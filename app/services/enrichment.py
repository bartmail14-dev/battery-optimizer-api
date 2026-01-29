"""
===============================================================================
DATA ENRICHMENT SERVICE - Hoofdservice
===============================================================================

Dit is de kern van de data verrijking. Deze service haalt automatisch alle
externe data op die nodig is voor een nauwkeurige batterij-analyse.

NOTITIE:
Deze service is de "orchestrator" - hij coördineert alle andere services:
1. Bepaalt netbeheerder op basis van postcode
2. Haalt ACM tarieven op
3. Checkt congestiestatus via Netbeheer NL
4. Haalt stroomprijzen op via ENTSO-E
5. Haalt onbalansprijzen op via TenneT
6. Berekent energiebelasting
7. Berekent subsidies (EIA, MIA, ISDE)
8. Schat PV productie

Alle API calls worden parallel uitgevoerd voor snelheid (asyncio.gather).
Als een externe API faalt, worden fallback waarden gebruikt.

Gebruik:
    service = await get_service()
    resultaat = await service.enrich(postcode="1012AB", verbruik_kwh=50000, ...)
===============================================================================
"""

from datetime import datetime, timedelta
from typing import Optional
import asyncio

from app.models.enrichment import (
    EnrichmentResultaat, Netbeheerder, CongestieStatus
)
from app.services.data.postcode_mapping import get_netbeheerder
from app.services.data.acm_tarieven import get_tarieven
from app.services.calculators.tax import bereken_energiebelasting
from app.services.calculators.subsidy import bereken_subsidies
from app.services.calculators.grid_costs import bereken_netkosten
from app.services.clients.entsoe import ENTSOEClient
from app.services.clients.tennet import TennetClient
from app.services.clients.netbeheer import NetbeheerClient
from app.services.clients.knmi import schat_pv_productie


class EnrichmentService:
    """
    Hoofdservice die alle data enrichment coördineert.

    NOTITIE:
    Dit is een "singleton" - er bestaat maar één instantie van deze service.
    Dit voorkomt dat we steeds nieuwe HTTP connecties maken naar externe APIs.

    De service houdt connecties open naar:
    - ENTSO-E (Europese stroomprijzen)
    - TenneT (Nederlandse onbalansprijzen)
    - Netbeheer Nederland (congestiekaart)
    """

    def __init__(self):
        """
        Initialiseert de externe API clients.

        NOTITIE:
        Elke client heeft zijn eigen configuratie en API key (uit environment).
        De clients gebruiken httpx voor async HTTP requests.
        """
        self.entsoe = ENTSOEClient()      # Day-ahead stroomprijzen
        self.tennet = TennetClient()       # Onbalansprijzen
        self.netbeheer = NetbeheerClient() # Congestiestatus

    async def close(self):
        """
        Sluit alle client connecties netjes af.

        NOTITIE:
        Dit wordt aangeroepen bij shutdown van de API.
        Zie app/main.py -> lifespan() functie.
        """
        await asyncio.gather(
            self.entsoe.close(),
            self.tennet.close(),
            self.netbeheer.close()
        )

    async def enrich(
        self,
        postcode: str,
        verbruik_kwh: float,
        teruglevering_kwh: float = 0,
        piek_kw: float = 0,
        batterij_investering: float = 0,
        batterij_kwh: float = 0,
        pv_kwp: Optional[float] = None,
        is_zakelijk: bool = True
    ) -> EnrichmentResultaat:
        """
        Verrijk een energieprofiel met alle externe data.

        NOTITIE:
        Dit is de hoofdfunctie! Geef postcode + verbruik en je krijgt alles terug:
        - Welke netbeheerder (Liander, Stedin, Enexis, etc.)
        - Hoeveel je betaalt aan netkosten
        - Of er congestie is in je gebied
        - Actuele stroomprijzen
        - Hoeveel energiebelasting je betaalt
        - Welke subsidies je kunt krijgen (EIA, MIA)
        - Schatting van je PV installatie

        Args:
            postcode: Nederlandse postcode (bijv. "1012AB" of "1012")
            verbruik_kwh: Jaarlijks verbruik in kWh
            teruglevering_kwh: Jaarlijkse teruglevering (zonnepanelen) in kWh
            piek_kw: Hoogste piekvermogen in kW
            batterij_investering: Investeringsbedrag batterij in EUR
            batterij_kwh: Capaciteit batterij in kWh
            pv_kwp: Vermogen zonnepanelen in kWp (optioneel, wordt geschat)
            is_zakelijk: True voor zakelijk, False voor particulier

        Returns:
            EnrichmentResultaat: Alle verrijkte data in één object
        """
        warnings = []   # Verzamel waarschuwingen als iets misgaat
        bronnen = []    # Houd bij welke bronnen we gebruiken

        # =====================================================================
        # STAP 1: Netbeheerder bepalen op basis van postcode
        # =====================================================================
        # NOTITIE:
        # Nederland heeft 6 grote netbeheerders. Op basis van de postcode
        # bepalen we welke netbeheerder van toepassing is.
        netbeheerder = get_netbeheerder(postcode)
        bronnen.append("Postcode mapping")

        # =====================================================================
        # STAP 2: ACM tarieven ophalen
        # =====================================================================
        # NOTITIE:
        # De ACM (Autoriteit Consument & Markt) stelt elk jaar de maximale
        # tarieven vast die netbeheerders mogen rekenen. Dit zijn de 2025 tarieven.
        tarieven = get_tarieven(netbeheerder)
        bronnen.append("ACM tarieven 2025")

        # =====================================================================
        # STAP 3: Netkosten berekenen
        # =====================================================================
        # NOTITIE:
        # Netkosten bestaan uit:
        # - Vastrecht (vast bedrag per jaar)
        # - Capaciteitstarief (per kW piekvermogen)
        # - Transporttarief (per kWh verbruik)
        netkosten = bereken_netkosten(tarieven, verbruik_kwh, piek_kw)

        # =====================================================================
        # STAP 4: Externe API calls (parallel voor snelheid)
        # =====================================================================
        # NOTITIE:
        # We roepen 3 externe APIs tegelijk aan met asyncio.gather().
        # Dit is veel sneller dan ze achter elkaar aan te roepen!
        # Als één API faalt, krijgen we een Exception terug ipv een crash.
        now = datetime.now()
        jaar_geleden = now - timedelta(days=365)
        maand_geleden = now - timedelta(days=30)

        results = await asyncio.gather(
            self.netbeheer.get_congestie(postcode, netbeheerder),
            self.entsoe.get_day_ahead_prices(jaar_geleden, now),
            self.tennet.get_imbalance_prices(maand_geleden, now),
            return_exceptions=True  # Voorkom crash bij API fout
        )

        congestie, commodity, onbalans = results

        # --- Verwerk congestie resultaat ---
        if isinstance(congestie, Exception):
            warnings.append(f"Congestie ophalen mislukt: {congestie}")
            congestie = self.netbeheer._fallback(postcode, netbeheerder)
        else:
            bronnen.append("Netbeheer NL Capaciteitskaart")

        # --- Verwerk ENTSO-E resultaat ---
        if isinstance(commodity, Exception):
            warnings.append(f"ENTSO-E ophalen mislukt: {commodity}")
            commodity = self.entsoe._fallback_prices(jaar_geleden, now)
        else:
            bronnen.append("ENTSO-E Transparency")

        # --- Verwerk TenneT resultaat ---
        if isinstance(onbalans, Exception):
            warnings.append(f"TenneT ophalen mislukt: {onbalans}")
            onbalans = None
        else:
            bronnen.append("TenneT")

        # =====================================================================
        # STAP 5: Energiebelasting berekenen
        # =====================================================================
        # NOTITIE:
        # Energiebelasting wordt berekend in schijven:
        # - Schijf 1: 0-10.000 kWh (hoogste tarief)
        # - Schijf 2: 10.000-50.000 kWh
        # - Schijf 3: >50.000 kWh (laagste tarief, voor grootverbruikers)
        # Zakelijke klanten krijgen een korting.
        energie_belasting = bereken_energiebelasting(verbruik_kwh, is_zakelijk)
        bronnen.append("Belastingdienst 2025")

        # =====================================================================
        # STAP 6: PV schatting (als er teruglevering is)
        # =====================================================================
        # NOTITIE:
        # Als iemand teruglevert, heeft hij zonnepanelen. We schatten dan:
        # - Hoeveel kWp zonnepanelen geïnstalleerd zijn
        # - Hoeveel ze per jaar produceren
        # Dit is gebaseerd op typische opbrengsten per regio (KNMI data).
        pv_schatting = None
        heeft_pv = teruglevering_kwh > 0 or (pv_kwp and pv_kwp > 0)
        effectieve_pv_kwp = pv_kwp or 0

        if teruglevering_kwh > 0:
            pv_schatting = schat_pv_productie(postcode, teruglevering_kwh)
            if not pv_kwp:
                effectieve_pv_kwp = pv_schatting.geschatte_capaciteit_kwp
            bronnen.append("KNMI zondata")

        # =====================================================================
        # STAP 7: Subsidies berekenen
        # =====================================================================
        # NOTITIE:
        # Voor batterijen zijn verschillende subsidies beschikbaar:
        # - EIA: Energie-investeringsaftrek (40% van investering aftrekbaar)
        # - MIA: Milieu-investeringsaftrek (voor grotere batterijen)
        # - ISDE: Subsidie voor particulieren
        # - Flex-e: Subsidie in congestiegebieden
        subsidies = bereken_subsidies(
            investering=batterij_investering,
            batterij_kwh=batterij_kwh,
            heeft_pv=heeft_pv,
            pv_kwp=effectieve_pv_kwp,
            congestie=congestie.afname_status,
            is_zakelijk=is_zakelijk
        )
        bronnen.append("RVO Energielijst 2025")

        # =====================================================================
        # STAP 8: Data compleetheid bepalen
        # =====================================================================
        # NOTITIE:
        # We geven aan hoe compleet de data is. Als externe APIs falen,
        # daalt de compleetheid. Dit helpt de gebruiker inschatten hoe
        # betrouwbaar de resultaten zijn.
        compleetheid = 1.0 - (len(warnings) * 0.15)
        compleetheid = max(0.5, min(1.0, compleetheid))

        # =====================================================================
        # RESULTAAT SAMENSTELLEN
        # =====================================================================
        return EnrichmentResultaat(
            postcode=postcode,
            timestamp=now,
            netbeheerder=netbeheerder,
            netbeheer_tarieven=tarieven,
            jaarlijkse_netkosten=netkosten,
            congestie=congestie,
            commodity_prijzen=commodity,
            onbalans_prijzen=onbalans,
            energie_belasting=energie_belasting,
            subsidies=subsidies,
            pv_schatting=pv_schatting,
            data_compleetheid=compleetheid,
            warnings=warnings,
            bronnen=bronnen
        )


# =============================================================================
# SINGLETON PATTERN
# =============================================================================
# NOTITIE:
# We maken maar één instantie van de EnrichmentService aan (singleton).
# Dit voorkomt dat we bij elke request nieuwe HTTP connecties maken.
_service: Optional[EnrichmentService] = None


async def get_service() -> EnrichmentService:
    """
    Haalt de singleton EnrichmentService instantie op (of maakt hem aan).

    NOTITIE:
    Gebruik deze functie om de service te krijgen:
        service = await get_service()
        result = await service.enrich(...)
    """
    global _service
    if _service is None:
        _service = EnrichmentService()
    return _service


async def close_service():
    """
    Sluit de singleton service af (voor shutdown).

    NOTITIE:
    Dit wordt aangeroepen vanuit app/main.py bij shutdown van de API.
    """
    global _service
    if _service is not None:
        await _service.close()
        _service = None
