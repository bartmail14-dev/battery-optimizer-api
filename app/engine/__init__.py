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

__all__ = [
    'MonteCarloEngine',
    'BatteryDispatchSimulator',
    'DegradationModel',
    'BatteryChemistry',
    'TCOCalculator',
]
