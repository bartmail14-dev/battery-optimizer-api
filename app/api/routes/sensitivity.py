"""
===============================================================================
SENSITIVITY ANALYSIS API ENDPOINTS
===============================================================================

These endpoints are the ONLY authorized source for sensitivity calculations.
Frontend must call these endpoints instead of calculating locally.

This ensures:
1. Single source of truth for all financial calculations
2. Consistent methodology across all clients
3. Audit trail of all calculations
4. Proper use of sourced assumptions
===============================================================================
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

from app.engine.sensitivity_analysis import (
    SensitivityAnalyzer,
    SensitivityParameters,
    run_all_stress_scenarios,
    STRESS_SCENARIOS,
    REVENUE_SPLIT,
    DEFAULT_DISCOUNT_RATE,
    DEFAULT_INFLATION_RATE,
    DEFAULT_PROJECT_YEARS,
)

router = APIRouter(prefix="/sensitivity", tags=["sensitivity"])


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class SensitivityRequest(BaseModel):
    """Request for sensitivity analysis."""
    # Baseline values from original analysis
    baseline_npv: float = Field(..., description="Baseline NPV from Monte Carlo analysis")
    baseline_payback_years: float = Field(..., description="Baseline simple payback in years")
    baseline_annual_savings: float = Field(..., description="Baseline annual savings in EUR")
    baseline_capex: float = Field(..., description="Total CAPEX in EUR")

    # Parameter adjustments
    energy_price_change_pct: float = Field(0, ge=-50, le=100, description="Energy price change %")
    capacity_tariff_change_pct: float = Field(0, ge=-50, le=100, description="Capacity tariff change %")
    capex_change_pct: float = Field(0, ge=-30, le=50, description="CAPEX change %")
    efficiency_change_pct: float = Field(0, ge=-20, le=10, description="Efficiency change %")
    degradation_change_pct: float = Field(0, ge=-50, le=100, description="Degradation rate change %")
    discount_rate_change_pp: float = Field(0, ge=-2, le=3, description="Discount rate change in pp")
    inflation_rate_pct: float = Field(2.5, ge=0, le=10, description="Assumed inflation rate %")


class SensitivityResponse(BaseModel):
    """Response from sensitivity analysis."""
    # Adjusted metrics
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

    # Validity
    is_profitable: bool
    warnings: List[str]

    # Methodology transparency
    methodology: Dict[str, Any]


class StressTestRequest(BaseModel):
    """Request for running stress test scenarios."""
    baseline_npv: float
    baseline_payback_years: float
    baseline_annual_savings: float
    baseline_capex: float


class StressScenarioResult(BaseModel):
    """Result for a single stress scenario."""
    name: str
    description: str
    source: str
    historical_precedent: str
    result: Dict[str, Any]
    warnings: List[str]


class StressTestResponse(BaseModel):
    """Response from stress test analysis."""
    scenarios: List[StressScenarioResult]
    robustness_score: float
    viable_scenarios_count: int
    total_scenarios_count: int
    methodology: Dict[str, Any]


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/analyze", response_model=SensitivityResponse)
async def analyze_sensitivity(request: SensitivityRequest) -> SensitivityResponse:
    """
    Perform sensitivity analysis on battery investment scenario.

    This endpoint is the SINGLE SOURCE OF TRUTH for sensitivity calculations.
    Frontend must call this instead of calculating locally.

    Parameters can be adjusted to see impact on financial metrics:
    - energy_price_change_pct: Impact on arbitrage and self-consumption revenue
    - capacity_tariff_change_pct: Impact on peak shaving revenue
    - capex_change_pct: Impact on investment cost
    - efficiency_change_pct: Impact on all savings
    - degradation_change_pct: Impact on long-term savings
    - discount_rate_change_pp: Impact on NPV calculation
    """
    analyzer = SensitivityAnalyzer(
        discount_rate=DEFAULT_DISCOUNT_RATE,
        inflation_rate=request.inflation_rate_pct / 100,
        project_years=DEFAULT_PROJECT_YEARS
    )

    params = SensitivityParameters(
        energy_price_change_pct=request.energy_price_change_pct,
        capacity_tariff_change_pct=request.capacity_tariff_change_pct,
        capex_change_pct=request.capex_change_pct,
        efficiency_change_pct=request.efficiency_change_pct,
        degradation_change_pct=request.degradation_change_pct,
        discount_rate_change_pp=request.discount_rate_change_pp,
        inflation_rate_pct=request.inflation_rate_pct
    )

    result = analyzer.analyze(
        baseline_npv=request.baseline_npv,
        baseline_payback=request.baseline_payback_years,
        baseline_savings=request.baseline_annual_savings,
        baseline_capex=request.baseline_capex,
        params=params
    )

    return SensitivityResponse(
        adjusted_npv_nominal=result.adjusted_npv_nominal,
        adjusted_npv_real=result.adjusted_npv_real,
        adjusted_payback_years=result.adjusted_payback_years,
        adjusted_annual_savings=result.adjusted_annual_savings,
        adjusted_capex=result.adjusted_capex,
        npv_change_pct=result.npv_change_pct,
        payback_change_pct=result.payback_change_pct,
        savings_change_pct=result.savings_change_pct,
        effective_discount_rate=result.effective_discount_rate,
        effective_inflation_rate=result.effective_inflation_rate,
        effective_degradation_rate=result.effective_degradation_rate,
        is_profitable=result.is_profitable,
        warnings=result.warnings,
        methodology={
            "revenue_split": REVENUE_SPLIT,
            "sources": [
                "CPB Werkgroep Discontovoet (2020)",
                "CE Delft Flexibiliteit Batterijopslag (2024)",
                "NREL Battery Lifetime Analysis (2023)"
            ],
            "project_years": DEFAULT_PROJECT_YEARS,
            "base_discount_rate": DEFAULT_DISCOUNT_RATE,
            "npv_formula": "NPV = -CAPEX + Σ(Savings_t * (1-degradation)^t / (1+r)^t)",
            "note": "Real NPV accounts for inflation using Fisher equation"
        }
    )


@router.post("/stress-test", response_model=StressTestResponse)
async def run_stress_test(request: StressTestRequest) -> StressTestResponse:
    """
    Run all predefined stress scenarios based on historical data.

    Each scenario is based on actual historical market events or
    regulatory changes with full source attribution.

    This endpoint is the SINGLE SOURCE OF TRUTH for stress testing.
    Frontend must call this instead of implementing its own scenarios.
    """
    results = run_all_stress_scenarios(
        baseline_npv=request.baseline_npv,
        baseline_payback=request.baseline_payback_years,
        baseline_savings=request.baseline_annual_savings,
        baseline_capex=request.baseline_capex
    )

    # Calculate robustness score
    viable_count = sum(1 for r in results if r["result"]["is_profitable"])
    total_count = len(results)
    robustness_score = (viable_count / total_count) * 100 if total_count > 0 else 0

    return StressTestResponse(
        scenarios=[StressScenarioResult(**r) for r in results],
        robustness_score=round(robustness_score, 1),
        viable_scenarios_count=viable_count,
        total_scenarios_count=total_count,
        methodology={
            "scenario_sources": [
                "ENTSOE Transparency Platform (day-ahead prices)",
                "TenneT Imbalance Data",
                "ACM Tarievenbesluiten 2021-2024",
                "BloombergNEF Battery Price Survey",
                "DNV GL BESS Project Database",
                "NREL BLAST Degradation Studies"
            ],
            "stress_scenarios": [
                {"name": s.name, "source": s.source}
                for s in STRESS_SCENARIOS
            ],
            "note": "All scenarios based on historical precedents, not arbitrary percentages"
        }
    )


@router.get("/methodology")
async def get_methodology() -> Dict[str, Any]:
    """
    Get full methodology documentation for sensitivity analysis.

    This provides transparency about all assumptions and sources.
    """
    return {
        "revenue_split": {
            "values": REVENUE_SPLIT,
            "sources": [
                {
                    "name": "CE Delft",
                    "year": 2024,
                    "title": "Flexibiliteit met batterijopslag",
                    "chapter": "Hoofdstuk 3: Revenue stacking"
                },
                {
                    "name": "Berenschot",
                    "year": 2023,
                    "title": "Business case analyse batterijopslag",
                    "chapter": "Bijlage B: Gevoeligheidsanalyse"
                }
            ],
            "note": "Based on analysis of 50+ Dutch commercial battery installations"
        },
        "financial_parameters": {
            "discount_rate": {
                "default": DEFAULT_DISCOUNT_RATE,
                "range": [0.03, 0.07],
                "source": "CPB Werkgroep Discontovoet (2020)"
            },
            "inflation_rate": {
                "default": DEFAULT_INFLATION_RATE,
                "source": "ECB inflation target (2% medium term)"
            },
            "project_years": {
                "default": DEFAULT_PROJECT_YEARS,
                "note": "Industry standard for commercial BESS"
            }
        },
        "degradation": {
            "default_rate": 0.02,
            "chemistry": "LFP",
            "conditions": "25°C, 80% DoD, 1 cycle/day",
            "source": "NREL BLAST (2023)"
        },
        "formulas": {
            "pvaf": "(1 - (1 + r)^-n) / r",
            "npv_nominal": "NPV = -CAPEX + Σ(Savings_t * (1-d)^t / (1+r)^t)",
            "real_discount_rate": "r_real = (1 + r_nominal) / (1 + inflation) - 1",
            "simple_payback": "CAPEX / Annual_Savings"
        },
        "stress_scenarios": [
            {
                "name": s.name,
                "source": s.source,
                "precedent": s.historical_precedent
            }
            for s in STRESS_SCENARIOS
        ]
    }
