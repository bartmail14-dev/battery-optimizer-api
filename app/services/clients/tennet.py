"""TenneT API client for imbalance prices."""

import httpx
from datetime import datetime
import os
from typing import Optional
import statistics

from app.models.enrichment import OnbalansPrijzen


class TennetClient:
    """
    TenneT API client voor onbalansprijzen.

    Token aanvragen: https://www.tennet.eu/registration-api-token
    """

    BASE_URL = "https://api.tennet.eu"

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("TENNET_API_TOKEN")
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.client = httpx.AsyncClient(timeout=30.0, headers=headers)

    async def close(self):
        await self.client.aclose()

    async def get_imbalance_prices(
        self,
        start: datetime,
        end: datetime
    ) -> OnbalansPrijzen:
        """
        Haal onbalansprijzen op.

        Args:
            start: Start datetime
            end: End datetime

        Returns:
            OnbalansPrijzen with imbalance price statistics
        """
        try:
            url = f"{self.BASE_URL}/transparency/settlementprices"
            params = {
                "startDate": start.strftime("%Y-%m-%d"),
                "endDate": end.strftime("%Y-%m-%d")
            }

            response = await self.client.get(url, params=params)

            if response.status_code == 200:
                data = response.json()
                return self._parse_response(data)
        except Exception as e:
            print(f"TenneT error: {e}")

        return self._fallback()

    def _parse_response(self, data: dict) -> OnbalansPrijzen:
        """Parse TenneT response."""
        tekort = []
        overschot = []

        for record in data.get('records', []):
            if 'tekort' in record:
                tekort.append(record['tekort'])
            if 'overschot' in record:
                overschot.append(record['overschot'])

        if not tekort:
            return self._fallback()

        gem_tekort = statistics.mean(tekort)

        return OnbalansPrijzen(
            bron="TenneT",
            gem_tekort_eur_mwh=round(gem_tekort, 2),
            gem_overschot_eur_mwh=round(statistics.mean(overschot), 2) if overschot else 0,
            max_tekort_eur_mwh=round(max(tekort), 2),
            volatiliteit_index=round(
                statistics.stdev(tekort) / gem_tekort, 2
            ) if gem_tekort > 0 and len(tekort) > 1 else 0
        )

    def _fallback(self) -> OnbalansPrijzen:
        """Fallback with historical averages."""
        return OnbalansPrijzen(
            bron="Fallback (historisch gemiddelde)",
            gem_tekort_eur_mwh=120.0,
            gem_overschot_eur_mwh=40.0,
            max_tekort_eur_mwh=500.0,
            volatiliteit_index=0.8
        )
