"""ENTSO-E Transparency Platform API client for day-ahead prices."""

import httpx
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
import statistics
import os

from app.models.enrichment import MarktPrijzen

ENTSOE_URL = "https://web-api.tp.entsoe.eu/api"
NL_BIDDING_ZONE = "10YNL----------L"


class ENTSOEClient:
    """
    ENTSO-E Transparency Platform client.

    API key aanvragen:
    1. Registreer op https://transparency.entsoe.eu/
    2. Email naar transparency@entsoe.eu met subject "Restful API access"
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ENTSOE_API_KEY")
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self.client.aclose()

    async def get_day_ahead_prices(
        self,
        start: datetime,
        end: datetime
    ) -> MarktPrijzen:
        """
        Haal day-ahead prijzen op.

        Args:
            start: Start datetime
            end: End datetime

        Returns:
            MarktPrijzen with statistics and optional hourly data
        """
        if not self.api_key:
            return self._fallback_prices(start, end)

        params = {
            "securityToken": self.api_key,
            "documentType": "A44",
            "processType": "A01",
            "in_Domain": NL_BIDDING_ZONE,
            "out_Domain": NL_BIDDING_ZONE,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }

        try:
            response = await self.client.get(ENTSOE_URL, params=params)
            response.raise_for_status()
            prices = self._parse_xml(response.text)
            return self._calculate_stats(prices, start, end)
        except Exception as e:
            print(f"ENTSO-E error: {e}")
            return self._fallback_prices(start, end)

    def _parse_xml(self, xml_text: str) -> List[Dict]:
        """Parse ENTSO-E XML response."""
        prices = []
        ns = {'ns': 'urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:0'}

        try:
            root = ET.fromstring(xml_text)
            for ts in root.findall('.//ns:TimeSeries', ns):
                period = ts.find('.//ns:Period', ns)
                if not period:
                    continue

                start_elem = period.find('ns:timeInterval/ns:start', ns)
                if not start_elem:
                    continue

                start_time = datetime.fromisoformat(
                    start_elem.text.replace('Z', '+00:00')
                )

                for point in period.findall('ns:Point', ns):
                    pos = int(point.find('ns:position', ns).text)
                    price_elem = point.find('ns:price.amount', ns)
                    if price_elem is not None:
                        ts_time = start_time + timedelta(hours=pos - 1)
                        prices.append({
                            'timestamp': ts_time.isoformat(),
                            'price_mwh': float(price_elem.text),
                            'hour': ts_time.hour
                        })
        except ET.ParseError:
            pass

        return prices

    def _calculate_stats(
        self,
        prices: List[Dict],
        start: datetime,
        end: datetime
    ) -> MarktPrijzen:
        """Bereken statistieken uit prijsdata."""
        if not prices:
            return self._fallback_prices(start, end)

        all_prices = [p['price_mwh'] for p in prices]
        piek_prices = [p['price_mwh'] for p in prices if 7 <= p['hour'] < 21]
        dal_prices = [p['price_mwh'] for p in prices if p['hour'] >= 21 or p['hour'] < 7]

        return MarktPrijzen(
            bron="ENTSO-E",
            periode_start=start,
            periode_eind=end,
            gemiddelde_eur_mwh=round(statistics.mean(all_prices), 2),
            min_eur_mwh=round(min(all_prices), 2),
            max_eur_mwh=round(max(all_prices), 2),
            std_dev=round(statistics.stdev(all_prices), 2) if len(all_prices) > 1 else 0,
            piek_gemiddelde=round(statistics.mean(piek_prices), 2) if piek_prices else 0,
            dal_gemiddelde=round(statistics.mean(dal_prices), 2) if dal_prices else 0,
            uurprijzen=prices
        )

    def _fallback_prices(self, start: datetime, end: datetime) -> MarktPrijzen:
        """Fallback bij API falen met historische gemiddelden."""
        return MarktPrijzen(
            bron="Fallback (historisch gemiddelde 2024)",
            periode_start=start,
            periode_eind=end,
            gemiddelde_eur_mwh=80.0,
            min_eur_mwh=20.0,
            max_eur_mwh=250.0,
            std_dev=50.0,
            piek_gemiddelde=95.0,
            dal_gemiddelde=65.0,
            uurprijzen=None
        )
