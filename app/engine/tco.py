"""
===============================================================================
TOTAL COST OF OWNERSHIP (TCO) CALCULATOR
===============================================================================

Industrie-standaard TCO berekening voor batterijopslag.

Dit module implementeert:
1. CAPEX breakdown (cells, inverter, BOS, installation, engineering)
2. OPEX berekening (maintenance, insurance, monitoring)
3. Replacement costs (batterijvervanging bij EOL)
4. Residual value (restwaarde bij einde analyseperiode)
5. LCOS (Levelized Cost of Storage) volgens Lazard methodologie
6. IRR/NPV berekeningen met Newton-Raphson

REFERENTIES:
- Lazard LCOS v9.0: Industry-standard methodology
- NREL ATB 2024: Cost assumptions for utility-scale storage
- EPRI: Load duration curve methodology

WAARSCHUWING:
- Deze berekeningen worden gebruikt voor investeringsbeslissingen
- Valideer altijd tegen meerdere bronnen en expertadvies
===============================================================================
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import math

import structlog

from .degradation import DegradationModel, BatteryChemistry

logger = structlog.get_logger()


# =============================================================================
# COST CONSTANTS (2024 EUR, Nederland)
# =============================================================================

# CAPEX breakdown percentages (bron: NREL ATB 2024, aangepast voor NL)
CAPEX_BREAKDOWN = {
    "cells_and_modules": 0.45,      # Batterijcellen en modules
    "inverter_pcs": 0.15,           # Power Conversion System
    "bos_electrical": 0.12,         # Balance of System (elektrisch)
    "bos_structural": 0.05,         # Balance of System (constructief)
    "installation_labor": 0.10,     # Installatie arbeid
    "engineering": 0.05,            # Engineering en projectmanagement
    "permitting": 0.03,             # Vergunningen en aansluitkosten
    "contingency": 0.05,            # Onvoorzien
}

# Base prices per kWh (2024, NL markt)
# Deze worden geschaald op basis van systeem grootte
BASE_PRICES_PER_KWH = {
    BatteryChemistry.LFP: 350,      # €/kWh installed
    BatteryChemistry.NMC: 400,
    BatteryChemistry.NCA: 420,
    BatteryChemistry.LTO: 650,      # Premium voor lange levensduur
}

# Schaalfactoren voor capaciteit (economies of scale)
# Kleinere systemen zijn relatief duurder per kWh
SCALE_FACTORS = [
    (5, 1.5),      # < 5 kWh: 50% premium
    (20, 1.3),     # 5-20 kWh: 30% premium
    (50, 1.15),    # 20-50 kWh: 15% premium
    (100, 1.05),   # 50-100 kWh: 5% premium
    (500, 1.0),    # 100-500 kWh: basisprijs
    (float('inf'), 0.95),  # > 500 kWh: 5% korting
]

# OPEX percentages (% van CAPEX per jaar)
OPEX_RATES = {
    "maintenance": 0.015,           # 1.5% preventief onderhoud
    "insurance": 0.005,             # 0.5% verzekering
    "monitoring": 0.003,            # 0.3% monitoring/software
    "grid_fees": 0.002,             # 0.2% netvakblasting
}


@dataclass
class CAPEXBreakdown:
    """
    Gedetailleerde CAPEX breakdown.
    """
    cells_and_modules: float
    inverter_pcs: float
    bos_electrical: float
    bos_structural: float
    installation_labor: float
    engineering: float
    permitting: float
    contingency: float
    total: float

    def to_dict(self) -> dict:
        return {
            "cells_and_modules": round(self.cells_and_modules, 2),
            "inverter_pcs": round(self.inverter_pcs, 2),
            "bos_electrical": round(self.bos_electrical, 2),
            "bos_structural": round(self.bos_structural, 2),
            "installation_labor": round(self.installation_labor, 2),
            "engineering": round(self.engineering, 2),
            "permitting": round(self.permitting, 2),
            "contingency": round(self.contingency, 2),
            "total": round(self.total, 2),
        }


@dataclass
class OPEXBreakdown:
    """
    Jaarlijkse OPEX breakdown.
    """
    maintenance: float
    insurance: float
    monitoring: float
    grid_fees: float
    total: float

    def to_dict(self) -> dict:
        return {
            "maintenance": round(self.maintenance, 2),
            "insurance": round(self.insurance, 2),
            "monitoring": round(self.monitoring, 2),
            "grid_fees": round(self.grid_fees, 2),
            "total": round(self.total, 2),
        }


@dataclass
class TCOResult:
    """
    Volledig TCO resultaat.

    FORMULE LCOS (Lazard):
    LCOS = (PV_costs - PV_residual) / PV_energy_throughput

    waar:
    - PV_costs = CAPEX + sum(OPEX_y / (1+r)^y) + sum(replacement_y / (1+r)^y)
    - PV_residual = residual_value / (1+r)^n
    - PV_energy_throughput = sum(throughput_y / (1+r)^y)
    """
    # CAPEX
    capex_total: float
    capex_breakdown: CAPEXBreakdown
    capex_per_kwh: float

    # OPEX (jaarlijks)
    opex_annual: float
    opex_breakdown: OPEXBreakdown
    opex_total_npv: float  # NPV van alle OPEX over analyseperiode

    # Replacements
    replacement_year: Optional[int]
    replacement_cost: float
    replacement_npv: float

    # Residual
    residual_value: float
    residual_npv: float

    # Totalen
    total_cost_npv: float      # CAPEX + OPEX NPV + Replacements - Residual
    cost_per_kwh_stored: float  # Per kWh throughput

    # LCOS (Lazard methodology)
    lcos: float  # €/kWh

    # Energy metrics
    total_throughput_kwh: float  # Totale energie throughput over analyseperiode

    def to_dict(self) -> dict:
        return {
            "capex": {
                "total": round(self.capex_total, 2),
                "per_kwh": round(self.capex_per_kwh, 2),
                "breakdown": self.capex_breakdown.to_dict(),
            },
            "opex": {
                "annual": round(self.opex_annual, 2),
                "total_npv": round(self.opex_total_npv, 2),
                "breakdown": self.opex_breakdown.to_dict(),
            },
            "replacement": {
                "year": self.replacement_year,
                "cost": round(self.replacement_cost, 2),
                "npv": round(self.replacement_npv, 2),
            },
            "residual": {
                "value": round(self.residual_value, 2),
                "npv": round(self.residual_npv, 2),
            },
            "totals": {
                "total_cost_npv": round(self.total_cost_npv, 2),
                "cost_per_kwh_stored": round(self.cost_per_kwh_stored, 4),
                "lcos": round(self.lcos, 4),
                "total_throughput_kwh": round(self.total_throughput_kwh, 2),
            }
        }


@dataclass
class FinancialMetrics:
    """
    Financiële metrics voor investeringsbeslissing.
    """
    # Basic
    simple_payback_years: float
    npv: float
    irr: Optional[float]

    # Advanced
    profitability_index: float  # PV benefits / PV costs
    modified_irr: Optional[float]
    discounted_payback_years: Optional[float]

    # Risk indicators
    breakeven_utilization: float  # Minimale benutting voor break-even

    def to_dict(self) -> dict:
        return {
            "simple_payback_years": round(self.simple_payback_years, 2),
            "npv": round(self.npv, 2),
            "irr": round(self.irr, 4) if self.irr else None,
            "profitability_index": round(self.profitability_index, 3),
            "modified_irr": round(self.modified_irr, 4) if self.modified_irr else None,
            "discounted_payback_years": (
                round(self.discounted_payback_years, 2)
                if self.discounted_payback_years else None
            ),
            "breakeven_utilization": round(self.breakeven_utilization, 3),
        }


class TCOCalculator:
    """
    Total Cost of Ownership calculator met LCOS berekening.

    GEBRUIK:
    ```python
    calc = TCOCalculator(
        capacity_kwh=100,
        chemistry=BatteryChemistry.LFP,
        analysis_years=15,
        discount_rate=0.05
    )

    tco = calc.calculate_tco(
        annual_cycles=300,
        average_dod=0.8,
        average_throughput_kwh=48000  # Per jaar
    )

    print(f"LCOS: €{tco.lcos:.3f}/kWh")
    ```
    """

    def __init__(
        self,
        capacity_kwh: float,
        chemistry: BatteryChemistry = BatteryChemistry.LFP,
        analysis_years: int = 15,
        discount_rate: float = 0.05,
        inflation_rate: float = 0.02
    ):
        """
        Initialiseer TCO calculator.

        Args:
            capacity_kwh: Batterijcapaciteit (kWh)
            chemistry: Batterijchemie
            analysis_years: Analyseperiode (jaren)
            discount_rate: Discontovoet (WACC)
            inflation_rate: Inflatie voor OPEX escalatie
        """
        self.capacity_kwh = capacity_kwh
        self.chemistry = chemistry
        self.analysis_years = analysis_years
        self.discount_rate = discount_rate
        self.inflation_rate = inflation_rate

        # Degradation model voor levensduurberekening
        self.degradation_model = DegradationModel(chemistry)

        logger.info(
            "TCO Calculator initialized",
            capacity_kwh=capacity_kwh,
            chemistry=chemistry.value,
            analysis_years=analysis_years
        )

    def calculate_capex(self, custom_price_per_kwh: Optional[float] = None) -> CAPEXBreakdown:
        """
        Bereken CAPEX breakdown.

        Args:
            custom_price_per_kwh: Override basis prijs (optioneel)

        Returns:
            CAPEXBreakdown met alle componenten
        """
        # Bepaal basisprijs
        if custom_price_per_kwh:
            base_price = custom_price_per_kwh
        else:
            base_price = BASE_PRICES_PER_KWH[self.chemistry]

        # Pas schaalfactor toe
        scale_factor = self._get_scale_factor(self.capacity_kwh)
        effective_price = base_price * scale_factor

        # Totale CAPEX
        total_capex = self.capacity_kwh * effective_price

        # Breakdown
        breakdown = CAPEXBreakdown(
            cells_and_modules=total_capex * CAPEX_BREAKDOWN["cells_and_modules"],
            inverter_pcs=total_capex * CAPEX_BREAKDOWN["inverter_pcs"],
            bos_electrical=total_capex * CAPEX_BREAKDOWN["bos_electrical"],
            bos_structural=total_capex * CAPEX_BREAKDOWN["bos_structural"],
            installation_labor=total_capex * CAPEX_BREAKDOWN["installation_labor"],
            engineering=total_capex * CAPEX_BREAKDOWN["engineering"],
            permitting=total_capex * CAPEX_BREAKDOWN["permitting"],
            contingency=total_capex * CAPEX_BREAKDOWN["contingency"],
            total=total_capex
        )

        return breakdown

    def calculate_opex(self, capex: float) -> OPEXBreakdown:
        """
        Bereken jaarlijkse OPEX breakdown.

        Args:
            capex: Totale CAPEX voor percentageberekening

        Returns:
            OPEXBreakdown met alle componenten
        """
        breakdown = OPEXBreakdown(
            maintenance=capex * OPEX_RATES["maintenance"],
            insurance=capex * OPEX_RATES["insurance"],
            monitoring=capex * OPEX_RATES["monitoring"],
            grid_fees=capex * OPEX_RATES["grid_fees"],
            total=capex * sum(OPEX_RATES.values())
        )

        return breakdown

    def calculate_tco(
        self,
        annual_cycles: float,
        average_dod: float = 0.8,
        average_throughput_kwh: Optional[float] = None,
        average_temp_c: float = 25.0,
        custom_capex: Optional[float] = None
    ) -> TCOResult:
        """
        Bereken volledige TCO met LCOS.

        LCOS FORMULE (Lazard v9.0):
        LCOS = (CAPEX + PV(OPEX) + PV(Replacements) - PV(Residual)) / PV(Throughput)

        Args:
            annual_cycles: Geschat aantal cycli per jaar
            average_dod: Gemiddelde Depth of Discharge
            average_throughput_kwh: Jaarlijkse energie throughput (optioneel)
            average_temp_c: Gemiddelde temperatuur
            custom_capex: Override CAPEX (optioneel)

        Returns:
            TCOResult met complete breakdown
        """
        # === CAPEX ===
        if custom_capex:
            capex_breakdown = CAPEXBreakdown(
                cells_and_modules=custom_capex * CAPEX_BREAKDOWN["cells_and_modules"],
                inverter_pcs=custom_capex * CAPEX_BREAKDOWN["inverter_pcs"],
                bos_electrical=custom_capex * CAPEX_BREAKDOWN["bos_electrical"],
                bos_structural=custom_capex * CAPEX_BREAKDOWN["bos_structural"],
                installation_labor=custom_capex * CAPEX_BREAKDOWN["installation_labor"],
                engineering=custom_capex * CAPEX_BREAKDOWN["engineering"],
                permitting=custom_capex * CAPEX_BREAKDOWN["permitting"],
                contingency=custom_capex * CAPEX_BREAKDOWN["contingency"],
                total=custom_capex
            )
        else:
            capex_breakdown = self.calculate_capex()

        capex_total = capex_breakdown.total
        capex_per_kwh = capex_total / self.capacity_kwh

        # === OPEX ===
        opex_breakdown = self.calculate_opex(capex_total)
        opex_annual = opex_breakdown.total

        # NPV van OPEX over analyseperiode (met inflatie)
        opex_total_npv = sum(
            opex_annual * ((1 + self.inflation_rate) ** year) /
            ((1 + self.discount_rate) ** year)
            for year in range(1, self.analysis_years + 1)
        )

        # === REPLACEMENT ===
        replacement_year = self.degradation_model.estimate_replacement_year(
            annual_cycles=annual_cycles,
            average_dod=average_dod,
            average_temp_c=average_temp_c,
            eol_threshold=0.80
        )

        replacement_cost = 0.0
        replacement_npv = 0.0

        if replacement_year and replacement_year < self.analysis_years:
            # Kosten voor vervanging (alleen cellen, niet hele systeem)
            # Celvervanging is typisch 50-60% van originele CAPEX
            replacement_cost = capex_total * 0.55

            # NPV van vervanging
            replacement_npv = replacement_cost / (
                (1 + self.discount_rate) ** replacement_year
            )

        # === RESIDUAL VALUE ===
        # Restwaarde aan einde analyseperiode
        # Gebaseerd op degradatie en lineaire afschrijving

        # Bereken degradatie aan einde analyseperiode
        end_degradation = self.degradation_model.calculate_degradation(
            years=self.analysis_years,
            cycles=annual_cycles * self.analysis_years,
            average_dod=average_dod,
            average_temp_c=average_temp_c
        )

        # Restwaarde: lineaire afschrijving * remaining capacity
        # Typische levensduur voor afschrijving: 15 jaar
        depreciation_life = 15
        linear_residual = max(0, 1 - self.analysis_years / depreciation_life)

        # Corrigeer voor daadwerkelijke state of health
        residual_value = capex_total * linear_residual * end_degradation.remaining_capacity
        residual_npv = residual_value / ((1 + self.discount_rate) ** self.analysis_years)

        # === ENERGY THROUGHPUT ===
        # Totale energie over analyseperiode (met degradatie)
        if average_throughput_kwh:
            annual_throughput = average_throughput_kwh
        else:
            # Schat throughput op basis van cycli en DoD
            annual_throughput = self.capacity_kwh * annual_cycles * average_dod

        # NPV van throughput (met degradatie)
        total_throughput_kwh = 0.0
        throughput_npv = 0.0

        for year in range(1, self.analysis_years + 1):
            # Degradatie in dit jaar
            degradation = self.degradation_model.calculate_degradation(
                years=year,
                cycles=annual_cycles * year,
                average_dod=average_dod,
                average_temp_c=average_temp_c
            )

            year_throughput = annual_throughput * degradation.remaining_capacity
            total_throughput_kwh += year_throughput

            # Disconteer throughput (voor LCOS berekening)
            throughput_npv += year_throughput / ((1 + self.discount_rate) ** year)

        # === TOTALE KOSTEN ===
        total_cost_npv = capex_total + opex_total_npv + replacement_npv - residual_npv

        # Kosten per kWh opgeslagen
        cost_per_kwh_stored = total_cost_npv / total_throughput_kwh if total_throughput_kwh > 0 else float('inf')

        # === LCOS (Lazard methodology) ===
        # LCOS = Total NPV costs / NPV of throughput
        lcos = total_cost_npv / throughput_npv if throughput_npv > 0 else float('inf')

        return TCOResult(
            capex_total=capex_total,
            capex_breakdown=capex_breakdown,
            capex_per_kwh=capex_per_kwh,
            opex_annual=opex_annual,
            opex_breakdown=opex_breakdown,
            opex_total_npv=opex_total_npv,
            replacement_year=int(replacement_year) if replacement_year else None,
            replacement_cost=replacement_cost,
            replacement_npv=replacement_npv,
            residual_value=residual_value,
            residual_npv=residual_npv,
            total_cost_npv=total_cost_npv,
            cost_per_kwh_stored=cost_per_kwh_stored,
            lcos=lcos,
            total_throughput_kwh=total_throughput_kwh
        )

    def calculate_financial_metrics(
        self,
        tco: TCOResult,
        annual_savings: float,
        peak_savings_annual: float = 0,
        annual_cycles: float = 0,
        average_dod: float = 0.8
    ) -> FinancialMetrics:
        """
        Bereken financiële metrics voor investeringsbeslissing.

        Args:
            tco: TCO resultaat
            annual_savings: Jaarlijkse energiebesparingen (€)
            peak_savings_annual: Jaarlijkse piekbesparingen (€)
            annual_cycles: Werkelijke cycli per jaar uit simulatie
            average_dod: Gemiddelde depth of discharge uit simulatie

        Returns:
            FinancialMetrics met alle metrics
        """
        total_annual_savings = annual_savings + peak_savings_annual

        # === SIMPLE PAYBACK ===
        if total_annual_savings > 0:
            simple_payback = tco.capex_total / total_annual_savings
        else:
            simple_payback = float('inf')

        # === CASH FLOWS ===
        cash_flows = []
        cumulative_npv = -tco.capex_total

        for year in range(1, self.analysis_years + 1):
            # Degradatie-factor voor besparingen - gebruik ECHTE cycli uit simulatie
            degradation = self.degradation_model.calculate_degradation(
                years=year,
                cycles=annual_cycles * year,
                average_dod=average_dod
            )

            year_savings = total_annual_savings * degradation.remaining_capacity
            year_opex = tco.opex_annual * ((1 + self.inflation_rate) ** year)

            # Eventuele vervanging
            year_replacement = 0
            if tco.replacement_year and year == tco.replacement_year:
                year_replacement = tco.replacement_cost

            net_cash_flow = year_savings - year_opex - year_replacement
            cash_flows.append(net_cash_flow)

        # === NPV ===
        npv = -tco.capex_total
        for year, cf in enumerate(cash_flows, 1):
            npv += cf / ((1 + self.discount_rate) ** year)

        # === IRR ===
        irr = self._calculate_irr(tco.capex_total, cash_flows)

        # === PROFITABILITY INDEX ===
        pv_benefits = sum(
            max(0, cf) / ((1 + self.discount_rate) ** (i + 1))
            for i, cf in enumerate(cash_flows)
        )
        profitability_index = pv_benefits / tco.capex_total if tco.capex_total > 0 else 0

        # === DISCOUNTED PAYBACK ===
        cumulative = -tco.capex_total
        discounted_payback = None

        for year, cf in enumerate(cash_flows, 1):
            discounted_cf = cf / ((1 + self.discount_rate) ** year)
            cumulative += discounted_cf

            if cumulative >= 0 and discounted_payback is None:
                # Interpoleer exact moment
                prev_cumulative = cumulative - discounted_cf
                fraction = -prev_cumulative / discounted_cf if discounted_cf != 0 else 0
                discounted_payback = year - 1 + fraction

        # === BREAKEVEN UTILIZATION ===
        # Minimale benutting om break-even te draaien
        if total_annual_savings > 0:
            annual_costs = tco.opex_annual + (tco.capex_total / self.analysis_years)
            breakeven_utilization = annual_costs / total_annual_savings
        else:
            breakeven_utilization = float('inf')

        return FinancialMetrics(
            simple_payback_years=min(100, simple_payback),
            npv=npv,
            irr=irr,
            profitability_index=profitability_index,
            modified_irr=None,  # TODO: Implement MIRR
            discounted_payback_years=discounted_payback,
            breakeven_utilization=min(2.0, breakeven_utilization)
        )

    def _get_scale_factor(self, capacity_kwh: float) -> float:
        """
        Bepaal schaalfactor op basis van capaciteit.
        """
        for threshold, factor in SCALE_FACTORS:
            if capacity_kwh < threshold:
                return factor
        return SCALE_FACTORS[-1][1]

    def _calculate_irr(
        self,
        initial_investment: float,
        cash_flows: List[float],
        max_iterations: int = 100,
        tolerance: float = 1e-6
    ) -> Optional[float]:
        """
        Bereken IRR met Newton-Raphson + bisection fallback.

        Args:
            initial_investment: Initiële investering (positief getal)
            cash_flows: Lijst met jaarlijkse cash flows

        Returns:
            IRR als decimaal (bijv. 0.15 voor 15%), of None
        """
        if not cash_flows or all(cf <= 0 for cf in cash_flows):
            return None

        # Newton-Raphson methode
        rate = 0.1

        for iteration in range(max_iterations):
            npv = -initial_investment
            dnpv = 0.0

            for year, cf in enumerate(cash_flows, 1):
                discount = (1 + rate) ** year
                npv += cf / discount
                dnpv -= year * cf / ((1 + rate) ** (year + 1))

            if abs(dnpv) < tolerance:
                break

            new_rate = rate - npv / dnpv

            if abs(new_rate - rate) < tolerance:
                if -0.5 < new_rate < 2.0:
                    return new_rate
                break

            rate = new_rate

            if rate < -0.99 or rate > 10:
                break

        # Fallback: bisection methode
        return self._calculate_irr_bisection(initial_investment, cash_flows)

    def _calculate_irr_bisection(
        self,
        initial_investment: float,
        cash_flows: List[float],
        low: float = -0.5,
        high: float = 2.0,
        tolerance: float = 1e-6,
        max_iterations: int = 100
    ) -> Optional[float]:
        """
        Bisection fallback voor IRR berekening.
        """
        def npv_at_rate(r: float) -> float:
            npv = -initial_investment
            for year, cf in enumerate(cash_flows, 1):
                npv += cf / ((1 + r) ** year)
            return npv

        npv_low = npv_at_rate(low)
        npv_high = npv_at_rate(high)

        # Check of er een root is
        if npv_low * npv_high > 0:
            return None

        for _ in range(max_iterations):
            mid = (low + high) / 2
            npv_mid = npv_at_rate(mid)

            if abs(npv_mid) < tolerance or (high - low) / 2 < tolerance:
                return mid

            if npv_mid * npv_low < 0:
                high = mid
                npv_high = npv_mid
            else:
                low = mid
                npv_low = npv_mid

        return (low + high) / 2
