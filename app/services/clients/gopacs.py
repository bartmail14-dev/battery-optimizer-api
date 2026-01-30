"""
===============================================================================
GOPACS CLIENT - Congestiemanagement Platform
===============================================================================

Client voor het ophalen van GOPACS (Grid Operators Platform for Congestion
Solutions) marktdata. GOPACS is het Nederlandse platform waar netbeheerders
flexibiliteit inkopen om congestie te managen.

BRONNEN:
- GOPACS Platform: https://en.gopacs.eu/
- Netbeheer Nederland Capaciteitskaart: https://capaciteitskaart.netbeheernederland.nl/
- TenneT Congestiemanagement publicaties

NOTITIE:
- GOPACS is operationeel sinds 2019
- Voornamelijk actief in gebieden met veel zon/wind (Zeeland, Noord-Holland, Groningen)
- Tarieven variëren per event en locatie (€0.10-0.25/kWh)
- Minimum deelname: 100 kW (kleinere assets via aggregator)
- Verwachte groei: congestie-uren stijgen jaarlijks met 20-30%

API:
- GOPACS heeft geen publieke API
- Data wordt geaggregeerd uit:
  1. Netbeheer Nederland publicaties
  2. ACM monitorrapporten
  3. Historische event data
===============================================================================
"""

import httpx
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import os

from app.models.enrichment import GOPACSData


class GOPACSClient:
    """
    GOPACS congestiemanagement data client.

    GOPACS werkt als volgt:
    1. Netbeheerder detecteert (verwachte) congestie
    2. GOPACS publiceert flexibiliteitsverzoek
    3. Marktpartijen bieden vermogensreductie aan
    4. GOPACS selecteert goedkoopste biedingen
    5. Activatie en verrekening

    Typische GOPACS events:
    - Duur: 2-6 uur
    - Vermogen: 1-50 MW per event
    - Prijs: €0.10-0.25/kWh (marktgebaseerd)
    - Frequentie: ~200 uur/jaar (groeiend)
    """

    # Netbeheer Nederland capaciteitskaart API
    CAPACITEITSKAART_URL = "https://capaciteitskaart.netbeheernederland.nl/api"

    # Regio-specifieke congestie factoren (gebaseerd op 2024 data)
    REGIO_FACTOREN = {
        # Hoge congestie (veel zon/wind, beperkte netcapaciteit)
        "zeeland": 1.5,
        "noord-holland-noord": 1.4,
        "groningen": 1.3,
        "friesland": 1.2,
        "flevoland": 1.2,

        # Gemiddelde congestie
        "gelderland": 1.0,
        "overijssel": 1.0,
        "utrecht": 1.0,
        "zuid-holland": 0.9,

        # Lage congestie (sterker netwerk)
        "noord-brabant": 0.8,
        "limburg": 0.7,

        # Default
        "default": 1.0
    }

    # Verwachte groei congestie-uren per jaar (%)
    GROEI_PERCENTAGE = 0.25  # 25% jaarlijkse groei verwacht

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        """Sluit HTTP client connectie."""
        await self.client.aclose()

    async def get_gopacs_data(
        self,
        postcode: Optional[str] = None,
        regio: Optional[str] = None
    ) -> GOPACSData:
        """
        Haal GOPACS congestiemanagement data op.

        Args:
            postcode: Nederlandse postcode voor regio-bepaling
            regio: Directe regio specificatie (overschrijft postcode)

        Returns:
            GOPACSData met tarieven en verwachte events
        """
        # Bepaal regio
        effectieve_regio = regio
        if not effectieve_regio and postcode:
            effectieve_regio = self._postcode_naar_regio(postcode)

        # Probeer live data
        try:
            live_data = await self._get_live_data(effectieve_regio)
            if live_data:
                return live_data
        except Exception as e:
            print(f"GOPACS live data error: {e}")

        # Fallback naar historische data
        return self._fallback(effectieve_regio)

    async def _get_live_data(self, regio: Optional[str]) -> Optional[GOPACSData]:
        """
        Probeer live GOPACS data op te halen.

        NOTITIE:
        GOPACS heeft geen publieke API. Deze functie is voorbereid voor
        toekomstige integratie met eventuele API of scraping van publicaties.
        """
        # Toekomstige implementatie:
        # - Netbeheer NL API voor actuele congestie events
        # - GOPACS publicaties scrapen
        # - TenneT congestiemanagement data

        # Voor nu: return None om fallback te triggeren
        return None

    async def get_recent_events(
        self,
        regio: Optional[str] = None,
        days: int = 30
    ) -> List[Dict]:
        """
        Haal recente GOPACS events op.

        Returns:
            Lijst van recente congestie events
        """
        # Dit zou in productie van GOPACS API komen
        # Voor nu: voorbeelddata gebaseerd op typische events
        return self._generate_sample_events(regio, days)

    def _postcode_naar_regio(self, postcode: str) -> str:
        """
        Converteer postcode naar regio voor congestie-factor bepaling.

        Gebaseerd op eerste 2 cijfers van postcode.
        """
        try:
            pc_prefix = int(postcode[:2])
        except (ValueError, IndexError):
            return "default"

        # Postcode ranges per regio (vereenvoudigd)
        if pc_prefix in range(43, 46) or pc_prefix in range(44, 47):
            return "zeeland"
        elif pc_prefix in range(17, 19) or pc_prefix in range(14, 17):
            return "noord-holland-noord"
        elif pc_prefix in range(96, 100) or pc_prefix in range(91, 96):
            return "groningen"
        elif pc_prefix in range(84, 91):
            return "friesland"
        elif pc_prefix in range(82, 84) or pc_prefix == 38:
            return "flevoland"
        elif pc_prefix in range(65, 70) or pc_prefix in range(38, 42):
            return "gelderland"
        elif pc_prefix in range(74, 82):
            return "overijssel"
        elif pc_prefix in range(34, 38):
            return "utrecht"
        elif pc_prefix in range(26, 34) or pc_prefix in range(22, 26):
            return "zuid-holland"
        elif pc_prefix in range(46, 56):
            return "noord-brabant"
        elif pc_prefix in range(56, 65):
            return "limburg"
        else:
            return "default"

    def _get_regio_factor(self, regio: Optional[str]) -> float:
        """Haal regio-specifieke congestie factor op."""
        if not regio:
            return self.REGIO_FACTOREN["default"]
        return self.REGIO_FACTOREN.get(regio.lower(), self.REGIO_FACTOREN["default"])

    def _fallback(self, regio: Optional[str] = None) -> GOPACSData:
        """
        Fallback GOPACS data gebaseerd op historische gemiddelden.

        BRONNEN:
        - ACM Elektriciteitsmonitor 2024
        - Netbeheer Nederland jaarverslagen
        - GOPACS publicaties

        Basiswaarden (nationaal gemiddelde):
        - Tarief: €0.15/kWh (range €0.10-0.25)
        - Uren: 200/jaar (sterk groeiend)
        """
        regio_factor = self._get_regio_factor(regio)

        # Basis verwachte uren (nationaal gemiddelde 2024)
        basis_uren = 200.0

        # Pas aan voor regio
        verwachte_uren = basis_uren * regio_factor

        return GOPACSData(
            bron="Fallback (historisch gemiddelde 2024)",
            gem_tarief_eur_kwh=0.15,
            min_tarief_eur_kwh=0.10,
            max_tarief_eur_kwh=0.25,
            verwachte_uren_per_jaar=round(verwachte_uren, 0),
            regio=regio,
            regio_factor=regio_factor,
            minimum_vermogen_kw=100.0
        )

    def _generate_sample_events(
        self,
        regio: Optional[str],
        days: int
    ) -> List[Dict]:
        """
        Genereer voorbeelddata voor recente events.

        Dit simuleert typische GOPACS events voor UI/testing.
        In productie zou dit van de echte API komen.
        """
        import random

        regio_factor = self._get_regio_factor(regio)
        events = []

        # Gemiddeld aantal events per maand: 15-20 (afhankelijk van regio)
        gem_events_per_maand = int(18 * regio_factor)
        num_events = int((days / 30) * gem_events_per_maand)

        now = datetime.now()

        for i in range(num_events):
            # Random datum in de periode
            event_date = now - timedelta(days=random.randint(1, days))

            # Typische event eigenschappen
            events.append({
                "datum": event_date.strftime("%Y-%m-%d"),
                "start_tijd": f"{random.randint(10, 16):02d}:00",
                "duur_uren": random.uniform(2, 6),
                "tarief_eur_kwh": round(random.uniform(0.10, 0.25), 3),
                "vermogen_mw": round(random.uniform(1, 20), 1),
                "regio": regio or "onbekend",
                "netbeheerder": random.choice([
                    "Liander", "Stedin", "Enexis", "TenneT"
                ]),
                "type": random.choice([
                    "afname_beperking",
                    "teruglevering_beperking",
                    "redispatch"
                ])
            })

        # Sorteer op datum (nieuwste eerst)
        events.sort(key=lambda x: x["datum"], reverse=True)
        return events

    def estimate_annual_revenue(
        self,
        vermogen_kw: float,
        regio: Optional[str] = None,
        beschikbaarheid: float = 0.9
    ) -> Dict[str, float]:
        """
        Schat jaarlijkse GOPACS opbrengst voor een batterij.

        Args:
            vermogen_kw: Beschikbaar vermogen in kW
            regio: Regio voor congestie-factor
            beschikbaarheid: Fractie van events waaraan deelgenomen wordt

        Returns:
            Dict met geschatte opbrengsten (conservatief, gemiddeld, optimistisch)
        """
        data = self._fallback(regio)

        # Alleen boven minimum vermogen
        if vermogen_kw < data.minimum_vermogen_kw:
            return {
                "conservatief": 0,
                "gemiddeld": 0,
                "optimistisch": 0,
                "reden": f"Vermogen ({vermogen_kw} kW) onder minimum ({data.minimum_vermogen_kw} kW)"
            }

        # Bereken verwachte opbrengst
        # Aanname: gemiddelde activatieduur 3 uur per event
        gem_event_duur = 3.0

        # Energie per jaar = uren * vermogen * beschikbaarheid
        energie_kwh = data.verwachte_uren_per_jaar * vermogen_kw * beschikbaarheid

        return {
            "conservatief": round(energie_kwh * data.min_tarief_eur_kwh * 0.7, 2),
            "gemiddeld": round(energie_kwh * data.gem_tarief_eur_kwh, 2),
            "optimistisch": round(energie_kwh * data.max_tarief_eur_kwh * 1.2, 2),
            "verwachte_uren": data.verwachte_uren_per_jaar,
            "regio_factor": data.regio_factor
        }
