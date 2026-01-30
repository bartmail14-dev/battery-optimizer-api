"""
===============================================================================
BATTERY SIZING ADVISOR
===============================================================================

Genereert drie batterij-aanbevelingen op basis van verschillende doelstellingen:

1. MINIMUM: Kleinste batterij die het huidige probleem oplost
   - Focus: Peak shaving alleen
   - Doel: Break-even binnen 10 jaar

2. OPTIMAL: Beste Return on Investment
   - Focus: Maximale NPV met >80% kans op positief resultaat
   - Doel: Hoogste ROI

3. STRATEGIC: Toekomstbestendig met alle revenue streams
   - Focus: Groeiruimte + meerdere inkomstenbronnen
   - Doel: Lange termijn flexibiliteit

GEBASEERD OP MURRE CASE:
- Klant dacht: 600 kWh nodig
- Minimum berekend: 20-30 kWh
- Strategische keuze: 750 kWh (aanbieding + groeiruimte)

METHODOLOGIE:
- Minimum: Peak shaving simulatie met break-even constraint
- Optimal: Grid search over sizes, selecteer max NPV
- Strategic: Optimal + groeibuffer + multi-revenue qualification

===============================================================================
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from .revenue_streams import (
    RevenueCalculator,
    RevenueStreamType,
    MultiRevenueResult,
    QualificationStatus,
)
from .growth_projector import (
    GrowthProjector,
    GrowthScenario,
    GrowthScenarioType,
    PREDEFINED_SCENARIOS,
)
from .market_params import DEFAULT_MARKET_PARAMS, get_capacity_tariff
from .cost_structure import CostEstimator


class SizingTier(Enum):
    """Drie sizing tiers."""
    MINIMUM = "minimum"
    OPTIMAL = "optimal"
    STRATEGIC = "strategic"


@dataclass
class SizingRecommendation:
    """Eén sizing aanbeveling."""

    tier: SizingTier
    capacity_kwh: float
    max_power_kw: float

    # Financiële metrics
    capex_eur: float
    annual_savings_eur: float
    npv_eur: float
    payback_years: float
    irr_percent: Optional[float]
    probability_positive_npv: float

    # Operationele metrics
    peak_reduction_kw: float
    cycles_per_year: float
    battery_utilization_percent: float

    # Revenue breakdown
    revenue_streams: Dict[str, float]
    enabled_streams: List[str]

    # Context
    rationale: str
    growth_buffer_years: int  # Hoeveel jaren groei dit aankan
    assumptions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Converteer naar dictionary voor JSON serialisatie."""
        return {
            "tier": self.tier.value,
            "capacity_kwh": round(self.capacity_kwh, 0),
            "max_power_kw": round(self.max_power_kw, 1),
            "financials": {
                "capex_eur": round(self.capex_eur, 0),
                "annual_savings_eur": round(self.annual_savings_eur, 0),
                "npv_eur": round(self.npv_eur, 0),
                "payback_years": round(self.payback_years, 1),
                "irr_percent": round(self.irr_percent, 1) if self.irr_percent else None,
                "probability_positive_npv": round(self.probability_positive_npv * 100, 0),
            },
            "operations": {
                "peak_reduction_kw": round(self.peak_reduction_kw, 1),
                "cycles_per_year": round(self.cycles_per_year, 0),
                "battery_utilization_percent": round(self.battery_utilization_percent, 0),
            },
            "revenue_streams": {k: round(v, 0) for k, v in self.revenue_streams.items()},
            "enabled_streams": self.enabled_streams,
            "rationale": self.rationale,
            "growth_buffer_years": self.growth_buffer_years,
            "assumptions": self.assumptions,
            "warnings": self.warnings,
        }


@dataclass
class SizingRecommendations:
    """Complete set van drie aanbevelingen."""

    minimum: SizingRecommendation
    optimal: SizingRecommendation
    strategic: SizingRecommendation

    # Context
    profile_summary: Dict[str, float]
    analysis_date: str
    methodology_notes: str

    def to_dict(self) -> dict:
        """Converteer naar dictionary voor JSON serialisatie."""
        return {
            "minimum": self.minimum.to_dict(),
            "optimal": self.optimal.to_dict(),
            "strategic": self.strategic.to_dict(),
            "profile_summary": self.profile_summary,
            "analysis_date": self.analysis_date,
            "methodology_notes": self.methodology_notes,
        }


@dataclass
class BatteryConstraints:
    """Constraints voor sizing optimalisatie."""
    min_capacity_kwh: float = 10
    max_capacity_kwh: float = 500
    max_budget_eur: Optional[float] = None
    max_payback_years: Optional[float] = 15
    min_npv_eur: Optional[float] = None
    required_peak_reduction_kw: Optional[float] = None


class SizingAdvisor:
    """
    Genereert drie-tier batterij sizing aanbevelingen.

    Usage:
        advisor = SizingAdvisor()
        recommendations = advisor.generate_recommendations(
            profile_df=profile,
            constraints=BatteryConstraints(max_budget_eur=100000)
        )

    COST CALCULATION:
        Uses CostEstimator from cost_structure.py with itemized costs
        from BloombergNEF Battery Price Survey 2024, DNV GL reports,
        and industry quotes. No hardcoded "magic number" CAPEX values.
    """

    # Battery sizes to evaluate (kWh)
    EVALUATION_SIZES = [10, 15, 20, 30, 50, 75, 100, 150, 200, 300, 400, 500]

    # Default battery parameters
    # Source: DNV GL "Battery Energy Storage Systems" 2023
    DEFAULT_C_RATE = 0.5  # Max power = capacity × C-rate (typical for LFP)
    DEFAULT_EFFICIENCY = 0.92  # Source: NREL "Grid-Scale Battery Storage" 2023
    ANALYSIS_YEARS = 15
    # Source: WACC for renewable energy projects in NL (DNB Financial Stability Report 2024)
    DISCOUNT_RATE = 0.05

    def __init__(self, battery_chemistry: str = "LFP"):
        self.revenue_calculator = RevenueCalculator()
        self.growth_projector = GrowthProjector()
        # Use CostEstimator for transparent, sourced cost calculations
        self.cost_estimator = CostEstimator(
            project_years=self.ANALYSIS_YEARS,
            include_contingency=True,
            battery_chemistry=battery_chemistry
        )

    def generate_recommendations(
        self,
        profile_df: pd.DataFrame,
        constraints: Optional[BatteryConstraints] = None,
        postcode: Optional[str] = None,
        has_solar: bool = False,
        solar_peak_kw: float = 0.0
    ) -> SizingRecommendations:
        """
        Genereer drie sizing aanbevelingen.

        Args:
            profile_df: DataFrame met energieprofiel
            constraints: Optionele beperkingen
            postcode: Voor netbeheerder tarief lookup
            has_solar: Heeft locatie zonne-energie?
            solar_peak_kw: Piekvermogen zonne-installatie

        Returns:
            SizingRecommendations met minimum, optimal, strategic
        """
        import datetime

        if constraints is None:
            constraints = BatteryConstraints()

        # Analyseer profiel
        profile_stats = self._analyze_profile(profile_df)

        # Evalueer alle battery sizes
        evaluations = self._evaluate_all_sizes(
            profile_df=profile_df,
            profile_stats=profile_stats,
            constraints=constraints,
            postcode=postcode,
            has_solar=has_solar,
            solar_peak_kw=solar_peak_kw
        )

        # Bepaal minimum recommendation
        minimum = self._find_minimum_size(evaluations, constraints)

        # Bepaal optimal recommendation
        optimal = self._find_optimal_size(evaluations, constraints)

        # Bepaal strategic recommendation
        strategic = self._find_strategic_size(
            evaluations=evaluations,
            constraints=constraints,
            profile_stats=profile_stats,
            has_solar=has_solar
        )

        return SizingRecommendations(
            minimum=minimum,
            optimal=optimal,
            strategic=strategic,
            profile_summary={
                "peak_kw": profile_stats["peak_kw"],
                "avg_kw": profile_stats["avg_kw"],
                "annual_consumption_kwh": profile_stats["annual_kwh"],
                "has_solar": has_solar,
            },
            analysis_date=datetime.datetime.now().isoformat(),
            methodology_notes=(
                "Minimum: Kleinste batterij met break-even < 10 jaar (peak shaving). "
                "Optimal: Hoogste NPV met P(NPV>0) > 80%. "
                "Strategic: Optimal + groeibuffer + multi-revenue qualification."
            )
        )

    def _analyze_profile(self, df: pd.DataFrame) -> dict:
        """Analyseer energieprofiel."""
        if df.empty:
            return {
                "peak_kw": 0,
                "avg_kw": 0,
                "baseload_kw": 0,
                "annual_kwh": 0,
                "days": 0,
            }

        interval_hours = 0.25
        # Support both column naming conventions
        afname_col = 'afname_kwh' if 'afname_kwh' in df.columns else 'afname'
        afname = df[afname_col].fillna(0)

        # Explicitly convert to float to avoid pandas Series issues
        peak_kw = float(afname.max()) / interval_hours
        avg_kw = float(afname.mean()) / interval_hours
        baseload_kw = float(afname.quantile(0.10)) / interval_hours

        days = len(df) / 96
        annual_kwh = (float(afname.sum()) / days) * 365 if days > 0 else 0

        return {
            "peak_kw": peak_kw,
            "avg_kw": avg_kw,
            "baseload_kw": baseload_kw,
            "annual_kwh": annual_kwh,
            "days": days,
        }

    def _evaluate_all_sizes(
        self,
        profile_df: pd.DataFrame,
        profile_stats: dict,
        constraints: BatteryConstraints,
        postcode: Optional[str],
        has_solar: bool,
        solar_peak_kw: float
    ) -> List[dict]:
        """Evalueer alle battery sizes."""
        evaluations = []

        for size_kwh in self.EVALUATION_SIZES:
            if size_kwh < constraints.min_capacity_kwh:
                continue
            if size_kwh > constraints.max_capacity_kwh:
                continue

            power_kw = size_kwh * self.DEFAULT_C_RATE

            # Use CostEstimator for transparent, sourced CAPEX calculation
            # Source: BloombergNEF 2024, DNV GL, Fraunhofer ISE (see cost_structure.py)
            cost_estimate = self.cost_estimator.estimate_complete(
                capacity_kwh=size_kwh,
                power_kw=power_kw,
                needs_grid_upgrade=power_kw > 200,  # Grid upgrade typically needed >200kW
                needs_transformer=power_kw > 400    # Transformer typically needed >400kW
            )
            capex = cost_estimate.total_capex

            # Budget check
            if constraints.max_budget_eur and capex > constraints.max_budget_eur:
                continue

            # Bereken revenue streams
            revenue_result = self.revenue_calculator.calculate_all(
                profile_df=profile_df,
                battery_kwh=size_kwh,
                battery_kw=power_kw,
                has_solar=has_solar,
                solar_peak_kw=solar_peak_kw,
                postcode=postcode
            )

            # Bereken peak reduction
            peak_reduction = self._estimate_peak_reduction(
                profile_stats=profile_stats,
                battery_kw=power_kw
            )

            # Financiële berekeningen
            annual_savings = revenue_result.realistic_combined_revenue
            payback = capex / annual_savings if annual_savings > 0 else 999
            npv = self._calculate_npv(capex, annual_savings)
            irr = self._calculate_irr(capex, annual_savings)

            # Probability positive NPV (simplified)
            prob_positive = self._estimate_probability_positive_npv(npv, annual_savings)

            # Cycles per year (geschat)
            cycles_per_year = self._estimate_cycles(
                revenue_result=revenue_result,
                battery_kwh=size_kwh
            )

            evaluations.append({
                "size_kwh": size_kwh,
                "power_kw": power_kw,
                "capex": capex,
                "annual_savings": annual_savings,
                "npv": npv,
                "irr": irr,
                "payback": payback,
                "prob_positive_npv": prob_positive,
                "peak_reduction": peak_reduction,
                "cycles_per_year": cycles_per_year,
                "revenue_result": revenue_result,
                "utilization": min(100, (cycles_per_year * 2 / 365) * 100),
            })

        return evaluations

    def _estimate_peak_reduction(self, profile_stats: dict, battery_kw: float) -> float:
        """Schat haalbare piekvermindering."""
        peak_kw = profile_stats["peak_kw"]
        avg_kw = profile_stats["avg_kw"]

        # Maximale reductie is verschil piek - gemiddelde
        max_possible = peak_kw - avg_kw

        # Batterij kan ~70% van nominaal vermogen leveren voor peak shaving
        battery_contribution = battery_kw * 0.70

        return min(max_possible, battery_contribution)

    def _calculate_npv(self, capex: float, annual_savings: float) -> float:
        """Bereken NPV over analyse periode."""
        npv = -capex
        for year in range(1, self.ANALYSIS_YEARS + 1):
            # Account for degradation (2%/jaar)
            degradation_factor = 0.98 ** year
            year_savings = annual_savings * degradation_factor
            npv += year_savings / ((1 + self.DISCOUNT_RATE) ** year)
        return npv

    def _calculate_irr(self, capex: float, annual_savings: float) -> Optional[float]:
        """Bereken IRR met Newton-Raphson."""
        if annual_savings <= 0:
            return None

        # Simpele benadering
        cashflows = [-capex] + [annual_savings * (0.98 ** y) for y in range(1, self.ANALYSIS_YEARS + 1)]

        # Newton-Raphson
        irr = 0.10  # Start guess
        for _ in range(50):
            npv = sum(cf / ((1 + irr) ** i) for i, cf in enumerate(cashflows))
            npv_deriv = sum(-i * cf / ((1 + irr) ** (i + 1)) for i, cf in enumerate(cashflows))

            if abs(npv_deriv) < 1e-10:
                break

            irr_new = irr - npv / npv_deriv
            if abs(irr_new - irr) < 1e-6:
                break
            irr = irr_new

        return irr * 100 if -0.5 < irr < 1.0 else None

    def _estimate_probability_positive_npv(self, npv: float, annual_savings: float) -> float:
        """Schat kans op positieve NPV (simplified)."""
        if npv <= 0:
            return 0.2  # Laag maar niet nul (onzekerheid)
        if npv > annual_savings * 3:
            return 0.90  # Hoge zekerheid bij robuuste NPV
        return 0.5 + (npv / (annual_savings * 6))  # Lineaire schaling

    def _estimate_cycles(self, revenue_result: MultiRevenueResult, battery_kwh: float) -> float:
        """Schat aantal cycli per jaar."""
        # Geschat op basis van throughput
        total_hours = sum(r.utilization_hours for r in revenue_result.streams.values())
        # Typisch 0.5 cycle per actief uur
        return min(500, total_hours * 0.5 / (battery_kwh / 100))

    def _find_minimum_size(
        self,
        evaluations: List[dict],
        constraints: BatteryConstraints
    ) -> SizingRecommendation:
        """
        Vind minimum batterijgrootte.

        Criteria:
        - Kleinste batterij
        - Payback < 10 jaar
        - Focus op peak shaving alleen
        """
        # Filter op payback
        viable = [e for e in evaluations if e["payback"] <= 10]

        if not viable:
            # Geen enkele batterij heeft payback < 10 jaar
            # Neem kleinste als "minimum"
            viable = evaluations

        # Sorteer op grootte (kleinste eerst)
        viable.sort(key=lambda x: x["size_kwh"])
        selected = viable[0]

        rev_result = selected["revenue_result"]
        peak_shaving_rev = rev_result.streams.get(
            RevenueStreamType.PEAK_SHAVING
        )
        ps_revenue = peak_shaving_rev.annual_revenue_eur if peak_shaving_rev else 0

        return SizingRecommendation(
            tier=SizingTier.MINIMUM,
            capacity_kwh=selected["size_kwh"],
            max_power_kw=selected["power_kw"],
            capex_eur=selected["capex"],
            annual_savings_eur=ps_revenue,  # Alleen peak shaving
            npv_eur=self._calculate_npv(selected["capex"], ps_revenue),
            payback_years=selected["capex"] / ps_revenue if ps_revenue > 0 else 999,
            irr_percent=self._calculate_irr(selected["capex"], ps_revenue),
            probability_positive_npv=0.70,  # Conservative voor minimum
            peak_reduction_kw=selected["peak_reduction"],
            cycles_per_year=selected["cycles_per_year"] * 0.5,  # Minder gebruik
            battery_utilization_percent=selected["utilization"] * 0.5,
            revenue_streams={"peak_shaving": ps_revenue},
            enabled_streams=["peak_shaving"],
            rationale=(
                f"Kleinste batterij voor huidige piekvermindering. "
                f"Focus op capaciteitstarief besparing."
            ),
            growth_buffer_years=0,
            assumptions=[
                "Alleen peak shaving revenue",
                "Huidige verbruikspatroon blijft gelijk",
            ],
            warnings=[
                "Geen ruimte voor groei",
                "Beperkte flexibiliteit"
            ] if selected["size_kwh"] < 50 else []
        )

    def _find_optimal_size(
        self,
        evaluations: List[dict],
        constraints: BatteryConstraints
    ) -> SizingRecommendation:
        """
        Vind optimale batterijgrootte.

        Criteria:
        - Hoogste NPV
        - Probability positive NPV > 80%
        """
        # Filter op payback constraint indien gegeven
        viable = evaluations
        if constraints.max_payback_years:
            viable = [e for e in viable if e["payback"] <= constraints.max_payback_years]

        if not viable:
            viable = evaluations

        # Filter op probability
        high_prob = [e for e in viable if e["prob_positive_npv"] >= 0.80]
        if high_prob:
            viable = high_prob

        # Sorteer op NPV (hoogste eerst)
        viable.sort(key=lambda x: x["npv"], reverse=True)
        selected = viable[0]

        rev_result = selected["revenue_result"]

        return SizingRecommendation(
            tier=SizingTier.OPTIMAL,
            capacity_kwh=selected["size_kwh"],
            max_power_kw=selected["power_kw"],
            capex_eur=selected["capex"],
            annual_savings_eur=selected["annual_savings"],
            npv_eur=selected["npv"],
            payback_years=selected["payback"],
            irr_percent=selected["irr"],
            probability_positive_npv=selected["prob_positive_npv"],
            peak_reduction_kw=selected["peak_reduction"],
            cycles_per_year=selected["cycles_per_year"],
            battery_utilization_percent=selected["utilization"],
            revenue_streams={
                s.value: r.annual_revenue_eur
                for s, r in rev_result.streams.items()
                if r.annual_revenue_eur > 0
            },
            enabled_streams=[
                s.value for s in rev_result.recommended_streams
            ],
            rationale=(
                f"Beste Return on Investment. "
                f"NPV €{selected['npv']:,.0f} met {selected['prob_positive_npv']*100:.0f}% zekerheid."
            ),
            growth_buffer_years=2,  # Kleine buffer
            assumptions=[
                "Huidige marktprijzen blijven vergelijkbaar",
                "Batterijprestaties volgens specificaties",
            ],
            warnings=[]
        )

    def _find_strategic_size(
        self,
        evaluations: List[dict],
        constraints: BatteryConstraints,
        profile_stats: dict,
        has_solar: bool
    ) -> SizingRecommendation:
        """
        Vind strategische batterijgrootte.

        Criteria:
        - Groot genoeg voor FCR/aFRR deelname (≥100 kW)
        - Ruimte voor groei (+50% verbruik)
        - Alle revenue streams mogelijk
        """
        # Filter op minimaal 100 kW voor grid services
        grid_ready = [e for e in evaluations if e["power_kw"] >= 100]

        if not grid_ready:
            # Geen grid-ready size beschikbaar, neem grootste
            grid_ready = sorted(evaluations, key=lambda x: x["size_kwh"], reverse=True)

        # Bereken benodigde grootte voor +50% groei
        future_peak = profile_stats["peak_kw"] * 1.5
        future_avg = profile_stats["avg_kw"] * 1.5
        required_power = (future_peak - future_avg) * 0.7  # 70% effectiviteit

        # Filter op voldoende capaciteit voor toekomstige piek
        growth_ready = [
            e for e in grid_ready
            if e["power_kw"] >= required_power * 0.8
        ]

        if not growth_ready:
            growth_ready = grid_ready

        # Sorteer op NPV (binnen de growth-ready set)
        growth_ready.sort(key=lambda x: x["npv"], reverse=True)
        selected = growth_ready[0]

        rev_result = selected["revenue_result"]

        # Bepaal hoeveel groei dit aankan
        current_need = profile_stats["peak_kw"] - profile_stats["avg_kw"]
        battery_capacity = selected["power_kw"] * 0.7
        growth_headroom = (battery_capacity / current_need) - 1 if current_need > 0 else 0
        growth_buffer_years = int(growth_headroom / 0.05)  # ~5% groei per jaar

        return SizingRecommendation(
            tier=SizingTier.STRATEGIC,
            capacity_kwh=selected["size_kwh"],
            max_power_kw=selected["power_kw"],
            capex_eur=selected["capex"],
            annual_savings_eur=selected["annual_savings"],
            npv_eur=selected["npv"],
            payback_years=selected["payback"],
            irr_percent=selected["irr"],
            probability_positive_npv=selected["prob_positive_npv"],
            peak_reduction_kw=selected["peak_reduction"],
            cycles_per_year=selected["cycles_per_year"],
            battery_utilization_percent=selected["utilization"],
            revenue_streams={
                s.value: r.annual_revenue_eur
                for s, r in rev_result.streams.items()
                if r.annual_revenue_eur > 0
            },
            enabled_streams=[s.value for s in RevenueStreamType],  # Alle streams
            rationale=(
                f"Toekomstbestendig met alle revenue streams. "
                f"Geschikt voor FCR/aFRR, {growth_buffer_years} jaar groeibuffer."
            ),
            growth_buffer_years=min(10, max(0, growth_buffer_years)),
            assumptions=[
                "Groei van 3-5% per jaar verwacht",
                "FCR/aFRR markten blijven toegankelijk",
                "Aggregator beschikbaar indien nodig",
            ],
            warnings=[
                "Hogere initiële investering",
                "Deels afhankelijk van toekomstige marktomstandigheden"
            ]
        )
