"""
===============================================================================
SENSITIVITY ANALYSIS ENGINE
===============================================================================

Server-side sensitivity analysis to ensure consistent calculations.
This module is the SINGLE SOURCE OF TRUTH for all sensitivity calculations.

Frontend should NEVER perform its own NPV/payback calculations.
All requests must go through this module.

SOURCES:
- CPB Werkgroep Discontovoet (2020): Recommended discount rates for energy projects
- CE Delft (2024): Revenue stacking analysis for battery storage
- NREL BLAST (2023): Battery degradation modeling
===============================================================================
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from enum import Enum
import math

import structlog

logger = structlog.get_logger()


# =============================================================================
# FINANCIAL CONSTANTS (with sources)
# =============================================================================

# Source: CPB Werkgroep Discontovoet (2020)
# URL: https://www.cpb.nl/publicatie/rapport-werkgroep-discontovoet
DEFAULT_DISCOUNT_RATE = 0.06  # 6% for energy projects (range: 3-7%)

# Source: ECB monetary policy strategy
# URL: https://www.ecb.europa.eu/mopo/strategy/
DEFAULT_INFLATION_RATE = 0.025  # 2.5% (ECB target: 2%)

# Source: Industry standard, CE Delft (2024)
DEFAULT_PROJECT_YEARS = 15

# Source: CE Delft (2024), Berenschot (2023)
# Based on analysis of 50+ Dutch commercial battery projects
REVENUE_SPLIT = {
    "peak_shaving": 0.55,      # Range: 0.45-0.70
    "arbitrage": 0.30,         # Range: 0.20-0.40
    "self_consumption": 0.15,  # Range: 0.05-0.25
}

# Source: NREL BLAST (2023)
# LFP batteries at 25°C, 80% DoD, 1 cycle/day
DEFAULT_DEGRADATION_RATE = 0.02  # 2% per year


@dataclass
class SensitivityParameters:
    """Input parameters for sensitivity analysis."""
    energy_price_change_pct: float = 0.0      # -50 to +100
    capacity_tariff_change_pct: float = 0.0  # -50 to +100
    capex_change_pct: float = 0.0            # -30 to +50
    efficiency_change_pct: float = 0.0       # -20 to +10
    degradation_change_pct: float = 0.0      # -50 to +100
    discount_rate_change_pp: float = 0.0     # -2 to +3 percentage points
    inflation_rate_pct: float = 2.5          # For real vs nominal


@dataclass
class SensitivityResult:
    """Result of sensitivity analysis."""
    # Adjusted financial metrics
    adjusted_npv_nominal: float
    adjusted_npv_real: float
    adjusted_payback_years: float
    adjusted_annual_savings: float
    adjusted_capex: float

    # Changes from baseline
    npv_change_pct: float
    payback_change_pct: float
    savings_change_pct: float

    # Parameters used
    effective_discount_rate: float
    effective_inflation_rate: float
    effective_degradation_rate: float

    # Validity flags
    is_profitable: bool
    warnings: List[str]


class SensitivityAnalyzer:
    """
    Performs sensitivity analysis on battery investment scenarios.

    This is the AUTHORITATIVE source for all sensitivity calculations.
    Frontend must call this instead of calculating locally.
    """

    def __init__(
        self,
        discount_rate: float = DEFAULT_DISCOUNT_RATE,
        inflation_rate: float = DEFAULT_INFLATION_RATE,
        project_years: int = DEFAULT_PROJECT_YEARS,
        degradation_rate: float = DEFAULT_DEGRADATION_RATE
    ):
        self.discount_rate = discount_rate
        self.inflation_rate = inflation_rate
        self.project_years = project_years
        self.degradation_rate = degradation_rate

    def calculate_pvaf(self, discount_rate: float, years: int) -> float:
        """
        Calculate Present Value Annuity Factor.

        Formula: PVAF = (1 - (1 + r)^-n) / r

        This is the mathematically correct factor for discounting
        a stream of equal annual cash flows.
        """
        if discount_rate == 0:
            return float(years)
        return (1 - math.pow(1 + discount_rate, -years)) / discount_rate

    def calculate_real_discount_rate(
        self,
        nominal_rate: float,
        inflation_rate: float
    ) -> float:
        """
        Calculate real discount rate using Fisher equation.

        Formula: (1 + r_real) = (1 + r_nominal) / (1 + inflation)
        """
        return (1 + nominal_rate) / (1 + inflation_rate) - 1

    def analyze(
        self,
        baseline_npv: float,
        baseline_payback: float,
        baseline_savings: float,
        baseline_capex: float,
        params: SensitivityParameters
    ) -> SensitivityResult:
        """
        Perform sensitivity analysis with given parameter changes.

        All calculations use proper financial formulas with full transparency.
        """
        warnings = []

        # Calculate effective rates
        effective_discount = self.discount_rate + (params.discount_rate_change_pp / 100)
        effective_inflation = params.inflation_rate_pct / 100
        effective_degradation = self.degradation_rate * (1 + params.degradation_change_pct / 100)

        # Validate rates
        if effective_discount < 0.01:
            warnings.append("Discontovoet zeer laag (<1%) - resultaten mogelijk onrealistisch")
            effective_discount = max(0.01, effective_discount)
        if effective_discount > 0.15:
            warnings.append("Discontovoet zeer hoog (>15%) - resultaten mogelijk te conservatief")

        # Calculate savings impact from each revenue stream
        # Energy price affects arbitrage + self-consumption (45% of savings)
        energy_impact = (params.energy_price_change_pct / 100) * (
            REVENUE_SPLIT["arbitrage"] + REVENUE_SPLIT["self_consumption"]
        )

        # Capacity tariff affects peak shaving (55% of savings)
        capacity_impact = (params.capacity_tariff_change_pct / 100) * REVENUE_SPLIT["peak_shaving"]

        # Total savings multiplier
        savings_multiplier = 1 + energy_impact + capacity_impact

        # Efficiency directly impacts all savings
        efficiency_multiplier = 1 + (params.efficiency_change_pct / 100)

        # CAPEX multiplier
        capex_multiplier = 1 + (params.capex_change_pct / 100)

        # Calculate adjusted values
        adjusted_savings = baseline_savings * savings_multiplier * efficiency_multiplier
        adjusted_capex = baseline_capex * capex_multiplier

        if adjusted_savings <= 0:
            warnings.append("Negatieve besparingen - controleer parameters")
            adjusted_savings = max(1, adjusted_savings)  # Prevent division by zero

        # Calculate adjusted payback (simple)
        adjusted_payback = adjusted_capex / adjusted_savings if adjusted_savings > 0 else 999

        # Calculate NPV with degradation
        # NPV = -CAPEX + Σ(Savings_t * (1-degradation)^t / (1+r)^t)
        adjusted_npv_nominal = -adjusted_capex
        for year in range(1, self.project_years + 1):
            degraded_savings = adjusted_savings * math.pow(1 - effective_degradation, year - 1)
            discount_factor = math.pow(1 + effective_discount, year)
            adjusted_npv_nominal += degraded_savings / discount_factor

        # Calculate real NPV (inflation-adjusted)
        real_discount = self.calculate_real_discount_rate(effective_discount, effective_inflation)
        adjusted_npv_real = -adjusted_capex
        for year in range(1, self.project_years + 1):
            degraded_savings = adjusted_savings * math.pow(1 - effective_degradation, year - 1)
            # Real savings decrease with inflation
            real_savings = degraded_savings / math.pow(1 + effective_inflation, year)
            discount_factor = math.pow(1 + real_discount, year)
            adjusted_npv_real += real_savings / discount_factor

        # Calculate percentage changes
        npv_change = ((adjusted_npv_nominal - baseline_npv) / abs(baseline_npv) * 100
                      if baseline_npv != 0 else 0)
        payback_change = ((adjusted_payback - baseline_payback) / baseline_payback * 100
                          if baseline_payback > 0 else 0)
        savings_change = ((adjusted_savings - baseline_savings) / baseline_savings * 100
                          if baseline_savings > 0 else 0)

        # Add warnings for extreme scenarios
        if adjusted_payback > 20:
            warnings.append("Terugverdientijd > 20 jaar - investering waarschijnlijk niet rendabel")
        if adjusted_payback < 3:
            warnings.append("Terugverdientijd < 3 jaar - controleer aannames op realisme")
        if npv_change < -50:
            warnings.append("NPV gedaald met >50% - hoog risico scenario")

        logger.info(
            "Sensitivity analysis completed",
            npv_change_pct=round(npv_change, 1),
            payback_years=round(adjusted_payback, 1),
            warnings_count=len(warnings)
        )

        return SensitivityResult(
            adjusted_npv_nominal=round(adjusted_npv_nominal, 2),
            adjusted_npv_real=round(adjusted_npv_real, 2),
            adjusted_payback_years=round(min(adjusted_payback, 99), 2),
            adjusted_annual_savings=round(adjusted_savings, 2),
            adjusted_capex=round(adjusted_capex, 2),
            npv_change_pct=round(npv_change, 2),
            payback_change_pct=round(payback_change, 2),
            savings_change_pct=round(savings_change, 2),
            effective_discount_rate=round(effective_discount, 4),
            effective_inflation_rate=round(effective_inflation, 4),
            effective_degradation_rate=round(effective_degradation, 4),
            is_profitable=adjusted_npv_nominal > 0 and adjusted_payback < 20,
            warnings=warnings
        )


@dataclass
class StressScenario:
    """A predefined stress scenario based on historical data."""
    name: str
    description: str
    parameters: SensitivityParameters
    source: str
    historical_precedent: str


# =============================================================================
# STRESS SCENARIOS (based on historical data)
# =============================================================================

# Source: ACM Tarievenbesluit history, TenneT data, ENTSOE prices
STRESS_SCENARIOS: List[StressScenario] = [
    StressScenario(
        name="Energieprijzen crisis (2022-niveau)",
        description="Extreem hoge volatiliteit zoals in 2022",
        parameters=SensitivityParameters(
            energy_price_change_pct=80,  # Based on 2022 vs 2021 spread
        ),
        source="ENTSOE Transparency Platform, 2022 vs 2021 spreads",
        historical_precedent="2022 energiecrisis: day-ahead spreads +80%"
    ),
    StressScenario(
        name="Energieprijzen normalisatie",
        description="Terugkeer naar pre-2021 prijsniveaus",
        parameters=SensitivityParameters(
            energy_price_change_pct=-40,  # Based on 2020 levels
        ),
        source="ENTSOE Transparency Platform, 2024 vs 2020 spreads",
        historical_precedent="2020 baseline: gemiddelde spread €0.03/kWh"
    ),
    StressScenario(
        name="Capaciteitstarief stijging (trend 2021-2024)",
        description="Voortzetting historische stijging netkosten",
        parameters=SensitivityParameters(
            capacity_tariff_change_pct=25,  # 5% per jaar, 5 jaar
        ),
        source="ACM Tarievenbesluiten 2021-2024",
        historical_precedent="2021-2024: gemiddeld +6% per jaar"
    ),
    StressScenario(
        name="Capaciteitstarief hervorming",
        description="ACM herstructureert tariefmethodiek",
        parameters=SensitivityParameters(
            capacity_tariff_change_pct=-30,
        ),
        source="ACM Methodebesluit consultatie 2025",
        historical_precedent="Theoretisch scenario bij grootschalige hervorming"
    ),
    StressScenario(
        name="Batterijprijzen daling (Wright's Law)",
        description="Technologie-leereffecten verlagen CAPEX",
        parameters=SensitivityParameters(
            capex_change_pct=-20,  # Based on BNEF projections
        ),
        source="BloombergNEF Battery Price Survey 2024",
        historical_precedent="2010-2024: -90% batterijkosten, verwachting -20% 2025-2028"
    ),
    StressScenario(
        name="CAPEX overschrijding",
        description="Projectkosten hoger dan begroot",
        parameters=SensitivityParameters(
            capex_change_pct=25,
        ),
        source="DNV GL Project Database",
        historical_precedent="P90 kostenoverschrijding bij BESS projecten: +25%"
    ),
    StressScenario(
        name="Versnelde degradatie",
        description="Batterij degradeert sneller dan verwacht",
        parameters=SensitivityParameters(
            degradation_change_pct=50,  # 3% instead of 2%
        ),
        source="NREL BLAST degradation studies",
        historical_precedent="Worst case bij suboptimale condities: +50% degradatie"
    ),
    StressScenario(
        name="Gecombineerde stress (worst case)",
        description="Meerdere negatieve factoren tegelijk",
        parameters=SensitivityParameters(
            energy_price_change_pct=-25,
            capacity_tariff_change_pct=-20,
            capex_change_pct=15,
            degradation_change_pct=25,
        ),
        source="Monte Carlo P5 scenario analyse",
        historical_precedent="Composiet worst case op basis van historische correlaties"
    ),
]


def run_all_stress_scenarios(
    baseline_npv: float,
    baseline_payback: float,
    baseline_savings: float,
    baseline_capex: float
) -> List[Dict[str, Any]]:
    """
    Run all predefined stress scenarios and return results.

    This function should be called by the API endpoint.
    Frontend should NOT implement its own stress calculations.
    """
    analyzer = SensitivityAnalyzer()
    results = []

    for scenario in STRESS_SCENARIOS:
        result = analyzer.analyze(
            baseline_npv=baseline_npv,
            baseline_payback=baseline_payback,
            baseline_savings=baseline_savings,
            baseline_capex=baseline_capex,
            params=scenario.parameters
        )

        results.append({
            "name": scenario.name,
            "description": scenario.description,
            "source": scenario.source,
            "historical_precedent": scenario.historical_precedent,
            "result": {
                "npv_nominal": result.adjusted_npv_nominal,
                "npv_real": result.adjusted_npv_real,
                "payback_years": result.adjusted_payback_years,
                "annual_savings": result.adjusted_annual_savings,
                "is_profitable": result.is_profitable,
                "npv_change_pct": result.npv_change_pct,
            },
            "warnings": result.warnings
        })

    return results
