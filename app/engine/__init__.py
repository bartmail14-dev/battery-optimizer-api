"""
===============================================================================
BATTERY OPTIMIZER ENGINE - Calculation Core
===============================================================================

Dit package bevat alle berekeningen voor batterij-optimalisatie:

- monte_carlo.py: Monte Carlo simulatie orchestrator (1000+ runs)
- simulation.py: Batterij dispatch simulatie
- degradation.py: Industrie-standaard degradatiemodel (Arrhenius + cycle aging)
- tco.py: Total Cost of Ownership met LCOS (Lazard methodologie)

REFERENTIES:
- NREL ATB 2024 (Annual Technology Baseline)
- Lazard LCOS v9.0 (Levelized Cost of Storage)
- IEC 62933-4-1 (Battery energy storage systems)
- Wang et al. (2011) - Cycle life degradation model

NOTITIE:
- Alle berekeningen gebeuren in de backend
- Frontend doet GEEN berekeningen, alleen visualisatie
- Nauwkeurigheid is kritisch - experts geven advies op basis van resultaten
===============================================================================
"""

from .monte_carlo import MonteCarloEngine
from .simulation import BatteryDispatchSimulator
from .degradation import DegradationModel, BatteryChemistry
from .tco import TCOCalculator
from .progress import ProgressEvent, ProgressEventType
from .revenue_streams import (
    RevenueCalculator,
    RevenueStreamType,
    RevenueStreamResult,
    MultiRevenueResult,
    QualificationStatus,
)
from .market_params import (
    MarketParams,
    DEFAULT_MARKET_PARAMS,
    get_capacity_tariff,
    Netbeheerder,
)
from .growth_projector import (
    GrowthProjector,
    GrowthScenario,
    GrowthScenarioType,
    GrowthProjectionResult,
    PREDEFINED_SCENARIOS,
    get_scenario,
)
from .sizing_advisor import (
    SizingAdvisor,
    SizingTier,
    SizingRecommendation,
    SizingRecommendations,
    BatteryConstraints,
)

__all__ = [
    # Monte Carlo & Simulation
    'MonteCarloEngine',
    'BatteryDispatchSimulator',
    'DegradationModel',
    'BatteryChemistry',
    'TCOCalculator',
    'ProgressEvent',
    'ProgressEventType',
    # Revenue Streams
    'RevenueCalculator',
    'RevenueStreamType',
    'RevenueStreamResult',
    'MultiRevenueResult',
    'QualificationStatus',
    # Market Parameters
    'MarketParams',
    'DEFAULT_MARKET_PARAMS',
    'get_capacity_tariff',
    'Netbeheerder',
    # Growth Projector
    'GrowthProjector',
    'GrowthScenario',
    'GrowthScenarioType',
    'GrowthProjectionResult',
    'PREDEFINED_SCENARIOS',
    'get_scenario',
    # Sizing Advisor
    'SizingAdvisor',
    'SizingTier',
    'SizingRecommendation',
    'SizingRecommendations',
    'BatteryConstraints',
]
