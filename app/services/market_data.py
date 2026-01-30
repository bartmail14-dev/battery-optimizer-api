"""
===============================================================================
MARKET DATA SERVICE - Centrale Marktdata Orchestrator
===============================================================================

Dit is de hoofdservice voor alle marktdata. Deze service combineert data van:
- ENTSO-E (day-ahead prijzen)
- TenneT (onbalansprijzen, FCR, aFRR)
- GOPACS (congestiemanagement)

De service zorgt voor:
1. Parallelle data ophaling (snelheid)
2. Caching van resultaten (rate limiting)
3. Fallback naar historische data (robuustheid)
4. Aggregatie tot één MarketDataSummary

GEBRUIK:
    service = await get_market_data_service()
    market_data = await service.get_all_market_data(postcode="1012AB")

NOTITIE:
- Alle externe API calls worden parallel uitgevoerd
- Bij API failure worden fallback waarden gebruikt
- Data wordt gecached voor 15 minuten (configureerbaar)
===============================================================================
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import hashlib
import json

from app.models.enrichment import (
    MarktPrijzen, OnbalansPrijzen, FCRPrijzen, AFRRPrijzen,
    GOPACSData, MarketDataSummary
)
from app.services.clients.entsoe import ENTSOEClient
from app.services.clients.tennet import TennetClient
from app.services.clients.fcr_afrr import FCRAFRRClient
from app.services.clients.gopacs import GOPACSClient


class MarketDataCache:
    """
    Eenvoudige in-memory cache voor marktdata.

    NOTITIE:
    - Voorkomt te veel API calls (rate limiting)
    - Default TTL: 15 minuten
    - In productie: vervang door Redis voor multi-instance support
    """

    def __init__(self, default_ttl_minutes: int = 15):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._default_ttl = timedelta(minutes=default_ttl_minutes)

    def _make_key(self, *args) -> str:
        """Genereer cache key uit argumenten."""
        key_str = json.dumps(args, sort_keys=True, default=str)
        return hashlib.md5(key_str.encode()).hexdigest()

    def get(self, *args) -> Optional[Any]:
        """Haal waarde uit cache indien niet verlopen."""
        key = self._make_key(*args)
        if key in self._cache:
            entry = self._cache[key]
            if datetime.now() < entry['expires']:
                return entry['value']
            # Verlopen, verwijder
            del self._cache[key]
        return None

    def set(self, value: Any, ttl: Optional[timedelta] = None, *args):
        """Sla waarde op in cache."""
        key = self._make_key(*args)
        expires = datetime.now() + (ttl or self._default_ttl)
        self._cache[key] = {
            'value': value,
            'expires': expires
        }

    def clear(self):
        """Wis alle cache entries."""
        self._cache.clear()


class MarketDataService:
    """
    Centrale service voor alle marktdata ophaling.

    Deze service is de "single point of contact" voor marktdata:
    - Coördineert alle externe API clients
    - Voert calls parallel uit voor snelheid
    - Handelt errors graceful af met fallbacks
    - Cached resultaten om rate limits te respecteren

    Clients:
    - ENTSO-E: Day-ahead stroomprijzen (EUR/MWh)
    - TenneT: Onbalansprijzen (EUR/MWh)
    - FCR/aFRR: Balancing capacity prijzen (EUR/MW/uur)
    - GOPACS: Congestietarieven (EUR/kWh)
    """

    def __init__(self):
        # API Clients
        self.entsoe = ENTSOEClient()
        self.tennet = TennetClient()
        self.fcr_afrr = FCRAFRRClient()
        self.gopacs = GOPACSClient()

        # Cache
        self._cache = MarketDataCache(default_ttl_minutes=15)

    async def close(self):
        """Sluit alle client connecties."""
        await asyncio.gather(
            self.entsoe.close(),
            self.tennet.close(),
            self.fcr_afrr.close(),
            self.gopacs.close()
        )

    async def get_all_market_data(
        self,
        postcode: Optional[str] = None,
        lookback_days: int = 365,
        use_cache: bool = True
    ) -> MarketDataSummary:
        """
        Haal alle marktdata op in één call.

        Args:
            postcode: Nederlandse postcode (voor GOPACS regio-bepaling)
            lookback_days: Aantal dagen historie voor prijsstatistieken
            use_cache: Of cache gebruikt moet worden

        Returns:
            MarketDataSummary met alle marktdata
        """
        # Check cache
        if use_cache:
            cached = self._cache.get("all_market_data", postcode, lookback_days)
            if cached:
                return cached

        now = datetime.now()
        start = now - timedelta(days=lookback_days)
        start_30d = now - timedelta(days=30)

        warnings = []
        bronnen = []

        # =====================================================================
        # PARALLELLE DATA OPHALING
        # =====================================================================
        results = await asyncio.gather(
            self.entsoe.get_day_ahead_prices(start, now),
            self.tennet.get_imbalance_prices(start_30d, now),
            self.fcr_afrr.get_fcr_prices(start_30d, now),
            self.fcr_afrr.get_afrr_prices(start_30d, now),
            self.gopacs.get_gopacs_data(postcode=postcode),
            return_exceptions=True
        )

        day_ahead, onbalans, fcr, afrr, gopacs = results

        # =====================================================================
        # VERWERK RESULTATEN
        # =====================================================================

        # Day-ahead prijzen (ENTSO-E)
        if isinstance(day_ahead, Exception):
            warnings.append(f"ENTSO-E error: {day_ahead}")
            day_ahead = self.entsoe._fallback_prices(start, now)
        else:
            bronnen.append("ENTSO-E Transparency")

        # Onbalansprijzen (TenneT)
        if isinstance(onbalans, Exception):
            warnings.append(f"TenneT onbalans error: {onbalans}")
            onbalans = self.tennet._fallback()
        else:
            bronnen.append("TenneT Imbalance")

        # FCR prijzen
        if isinstance(fcr, Exception):
            warnings.append(f"FCR error: {fcr}")
            fcr = self.fcr_afrr._fcr_fallback()
        else:
            bronnen.append("TenneT/ENTSO-E FCR")

        # aFRR prijzen
        if isinstance(afrr, Exception):
            warnings.append(f"aFRR error: {afrr}")
            afrr = self.fcr_afrr._afrr_fallback()
        else:
            bronnen.append("TenneT aFRR")

        # GOPACS data
        if isinstance(gopacs, Exception):
            warnings.append(f"GOPACS error: {gopacs}")
            gopacs = self.gopacs._fallback()
        else:
            bronnen.append("GOPACS/Netbeheer NL")

        # =====================================================================
        # BOUW RESULTAAT
        # =====================================================================
        compleetheid = 1.0 - (len(warnings) * 0.15)
        compleetheid = max(0.5, min(1.0, compleetheid))

        result = MarketDataSummary(
            timestamp=now,
            day_ahead=day_ahead,
            onbalans=onbalans,
            fcr=fcr,
            afrr=afrr,
            gopacs=gopacs,
            data_compleetheid=round(compleetheid, 2),
            bronnen=bronnen,
            warnings=warnings
        )

        # Cache resultaat
        if use_cache:
            self._cache.set(result, None, "all_market_data", postcode, lookback_days)

        return result

    # =========================================================================
    # INDIVIDUELE DATA OPHALING
    # =========================================================================

    async def get_day_ahead_prices(
        self,
        start: datetime,
        end: datetime
    ) -> MarktPrijzen:
        """Haal alleen day-ahead prijzen op."""
        return await self.entsoe.get_day_ahead_prices(start, end)

    async def get_imbalance_prices(
        self,
        start: datetime,
        end: datetime
    ) -> OnbalansPrijzen:
        """Haal alleen onbalansprijzen op."""
        return await self.tennet.get_imbalance_prices(start, end)

    async def get_fcr_prices(
        self,
        start: datetime,
        end: datetime
    ) -> FCRPrijzen:
        """Haal alleen FCR prijzen op."""
        return await self.fcr_afrr.get_fcr_prices(start, end)

    async def get_afrr_prices(
        self,
        start: datetime,
        end: datetime
    ) -> AFRRPrijzen:
        """Haal alleen aFRR prijzen op."""
        return await self.fcr_afrr.get_afrr_prices(start, end)

    async def get_gopacs_data(
        self,
        postcode: Optional[str] = None,
        regio: Optional[str] = None
    ) -> GOPACSData:
        """Haal alleen GOPACS data op."""
        return await self.gopacs.get_gopacs_data(postcode=postcode, regio=regio)

    # =========================================================================
    # REVENUE STREAM HELPERS
    # =========================================================================

    def calculate_potential_revenues(
        self,
        market_data: MarketDataSummary,
        battery_kw: float,
        battery_kwh: float,
        annual_cycles: int = 365
    ) -> Dict[str, Dict[str, float]]:
        """
        Bereken potentiële revenues per revenue stream.

        Args:
            market_data: Actuele marktdata
            battery_kw: Batterij vermogen in kW
            battery_kwh: Batterij capaciteit in kWh
            annual_cycles: Verwacht aantal cycli per jaar

        Returns:
            Dict met revenue schattingen per stream
        """
        revenues = {}

        # =================================================================
        # 1. ARBITRAGE (day-ahead spreads)
        # =================================================================
        # Schatting: batterij kan 50% van theoretische spread realiseren
        spread = market_data.day_ahead.piek_gemiddelde - market_data.day_ahead.dal_gemiddelde
        arbitrage_per_cycle = battery_kwh * (spread / 1000) * 0.5  # /1000: MWh->kWh
        revenues["arbitrage"] = {
            "conservatief": round(arbitrage_per_cycle * annual_cycles * 0.6, 2),
            "gemiddeld": round(arbitrage_per_cycle * annual_cycles, 2),
            "optimistisch": round(arbitrage_per_cycle * annual_cycles * 1.4, 2),
            "eenheid": "EUR/jaar",
            "aannames": f"Spread €{spread:.2f}/MWh, {annual_cycles} cycli"
        }

        # =================================================================
        # 2. FCR
        # =================================================================
        if market_data.fcr and battery_kw >= 100:  # Min 100 kW voor pooling
            mw = battery_kw / 1000
            fcr_hourly = market_data.fcr.gem_capaciteit_eur_mw_hour
            # Aanname: 80% beschikbaarheid, 8000 uur deelname
            fcr_annual = mw * fcr_hourly * 8000 * 0.8
            # Minus aggregator fee (15%)
            fcr_net = fcr_annual * 0.85

            revenues["fcr"] = {
                "conservatief": round(fcr_net * 0.7, 2),
                "gemiddeld": round(fcr_net, 2),
                "optimistisch": round(fcr_net * 1.3, 2),
                "eenheid": "EUR/jaar",
                "aannames": f"€{fcr_hourly}/MW/uur, 80% beschikbaarheid, 15% aggregator fee"
            }
        else:
            revenues["fcr"] = {
                "conservatief": 0,
                "gemiddeld": 0,
                "optimistisch": 0,
                "reden": "Vermogen onder minimum (100 kW voor pooling)"
            }

        # =================================================================
        # 3. aFRR
        # =================================================================
        if market_data.afrr and battery_kw >= 100:
            mw = battery_kw / 1000
            afrr_hourly = market_data.afrr.gem_capaciteit_eur_mw_hour
            # Capaciteitsvergoeding
            afrr_cap = mw * afrr_hourly * 8000 * 0.75
            # Energievergoeding (15% activatiekans)
            activatie_uren = 8000 * market_data.afrr.activatie_kans
            afrr_energy = mw * (market_data.afrr.gem_energie_eur_mwh - market_data.day_ahead.gemiddelde_eur_mwh) * activatie_uren
            afrr_total = (afrr_cap + afrr_energy) * 0.88  # 12% aggregator fee

            revenues["afrr"] = {
                "conservatief": round(afrr_total * 0.7, 2),
                "gemiddeld": round(afrr_total, 2),
                "optimistisch": round(afrr_total * 1.3, 2),
                "eenheid": "EUR/jaar",
                "aannames": f"€{afrr_hourly}/MW/uur cap + €{market_data.afrr.gem_energie_eur_mwh}/MWh activatie"
            }
        else:
            revenues["afrr"] = {
                "conservatief": 0,
                "gemiddeld": 0,
                "optimistisch": 0,
                "reden": "Vermogen onder minimum (100 kW voor pooling)"
            }

        # =================================================================
        # 4. GOPACS
        # =================================================================
        if market_data.gopacs:
            gopacs_rev = self.gopacs.estimate_annual_revenue(
                vermogen_kw=battery_kw,
                regio=market_data.gopacs.regio
            )
            revenues["gopacs"] = gopacs_rev

        # =================================================================
        # 5. IMBALANCE
        # =================================================================
        if market_data.onbalans:
            # Onbalanshandel is risicovol, conservatieve schatting
            mw = battery_kw / 1000
            # Aanname: 5% van de tijd gunstige onbalans, 2 uur gem duur
            gunstige_uren = 8760 * 0.05
            # Gem winst per event: verschil tekort - commodity prijs
            gem_winst = market_data.onbalans.gem_tekort_eur_mwh - market_data.day_ahead.gemiddelde_eur_mwh
            imbalance_annual = mw * gem_winst * gunstige_uren * 0.3  # 30% realisatie

            revenues["imbalance"] = {
                "conservatief": round(imbalance_annual * 0.5, 2),
                "gemiddeld": round(imbalance_annual, 2),
                "optimistisch": round(imbalance_annual * 2, 2),
                "eenheid": "EUR/jaar",
                "aannames": "Hoog risico, sterk afhankelijk van handelsstrategie"
            }

        return revenues


# =============================================================================
# SINGLETON PATTERN
# =============================================================================
_market_service: Optional[MarketDataService] = None


async def get_market_data_service() -> MarketDataService:
    """
    Haal de singleton MarketDataService instantie op (of maak hem aan).

    Gebruik:
        service = await get_market_data_service()
        data = await service.get_all_market_data()
    """
    global _market_service
    if _market_service is None:
        _market_service = MarketDataService()
    return _market_service


async def close_market_data_service():
    """Sluit de singleton service af (voor shutdown)."""
    global _market_service
    if _market_service is not None:
        await _market_service.close()
        _market_service = None
