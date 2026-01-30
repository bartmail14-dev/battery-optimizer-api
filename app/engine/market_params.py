"""
===============================================================================
DUTCH MARKET PARAMETERS - 2024/2025
===============================================================================

Marktparameters voor de Nederlandse energiemarkt, gebruikt voor revenue stream
berekeningen. Gebaseerd op ACM tarieven, ENTSO-E data, en TenneT publicaties.

BRONNEN:
- ACM: Capaciteitstarieven netbeheerders 2024
- TenneT: FCR/aFRR auction results 2024
- GOPACS: Congestiemanagement statistieken
- ENTSO-E: Day-ahead prijzen Nederland

NOTITIE:
- Tarieven worden jaarlijks geüpdatet
- Sommige waarden zijn gemiddelden over 2023/2024
- Voor precisie, gebruik actuele marktdata waar mogelijk
===============================================================================
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class Netbeheerder(Enum):
    """Nederlandse netbeheerders met hun regio's."""
    LIANDER = "liander"          # Noord-Holland, Zuid-Holland, Gelderland, Flevoland
    STEDIN = "stedin"            # Rotterdam, Utrecht, Zeeland
    ENEXIS = "enexis"            # Noord-Brabant, Limburg, Groningen, Overijssel
    WESTLAND = "westland"        # Westland (glastuinbouw)
    COTEQ = "coteq"              # Oost-Twente
    RENDO = "rendo"              # Drenthe, Overijssel


@dataclass
class CapacityTariffs:
    """Capaciteitstarieven per netbeheerder (2024)."""
    # €/kW/maand voor verschillende aansluitcategorieën

    # Kleinverbruik (< 3x80A)
    kleinverbruik_per_kw_month: float = 2.50

    # Grootverbruik laagspanning (LS)
    grootverbruik_ls_per_kw_month: float = 5.20

    # Grootverbruik middenspanning (MS)
    grootverbruik_ms_per_kw_month: float = 3.80

    # Boete bij overschrijding gecontracteerd vermogen
    overschrijding_factor: float = 2.5  # 2.5x normaal tarief


# Capaciteitstarieven per netbeheerder (€/kW/maand, grootverbruik LS, 2024)
CAPACITY_TARIFFS_PER_NETBEHEERDER: Dict[Netbeheerder, float] = {
    Netbeheerder.LIANDER: 5.45,
    Netbeheerder.STEDIN: 5.20,
    Netbeheerder.ENEXIS: 4.95,
    Netbeheerder.WESTLAND: 5.80,
    Netbeheerder.COTEQ: 5.15,
    Netbeheerder.RENDO: 5.10,
}


@dataclass
class EnergyTariffs:
    """Energietarieven voor arbitrage en zelfconsumptie."""

    # Commodity prijzen (€/kWh, exclusief belasting/ODE)
    inkoop_piek: float = 0.12          # 07:00-21:00
    inkoop_dal: float = 0.08           # 21:00-07:00 + weekend

    # Terugleververgoeding (gemiddeld)
    teruglevering: float = 0.07

    # Day-ahead spread (gemiddeld 2024)
    day_night_spread: float = 0.05     # Typisch €0.03-0.08

    # Piekuren definitie
    peak_hours_start: int = 7
    peak_hours_end: int = 21


@dataclass
class FCRMarketParams:
    """FCR (Frequency Containment Reserve) marktparameters."""

    # Capaciteitsprijs (€/MW/uur, gemiddeld 2024)
    capacity_price_mw_hour: float = 12.0

    # Minimum capaciteit voor deelname
    minimum_capacity_mw: float = 1.0

    # Pooling toegestaan (via aggregator)
    pooling_minimum_kw: float = 100.0  # Vaak 100 kW minimum bij aggregator

    # Beschikbaarheidseis
    availability_requirement: float = 0.97  # 97% uptime vereist

    # Activatietijd
    activation_time_seconds: float = 30.0

    # Prequalificatie kosten (eenmalig, geschat)
    prequalification_cost_eur: float = 5000.0

    # Aggregator fee (% van opbrengst)
    aggregator_fee_percent: float = 15.0


@dataclass
class AFRRMarketParams:
    """aFRR (automatic Frequency Restoration Reserve) marktparameters."""

    # Capaciteitsprijs (€/MW/uur, gemiddeld 2024)
    capacity_price_mw_hour: float = 8.0

    # Energievergoeding bij activatie (€/MWh)
    energy_price_mwh: float = 150.0  # Zeer variabel!

    # Activatiekans (% van beschikbare uren)
    activation_probability: float = 0.15  # ~15% van de tijd

    # Minimum capaciteit
    minimum_capacity_mw: float = 1.0

    # Activatietijd
    activation_time_minutes: float = 5.0

    # Aggregator fee
    aggregator_fee_percent: float = 12.0


@dataclass
class ImbalanceMarketParams:
    """Onbalansmarkt parameters."""

    # Gemiddelde onbalansprijs (€/MWh, 2024)
    average_price_mwh: float = 80.0

    # Standaarddeviatie (zeer volatiel)
    price_std_mwh: float = 100.0

    # Extreme prijzen komen voor
    max_price_mwh: float = 500.0
    min_price_mwh: float = -50.0

    # Beschikbaarheidsvergoeding bij BRP contract
    availability_fee_mw_hour: float = 2.50


@dataclass
class GOPACSParams:
    """GOPACS congestiemanagement parameters."""

    # Congestietarief (€/kWh tijdens congestie-event)
    congestion_tariff_kwh: float = 0.15

    # Verwachte congestie-uren per jaar (groeiend!)
    expected_hours_per_year: float = 200.0

    # Regio-specifieke factoren (sommige gebieden meer congestie)
    region_factors: Dict[str, float] = None

    # Minimale vermogen voor deelname
    minimum_capacity_kw: float = 100.0

    def __post_init__(self):
        if self.region_factors is None:
            self.region_factors = {
                "noord-holland": 1.3,   # Veel zonne-energie
                "zeeland": 1.5,         # Wind + beperkte netcapaciteit
                "groningen": 1.2,       # Wind
                "default": 1.0,
            }


@dataclass
class SelfConsumptionParams:
    """Parameters voor zelfconsumptie (PV buffering)."""

    # Verschil inkoop vs teruglevering (besparing per kWh gebufferd)
    spread_kwh: float = 0.05  # €0.12 inkoop - €0.07 teruglevering

    # Typisch percentage zonne-energie dat gebufferd kan worden
    typical_buffer_percentage: float = 0.30  # 30% van teruglevering

    # Saldering eindigt in 2027
    saldering_ends_year: int = 2027

    # Na saldering wordt spread groter
    post_saldering_spread_kwh: float = 0.10


@dataclass
class MarketParams:
    """Complete set marktparameters."""

    capacity: CapacityTariffs = None
    energy: EnergyTariffs = None
    fcr: FCRMarketParams = None
    afrr: AFRRMarketParams = None
    imbalance: ImbalanceMarketParams = None
    gopacs: GOPACSParams = None
    self_consumption: SelfConsumptionParams = None

    def __post_init__(self):
        if self.capacity is None:
            self.capacity = CapacityTariffs()
        if self.energy is None:
            self.energy = EnergyTariffs()
        if self.fcr is None:
            self.fcr = FCRMarketParams()
        if self.afrr is None:
            self.afrr = AFRRMarketParams()
        if self.imbalance is None:
            self.imbalance = ImbalanceMarketParams()
        if self.gopacs is None:
            self.gopacs = GOPACSParams()
        if self.self_consumption is None:
            self.self_consumption = SelfConsumptionParams()


# Default market parameters instance
DEFAULT_MARKET_PARAMS = MarketParams()


def get_capacity_tariff(
    netbeheerder: Optional[Netbeheerder] = None,
    postcode: Optional[str] = None
) -> float:
    """
    Haal capaciteitstarief op voor een netbeheerder of postcode.

    Args:
        netbeheerder: Directe netbeheerder specificatie
        postcode: Nederlandse postcode (4 cijfers + 2 letters)

    Returns:
        Capaciteitstarief in €/kW/maand
    """
    if netbeheerder:
        return CAPACITY_TARIFFS_PER_NETBEHEERDER.get(
            netbeheerder,
            DEFAULT_MARKET_PARAMS.capacity.grootverbruik_ls_per_kw_month
        )

    if postcode:
        # Simpele mapping op basis van eerste 2 cijfers
        pc_prefix = int(postcode[:2])

        # Liander: 10-19 (Amsterdam e.o.), 38-39 (Flevoland), etc.
        if pc_prefix in range(10, 20) or pc_prefix in range(38, 40):
            return CAPACITY_TARIFFS_PER_NETBEHEERDER[Netbeheerder.LIANDER]

        # Stedin: 30-34 (Rotterdam/Utrecht)
        if pc_prefix in range(30, 35):
            return CAPACITY_TARIFFS_PER_NETBEHEERDER[Netbeheerder.STEDIN]

        # Enexis: 50-59 (Brabant), 60-69 (Limburg), 90-99 (Groningen)
        if pc_prefix in range(50, 70) or pc_prefix in range(90, 100):
            return CAPACITY_TARIFFS_PER_NETBEHEERDER[Netbeheerder.ENEXIS]

    # Default
    return DEFAULT_MARKET_PARAMS.capacity.grootverbruik_ls_per_kw_month
