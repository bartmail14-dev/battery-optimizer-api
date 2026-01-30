"""
===============================================================================
FCR & aFRR CLIENT - TenneT Balancing Markets
===============================================================================

Client voor het ophalen van FCR (Frequency Containment Reserve) en aFRR
(automatic Frequency Restoration Reserve) marktprijzen van TenneT.

BRONNEN:
- TenneT Balancing API: https://www.tennet.eu/nl/bedrijfsvoering/data-dashboard
- ENTSO-E Transparency Platform (backup): FCR cooperation prices
- Regelleistung.net (historisch): Europese FCR veiling resultaten

NOTITIE:
- FCR: Primaire reserve, activatie binnen 30 seconden
- aFRR: Secundaire reserve, activatie binnen 5-15 minuten
- Minimum deelname: 1 MW (pooling via aggregator vanaf 100 kW)
- Veilingen: FCR dagelijks, aFRR 4x per dag (PTUs)

API KEYS:
- TenneT API token nodig voor live data
- Fallback naar historische gemiddelden indien geen token
===============================================================================
"""

import httpx
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import statistics
import os

from app.models.enrichment import FCRPrijzen, AFRRPrijzen


class FCRAFRRClient:
    """
    Client voor TenneT FCR en aFRR marktdata.

    FCR (Frequency Containment Reserve):
    - Primaire frequentieregeling
    - Activatie bij frequentieafwijking > 10 mHz
    - Volledige activatie binnen 30 seconden
    - Capaciteitsprijs: €8-20/MW/uur (2024 gemiddelde: €12)

    aFRR (automatic Frequency Restoration Reserve):
    - Secundaire frequentieregeling
    - Activatie na FCR, herstelt frequentie naar 50 Hz
    - Volledige activatie binnen 5-15 minuten
    - Capaciteitsprijs + energievergoeding
    """

    BASE_URL = "https://api.tennet.eu"
    ENTSOE_FCR_URL = "https://web-api.tp.entsoe.eu/api"

    def __init__(
        self,
        tennet_token: Optional[str] = None,
        entsoe_key: Optional[str] = None
    ):
        self.tennet_token = tennet_token or os.getenv("TENNET_API_TOKEN")
        self.entsoe_key = entsoe_key or os.getenv("ENTSOE_API_KEY")

        headers = {}
        if self.tennet_token:
            headers["Authorization"] = f"Bearer {self.tennet_token}"

        self.client = httpx.AsyncClient(timeout=30.0, headers=headers)

    async def close(self):
        """Sluit HTTP client connectie."""
        await self.client.aclose()

    # =========================================================================
    # FCR PRIJZEN
    # =========================================================================

    async def get_fcr_prices(
        self,
        start: datetime,
        end: datetime
    ) -> FCRPrijzen:
        """
        Haal FCR capaciteitsprijzen op.

        Args:
            start: Start datetime
            end: End datetime

        Returns:
            FCRPrijzen met statistieken
        """
        # Probeer TenneT API
        try:
            if self.tennet_token:
                return await self._get_fcr_from_tennet(start, end)
        except Exception as e:
            print(f"TenneT FCR error: {e}")

        # Fallback naar ENTSO-E
        try:
            if self.entsoe_key:
                return await self._get_fcr_from_entsoe(start, end)
        except Exception as e:
            print(f"ENTSO-E FCR error: {e}")

        # Fallback naar historische data
        return self._fcr_fallback()

    async def _get_fcr_from_tennet(
        self,
        start: datetime,
        end: datetime
    ) -> FCRPrijzen:
        """Haal FCR data van TenneT API."""
        url = f"{self.BASE_URL}/balancing/fcr/auctionresults"
        params = {
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate": end.strftime("%Y-%m-%d")
        }

        response = await self.client.get(url, params=params)
        response.raise_for_status()

        data = response.json()
        return self._parse_fcr_response(data, "TenneT FCR")

    async def _get_fcr_from_entsoe(
        self,
        start: datetime,
        end: datetime
    ) -> FCRPrijzen:
        """
        Haal FCR data van ENTSO-E Transparency Platform.

        ENTSO-E documentType A25 = Contracted reserve prices
        """
        params = {
            "securityToken": self.entsoe_key,
            "documentType": "A25",
            "processType": "A51",  # FCR
            "controlArea_Domain": "10YNL----------L",
            "periodStart": start.strftime("%Y%m%d0000"),
            "periodEnd": end.strftime("%Y%m%d2300"),
        }

        response = await self.client.get(self.ENTSOE_FCR_URL, params=params)
        if response.status_code == 200:
            # Parse XML response
            prices = self._parse_entsoe_fcr_xml(response.text)
            if prices:
                return self._calculate_fcr_stats(prices, "ENTSO-E FCR")

        return self._fcr_fallback()

    def _parse_fcr_response(self, data: dict, bron: str) -> FCRPrijzen:
        """Parse TenneT FCR auction response."""
        prices = []
        laatste_veiling = None
        laatste_prijs = None

        for record in data.get('results', data.get('records', [])):
            prijs = record.get('price') or record.get('capacityPrice')
            if prijs:
                prices.append(float(prijs))
                # Track laatste veiling
                datum_str = record.get('date') or record.get('deliveryDate')
                if datum_str:
                    try:
                        datum = datetime.fromisoformat(datum_str.replace('Z', ''))
                        if laatste_veiling is None or datum > laatste_veiling:
                            laatste_veiling = datum
                            laatste_prijs = float(prijs)
                    except ValueError:
                        pass

        if not prices:
            return self._fcr_fallback()

        return FCRPrijzen(
            bron=bron,
            gem_capaciteit_eur_mw_hour=round(statistics.mean(prices), 2),
            min_capaciteit_eur_mw_hour=round(min(prices), 2),
            max_capaciteit_eur_mw_hour=round(max(prices), 2),
            laatste_veiling_datum=laatste_veiling,
            laatste_veiling_prijs=laatste_prijs
        )

    def _parse_entsoe_fcr_xml(self, xml_text: str) -> List[float]:
        """Parse ENTSO-E XML voor FCR prijzen."""
        import xml.etree.ElementTree as ET

        prices = []
        ns = {'ns': 'urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:0'}

        try:
            root = ET.fromstring(xml_text)
            for ts in root.findall('.//ns:TimeSeries', ns):
                for point in ts.findall('.//ns:Point', ns):
                    price_elem = point.find('ns:price.amount', ns)
                    if price_elem is not None:
                        prices.append(float(price_elem.text))
        except ET.ParseError:
            pass

        return prices

    def _calculate_fcr_stats(self, prices: List[float], bron: str) -> FCRPrijzen:
        """Bereken statistieken uit FCR prijslijst."""
        return FCRPrijzen(
            bron=bron,
            gem_capaciteit_eur_mw_hour=round(statistics.mean(prices), 2),
            min_capaciteit_eur_mw_hour=round(min(prices), 2),
            max_capaciteit_eur_mw_hour=round(max(prices), 2)
        )

    def _fcr_fallback(self) -> FCRPrijzen:
        """
        Fallback FCR prijzen gebaseerd op historische data 2024.

        BRON: TenneT FCR auction results 2024
        - Gemiddelde prijs: €12/MW/uur
        - Range: €5-25/MW/uur (afhankelijk van seizoen/weer)
        """
        return FCRPrijzen(
            bron="Fallback (historisch gemiddelde 2024)",
            gem_capaciteit_eur_mw_hour=12.0,
            min_capaciteit_eur_mw_hour=5.0,
            max_capaciteit_eur_mw_hour=25.0,
            availability_requirement=0.97
        )

    # =========================================================================
    # aFRR PRIJZEN
    # =========================================================================

    async def get_afrr_prices(
        self,
        start: datetime,
        end: datetime
    ) -> AFRRPrijzen:
        """
        Haal aFRR capaciteits- en energieprijzen op.

        Args:
            start: Start datetime
            end: End datetime

        Returns:
            AFRRPrijzen met statistieken
        """
        try:
            if self.tennet_token:
                return await self._get_afrr_from_tennet(start, end)
        except Exception as e:
            print(f"TenneT aFRR error: {e}")

        return self._afrr_fallback()

    async def _get_afrr_from_tennet(
        self,
        start: datetime,
        end: datetime
    ) -> AFRRPrijzen:
        """Haal aFRR data van TenneT API."""
        # Capaciteitsprijzen
        cap_url = f"{self.BASE_URL}/balancing/afrr/capacityprices"
        cap_params = {
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate": end.strftime("%Y-%m-%d")
        }

        cap_response = await self.client.get(cap_url, params=cap_params)
        cap_response.raise_for_status()
        cap_data = cap_response.json()

        # Energieprijzen
        energy_url = f"{self.BASE_URL}/balancing/afrr/activationprices"
        energy_response = await self.client.get(energy_url, params=cap_params)
        energy_data = energy_response.json() if energy_response.status_code == 200 else {}

        return self._parse_afrr_response(cap_data, energy_data)

    def _parse_afrr_response(
        self,
        cap_data: dict,
        energy_data: dict
    ) -> AFRRPrijzen:
        """Parse TenneT aFRR response."""
        cap_prices = []
        energy_prices = []

        for record in cap_data.get('results', cap_data.get('records', [])):
            prijs = record.get('price') or record.get('capacityPrice')
            if prijs:
                cap_prices.append(float(prijs))

        for record in energy_data.get('results', energy_data.get('records', [])):
            prijs = record.get('price') or record.get('energyPrice')
            if prijs:
                energy_prices.append(float(prijs))

        if not cap_prices:
            return self._afrr_fallback()

        return AFRRPrijzen(
            bron="TenneT aFRR",
            gem_capaciteit_eur_mw_hour=round(statistics.mean(cap_prices), 2),
            min_capaciteit_eur_mw_hour=round(min(cap_prices), 2),
            max_capaciteit_eur_mw_hour=round(max(cap_prices), 2),
            gem_energie_eur_mwh=round(statistics.mean(energy_prices), 2) if energy_prices else 150.0,
            max_energie_eur_mwh=round(max(energy_prices), 2) if energy_prices else 500.0,
            activatie_kans=0.15
        )

    def _afrr_fallback(self) -> AFRRPrijzen:
        """
        Fallback aFRR prijzen gebaseerd op historische data 2024.

        BRON: TenneT aFRR auction results 2024
        - Gemiddelde capaciteitsprijs: €8/MW/uur
        - Gemiddelde energieprijs: €150/MWh (zeer variabel!)
        - Activatiekans: ~15% van de tijd
        """
        return AFRRPrijzen(
            bron="Fallback (historisch gemiddelde 2024)",
            gem_capaciteit_eur_mw_hour=8.0,
            min_capaciteit_eur_mw_hour=3.0,
            max_capaciteit_eur_mw_hour=18.0,
            gem_energie_eur_mwh=150.0,
            max_energie_eur_mwh=500.0,
            activatie_kans=0.15,
            gem_activatie_duur_min=15.0
        )

    # =========================================================================
    # GECOMBINEERDE DATA
    # =========================================================================

    async def get_all_balancing_prices(
        self,
        start: datetime,
        end: datetime
    ) -> Dict[str, any]:
        """
        Haal FCR en aFRR prijzen tegelijk op.

        Returns:
            Dict met 'fcr' en 'afrr' prijzen
        """
        import asyncio

        fcr, afrr = await asyncio.gather(
            self.get_fcr_prices(start, end),
            self.get_afrr_prices(start, end),
            return_exceptions=True
        )

        return {
            'fcr': fcr if not isinstance(fcr, Exception) else self._fcr_fallback(),
            'afrr': afrr if not isinstance(afrr, Exception) else self._afrr_fallback()
        }
