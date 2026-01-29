"""Financial calculations for battery investments."""

from typing import Optional
import structlog

from app.models.schemas import BatteryConfig, SimulationSummary, FinancialAnalysis

logger = structlog.get_logger()


def calculate_financials(
    config: BatteryConfig,
    simulation: SimulationSummary,
    analysis_years: int = 10,
    discount_rate: float = 0.05,
    opex_percentage: float = 0.02
) -> FinancialAnalysis:
    """
    Calculate comprehensive financial metrics.

    Args:
        config: Battery configuration
        simulation: Simulation results
        analysis_years: NPV analysis horizon
        discount_rate: Discount rate for NPV
        opex_percentage: Annual O&M as percentage of CAPEX

    Returns:
        FinancialAnalysis with all metrics
    """
    # CAPEX
    capex = config.capacity_kwh * config.price_per_kwh

    # Annual savings
    annual_savings = simulation.total_cost_savings_eur + simulation.peak_savings_eur_year

    # Simple payback
    simple_payback = capex / annual_savings if annual_savings > 0 else float('inf')

    # Annual OPEX
    annual_opex = capex * opex_percentage

    # NPV calculation with degradation
    npv = -capex
    cash_flows = []

    for year in range(1, analysis_years + 1):
        # Apply degradation to savings
        degradation_factor = (1 - config.degradation_rate) ** year
        year_savings = annual_savings * degradation_factor - annual_opex

        # Discount
        discounted = year_savings / ((1 + discount_rate) ** year)
        npv += discounted
        cash_flows.append(year_savings)

    # IRR calculation
    irr = calculate_irr(capex, cash_flows)

    # LCOE (Levelized Cost of Storage)
    if simulation.total_energy_savings_kwh > 0:
        pv_cost = capex + sum(
            annual_opex / ((1 + discount_rate) ** y)
            for y in range(1, analysis_years + 1)
        )
        pv_energy = sum(
            simulation.total_energy_savings_kwh * ((1 - config.degradation_rate) ** y) / ((1 + discount_rate) ** y)
            for y in range(1, analysis_years + 1)
        )
        lcoe = pv_cost / pv_energy if pv_energy > 0 else float('inf')
    else:
        lcoe = float('inf')

    # ROI
    total_returns = sum(cash_flows)
    roi = (total_returns - capex) / capex if capex > 0 else 0

    # Cap unrealistic values
    if simple_payback > 100:
        simple_payback = 100
    if lcoe > 10:
        lcoe = 10

    return FinancialAnalysis(
        capex=round(capex, 2),
        annual_savings=round(annual_savings, 2),
        simple_payback_years=round(simple_payback, 2),
        npv=round(npv, 2),
        irr=round(irr, 4) if irr else None,
        lcoe=round(lcoe, 4),
        roi=round(roi, 4)
    )


def calculate_irr(
    initial_investment: float,
    cash_flows: list[float],
    max_iterations: int = 100,
    tolerance: float = 1e-6
) -> Optional[float]:
    """
    Calculate Internal Rate of Return using Newton-Raphson method.

    Args:
        initial_investment: Initial outlay (positive number)
        cash_flows: List of annual cash flows

    Returns:
        IRR as decimal (e.g., 0.15 for 15%) or None if not converging
    """
    if not cash_flows or all(cf <= 0 for cf in cash_flows):
        return None

    # Initial guess
    rate = 0.1

    for _ in range(max_iterations):
        # Calculate NPV at current rate
        npv = -initial_investment
        dnpv = 0.0  # Derivative

        for year, cf in enumerate(cash_flows, 1):
            discount = (1 + rate) ** year
            npv += cf / discount
            dnpv -= year * cf / ((1 + rate) ** (year + 1))

        # Newton-Raphson step
        if abs(dnpv) < tolerance:
            break

        new_rate = rate - npv / dnpv

        # Convergence check
        if abs(new_rate - rate) < tolerance:
            return new_rate

        rate = new_rate

        # Bounds check
        if rate < -0.99 or rate > 10:
            return None

    return rate if -0.5 < rate < 5 else None


def calculate_lcoe_detailed(
    config: BatteryConfig,
    simulation: SimulationSummary,
    analysis_years: int,
    discount_rate: float,
    opex_percentage: float = 0.02
) -> dict:
    """
    Detailed LCOE breakdown.

    Returns:
        Dict with LCOE components
    """
    capex = config.capacity_kwh * config.price_per_kwh
    annual_opex = capex * opex_percentage

    # Present value of costs
    pv_capex = capex
    pv_opex = sum(
        annual_opex / ((1 + discount_rate) ** y)
        for y in range(1, analysis_years + 1)
    )

    # Present value of energy
    pv_energy = sum(
        simulation.total_energy_savings_kwh * ((1 - config.degradation_rate) ** y) / ((1 + discount_rate) ** y)
        for y in range(1, analysis_years + 1)
    )

    total_pv_cost = pv_capex + pv_opex

    return {
        'lcoe': total_pv_cost / pv_energy if pv_energy > 0 else float('inf'),
        'capex_component': pv_capex / pv_energy if pv_energy > 0 else 0,
        'opex_component': pv_opex / pv_energy if pv_energy > 0 else 0,
        'total_pv_cost': total_pv_cost,
        'total_pv_energy': pv_energy
    }
