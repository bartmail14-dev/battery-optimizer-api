"""Battery size optimizer."""

from typing import List
import pandas as pd
import structlog
from concurrent.futures import ThreadPoolExecutor
import time

from app.models.schemas import (
    BatteryConfig, BatteryConstraints, TariffStructure,
    OptimizationResult, BatteryScenario, SensitivityPoint,
    OptimizationStrategy
)
from app.core.simulator import SimulationEngine
from app.core.financials import calculate_financials

logger = structlog.get_logger()


class BatteryOptimizer:
    """
    Battery size optimizer using simulation-based grid search.
    """

    # Default battery sizes to evaluate (kWh)
    GRID_SIZES = [5, 10, 15, 20, 30, 50, 75, 100, 150, 200, 300, 500]

    def __init__(
        self,
        profile_df: pd.DataFrame,
        tariffs: TariffStructure,
        constraints: BatteryConstraints,
        strategy: OptimizationStrategy = OptimizationStrategy.HYBRID,
        analysis_years: int = 10,
        discount_rate: float = 0.05
    ):
        self.profile_df = profile_df
        self.tariffs = tariffs
        self.constraints = constraints
        self.strategy = strategy
        self.analysis_years = analysis_years
        self.discount_rate = discount_rate

        # Filter sizes by constraints
        self.sizes_to_evaluate = [
            s for s in self.GRID_SIZES
            if constraints.min_capacity_kwh <= s <= constraints.max_capacity_kwh
        ]

    def optimize(self) -> OptimizationResult:
        """
        Run full optimization pipeline.

        Returns:
            OptimizationResult with optimal configuration and alternatives
        """
        start_time = time.time()
        logger.info(
            "Starting optimization",
            sizes=len(self.sizes_to_evaluate),
            strategy=self.strategy.value
        )

        try:
            # Phase 1: Grid search
            scenarios = self._evaluate_all_sizes()

            if not scenarios:
                return OptimizationResult(
                    success=False,
                    optimal=None,
                    alternatives=[],
                    sensitivity_analysis=[],
                    computation_time_seconds=time.time() - start_time,
                    methodology_notes="",
                    error="Geen batterijconfiguraties konden worden geëvalueerd"
                )

            # Phase 2: Filter by constraints
            valid_scenarios = self._apply_constraints(scenarios)

            if not valid_scenarios:
                # Return best scenario even if constraints not met
                optimal = max(scenarios, key=lambda s: s.financials.npv)
                optimal.is_optimal = True

                return OptimizationResult(
                    success=True,
                    optimal=optimal,
                    alternatives=scenarios[:5],
                    sensitivity_analysis=[],
                    computation_time_seconds=time.time() - start_time,
                    methodology_notes=self._generate_methodology_notes(),
                    error="Waarschuwing: Geen configuratie voldoet volledig aan alle constraints"
                )

            # Phase 3: Select optimal (highest NPV)
            optimal = max(valid_scenarios, key=lambda s: s.financials.npv)
            optimal.is_optimal = True

            # Phase 4: Select alternatives (top 5 excluding optimal)
            alternatives = sorted(
                [s for s in valid_scenarios if s != optimal],
                key=lambda s: s.financials.npv,
                reverse=True
            )[:5]

            # Phase 5: Sensitivity analysis
            sensitivity = self._run_sensitivity_analysis(optimal)

            computation_time = time.time() - start_time
            logger.info("Optimization complete", time_seconds=computation_time)

            return OptimizationResult(
                success=True,
                optimal=optimal,
                alternatives=alternatives,
                sensitivity_analysis=sensitivity,
                computation_time_seconds=round(computation_time, 2),
                methodology_notes=self._generate_methodology_notes(),
                error=None
            )

        except Exception as e:
            logger.error("Optimization failed", error=str(e))
            return OptimizationResult(
                success=False,
                optimal=None,
                alternatives=[],
                sensitivity_analysis=[],
                computation_time_seconds=time.time() - start_time,
                methodology_notes="",
                error=str(e)
            )

    def _evaluate_all_sizes(self) -> List[BatteryScenario]:
        """Evaluate all battery sizes in parallel."""
        scenarios = []

        # Use ThreadPoolExecutor for parallel simulation
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self._evaluate_single_size, size): size
                for size in self.sizes_to_evaluate
            }

            for future in futures:
                try:
                    scenario = future.result()
                    scenarios.append(scenario)
                except Exception as e:
                    logger.error("Simulation failed", size=futures[future], error=str(e))

        return sorted(scenarios, key=lambda s: s.capacity_kwh)

    def _evaluate_single_size(self, capacity_kwh: float) -> BatteryScenario:
        """Evaluate a single battery size."""
        # Create battery config
        config = BatteryConfig(
            capacity_kwh=capacity_kwh,
            max_power_kw=capacity_kwh * 0.5,  # 0.5C rate
            charge_efficiency=0.959,
            discharge_efficiency=0.959,
            min_soc=0.1,
            max_soc=0.9,
            degradation_rate=0.02,
            cycle_life=6000,
            price_per_kwh=450.0
        )

        # Run simulation
        engine = SimulationEngine(self.profile_df, self.tariffs)
        _, simulation = engine.simulate(config, self.strategy)

        # Calculate financials
        financials = calculate_financials(
            config=config,
            simulation=simulation,
            analysis_years=self.analysis_years,
            discount_rate=self.discount_rate
        )

        return BatteryScenario(
            capacity_kwh=capacity_kwh,
            max_power_kw=config.max_power_kw,
            config=config,
            simulation=simulation,
            financials=financials,
            is_optimal=False
        )

    def _apply_constraints(self, scenarios: List[BatteryScenario]) -> List[BatteryScenario]:
        """Filter scenarios by user constraints."""
        valid = []

        for s in scenarios:
            # Budget constraint
            if self.constraints.max_budget_eur and s.financials.capex > self.constraints.max_budget_eur:
                continue

            # Payback constraint
            if self.constraints.max_payback_years and s.financials.simple_payback_years > self.constraints.max_payback_years:
                continue

            # NPV constraint
            if self.constraints.min_npv and s.financials.npv < self.constraints.min_npv:
                continue

            valid.append(s)

        return valid

    def _run_sensitivity_analysis(self, optimal: BatteryScenario) -> List[SensitivityPoint]:
        """Run sensitivity analysis on key parameters."""
        sensitivity_points = []

        parameters = {
            'energy_price': [0.8, 1.0, 1.2],
            'capacity_tariff': [0.7, 1.0, 1.3],
            'battery_price': [0.75, 1.0, 1.25],
        }

        for param, variations in parameters.items():
            for mult in variations:
                # Modify tariffs/config
                modified_tariffs = TariffStructure(
                    peak_rate=self.tariffs.peak_rate * (mult if param == 'energy_price' else 1),
                    off_peak_rate=self.tariffs.off_peak_rate * (mult if param == 'energy_price' else 1),
                    peak_hours_start=self.tariffs.peak_hours_start,
                    peak_hours_end=self.tariffs.peak_hours_end,
                    capacity_tariff=self.tariffs.capacity_tariff * (mult if param == 'capacity_tariff' else 1),
                    feed_in_tariff=self.tariffs.feed_in_tariff
                )

                # Re-simulate with modified parameters
                engine = SimulationEngine(self.profile_df, modified_tariffs)

                modified_config = BatteryConfig(
                    capacity_kwh=optimal.config.capacity_kwh,
                    max_power_kw=optimal.config.max_power_kw,
                    charge_efficiency=optimal.config.charge_efficiency,
                    discharge_efficiency=optimal.config.discharge_efficiency,
                    min_soc=optimal.config.min_soc,
                    max_soc=optimal.config.max_soc,
                    degradation_rate=optimal.config.degradation_rate,
                    cycle_life=optimal.config.cycle_life,
                    price_per_kwh=optimal.config.price_per_kwh * (mult if param == 'battery_price' else 1)
                )

                _, simulation = engine.simulate(modified_config, self.strategy)

                financials = calculate_financials(
                    config=modified_config,
                    simulation=simulation,
                    analysis_years=self.analysis_years,
                    discount_rate=self.discount_rate
                )

                sensitivity_points.append(SensitivityPoint(
                    parameter=param,
                    variation=mult,
                    npv=financials.npv
                ))

        return sensitivity_points

    def _generate_methodology_notes(self) -> str:
        """Generate methodology documentation."""
        return f"""
## Methodologie

### Optimalisatie Aanpak
- Grid search over {len(self.sizes_to_evaluate)} batterijconfiguraties
- Simulatie met {self.strategy.value} strategie
- NPV-optimalisatie over {self.analysis_years} jaar

### Batterij Parameters
- Laad/ontlaad efficiency: 95.9% (round-trip: 92%)
- C-rate: 0.5 (vermogen = capaciteit x 0.5)
- SoC range: 10% - 90%
- Degradatie: 2% per jaar (kalendarisch)
- Cycle life: 6000 cycli (LFP)

### Financiële Aannames
- Discontovoet: {self.discount_rate:.1%}
- Batterijprijs: 450 EUR/kWh geïnstalleerd
- Onderhoudskosten: 2% van CAPEX/jaar
- Analysehorizon: {self.analysis_years} jaar

### Tariefstructuur
- Piekhours: {self.tariffs.peak_hours_start}:00 - {self.tariffs.peak_hours_end}:00
- Piektarief: EUR {self.tariffs.peak_rate}/kWh
- Daltarief: EUR {self.tariffs.off_peak_rate}/kWh
- Capaciteitstarief: EUR {self.tariffs.capacity_tariff}/kW/maand
        """.strip()
