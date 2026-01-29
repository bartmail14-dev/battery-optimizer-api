"""Netbeheer Nederland capacity map API client."""

import httpx
from typing import Optional

from app.models.enrichment import CongestieInfo, CongestieStatus, Netbeheerder


class NetbeheerClient:
    """
    Client voor Netbeheer Nederland capaciteitskaart.

    Bron: https://capaciteitskaart.netbeheernederland.nl/
    """

    API_URL = "https://capaciteitskaart.netbeheernederland.nl/api/v1"

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self.client.aclose()

    async def get_congestie(
        self,
        postcode: str,
        netbeheerder: Netbeheerder
    ) -> CongestieInfo:
        """
        Haal congestiestatus op voor postcode.

        Args:
            postcode: Dutch postal code
            netbeheerder: Grid operator

        Returns:
            CongestieInfo with congestion status for the area
        """
        try:
            url = f"{self.API_URL}/capacity"
            response = await self.client.get(url, params={"postcode": postcode[:4]})

            if response.status_code == 200:
                data = response.json()
                return self._parse_response(data, postcode, netbeheerder)
        except Exception as e:
            print(f"Capaciteitskaart error: {e}")

        return self._fallback(postcode, netbeheerder)

    def _parse_response(
        self,
        data: dict,
        postcode: str,
        netbeheerder: Netbeheerder
    ) -> CongestieInfo:
        """Parse capaciteitskaart response."""
        status_map = {
            "groen": CongestieStatus.BESCHIKBAAR,
            "geel": CongestieStatus.BEPERKT,
            "oranje": CongestieStatus.WACHTRIJ,
            "rood": CongestieStatus.NIET_BESCHIKBAAR
        }

        afname = status_map.get(
            data.get("afname_status", "groen"),
            CongestieStatus.BESCHIKBAAR
        )
        teruglevering = status_map.get(
            data.get("teruglevering_status", "groen"),
            CongestieStatus.BESCHIKBAAR
        )

        return CongestieInfo(
            postcode=postcode,
            netbeheerder=netbeheerder,
            voedingsgebied=data.get("voedingsgebied"),
            afname_status=afname,
            teruglevering_status=teruglevering,
            wachtrij_afname_mw=data.get("wachtrij_mw"),
            wachtrij_aantal=data.get("wachtrij_aantal"),
            beschikbaar_afname_mw=data.get("beschikbaar_mw"),
            congestiemanagement_actief=data.get("cm_actief", False),
            export_beperking=teruglevering == CongestieStatus.NIET_BESCHIKBAAR,
            max_export_kw=data.get("max_export_kw")
        )

    def _fallback(self, postcode: str, netbeheerder: Netbeheerder) -> CongestieInfo:
        """Fallback when API is unavailable."""
        return CongestieInfo(
            postcode=postcode,
            netbeheerder=netbeheerder,
            afname_status=CongestieStatus.BESCHIKBAAR,
            teruglevering_status=CongestieStatus.BESCHIKBAAR,
            congestiemanagement_actief=False,
            export_beperking=False
        )
