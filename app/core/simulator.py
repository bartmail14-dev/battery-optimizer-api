"""Battery simulation engine with multiple strategies."""

import pandas as pd
from typing import Tuple
import structlog

from app.models.schemas import (
    BatteryConfig, TariffStructure, SimulationSummary,
    OptimizationStrategy
)
from app.core.battery import BatteryModel

logger = structlog.get_logger()


class SimulationEngine:
    """
    Battery simulation engine with multiple optimization strategies.

    Implements:
    - Peak shaving
    - Arbitrage
    - Self-consumption
    - Hybrid (weighted combination)
    """

    def __init__(
        self,
        profile_df: pd.DataFrame,
        tariffs: TariffStructure,
        interval_minutes: int = 15
    ):
        self.df = profile_df.copy()
        self.tariffs = tariffs
        self.interval_hours = interval_minutes / 60

        # Pre-calculate derived columns
        self.df['hour'] = self.df['timestamp'].dt.hour
        self.df['net_load_kwh'] = self.df['afname_kwh'] - self.df['teruglevering_kwh']
        self.df['tariff'] = self.df['hour'].apply(self._get_tariff)

        # Calculate statistics for strategy decisions
        self.avg_tariff = float(self.df['tariff'].mean())
        self.load_p70 = float(self.df['net_load_kwh'].quantile(0.70))
        self.load_p75 = float(self.df['net_load_kwh'].quantile(0.75))

    def _get_tariff(self, hour: int) -> float:
        """Get electricity tariff for given hour."""
        if self.tariffs.peak_hours_start <= hour < self.tariffs.peak_hours_end:
            return self.tariffs.peak_rate
        return self.tariffs.off_peak_rate

    def simulate(
        self,
        battery_config: BatteryConfig,
        strategy: OptimizationStrategy = OptimizationStrategy.HYBRID
    ) -> Tuple[pd.DataFrame, SimulationSummary]:
        """
        Run full simulation over profile.

        Returns:
            Tuple of (detailed results DataFrame, summary)
        """
        battery = BatteryModel(battery_config)

        # Results storage
        results = []
        strategy_savings = {'peak_shaving': 0.0, 'arbitrage': 0.0, 'self_consumption': 0.0}
        original_peak = 0.0
        new_peak = 0.0

        for _, row in self.df.iterrows():
            net_load = float(row['net_load_kwh'])
            hour = int(row['hour'])
            tariff = float(row['tariff'])

            # Get strategy decision
            action, amount = self._get_strategy_decision(
                strategy=strategy,
                net_load=net_load,
                hour=hour,
                tariff=tariff,
                battery=battery
            )

            # Execute action
            charge_kwh = 0.0
            discharge_kwh = 0.0
            savings = 0.0

            if action == 'charge' and amount > 0:
                result = battery.charge(amount, self.interval_hours)
                charge_kwh = result.charged_kwh
                # Cost of charging (negative savings)
                savings = -charge_kwh * tariff

            elif action == 'discharge' and amount > 0:
                result = battery.discharge(amount, self.interval_hours)
                discharge_kwh = result.discharged_kwh
                # Savings from avoided grid import
                savings = discharge_kwh * tariff

                # Track which strategy contributed
                if net_load > battery_config.capacity_kwh * 0.5:
                    strategy_savings['peak_shaving'] += savings
                elif tariff > self.avg_tariff:
                    strategy_savings['arbitrage'] += savings
                else:
                    strategy_savings['self_consumption'] += savings

            # Calculate new grid exchange
            new_load = net_load - discharge_kwh + charge_kwh

            # Track peaks
            original_power = net_load / self.interval_hours
            new_power = new_load / self.interval_hours
            original_peak = max(original_peak, original_power)
            new_peak = max(new_peak, new_power)

            results.append({
                'timestamp': row['timestamp'],
                'original_load_kwh': net_load,
                'new_load_kwh': new_load,
                'charge_kwh': charge_kwh,
                'discharge_kwh': discharge_kwh,
                'soc_kwh': battery.soc_kwh,
                'soc_percent': battery.soc_percent,
                'savings_eur': savings,
                'tariff': tariff
            })

        results_df = pd.DataFrame(results)

        # Calculate summary
        total_savings = float(results_df['savings_eur'].sum())
        peak_reduction = original_peak - new_peak
        peak_savings_monthly = peak_reduction * self.tariffs.capacity_tariff

        # Annualize
        date_range = self.df['timestamp'].max() - self.df['timestamp'].min()
        data_days = max(1, date_range.days + 1)
        annual_factor = 365 / data_days

        state = battery.get_state()

        summary = SimulationSummary(
            total_energy_savings_kwh=round(float(results_df['discharge_kwh'].sum()), 2),
            total_cost_savings_eur=round(total_savings + peak_savings_monthly * 12 / annual_factor, 2),
            peak_reduction_kw=round(peak_reduction, 2),
            peak_savings_eur_year=round(peak_savings_monthly * 12, 2),
            self_consumption_increase=0.0,
            cycles_per_year=round(state.total_cycles * annual_factor, 1),
            strategy_breakdown={k: round(v * annual_factor, 2) for k, v in strategy_savings.items()}
        )

        return results_df, summary

    def _get_strategy_decision(
        self,
        strategy: OptimizationStrategy,
        net_load: float,
        hour: int,
        tariff: float,
        battery: BatteryModel
    ) -> Tuple[str, float]:
        """
        Determine charge/discharge action based on strategy.

        Returns:
            Tuple of (action: 'charge'|'discharge'|'idle', amount_kwh)
        """
        if strategy == OptimizationStrategy.PEAK_SHAVING:
            return self._peak_shaving_decision(net_load, battery)

        elif strategy == OptimizationStrategy.ARBITRAGE:
            return self._arbitrage_decision(tariff, battery)

        elif strategy == OptimizationStrategy.SELF_CONSUMPTION:
            return self._self_consumption_decision(net_load, battery)

        else:  # HYBRID
            return self._hybrid_decision(net_load, tariff, battery)

    def _peak_shaving_decision(
        self,
        net_load: float,
        battery: BatteryModel
    ) -> Tuple[str, float]:
        """Peak shaving: discharge to reduce peaks, charge during valleys."""
        if net_load > self.load_p70:
            discharge_needed = net_load - self.load_p70
            return 'discharge', discharge_needed

        elif net_load < self.load_p70 * 0.3 and battery.soc_percent < 0.8:
            charge_amount = self.load_p70 * 0.3 - net_load
            return 'charge', charge_amount

        return 'idle', 0.0

    def _arbitrage_decision(
        self,
        tariff: float,
        battery: BatteryModel
    ) -> Tuple[str, float]:
        """Arbitrage: charge when cheap, discharge when expensive."""
        max_charge = battery.config.max_power_kw * self.interval_hours

        if tariff < self.avg_tariff * 0.85 and battery.soc_percent < 0.85:
            return 'charge', max_charge

        elif tariff > self.avg_tariff * 1.15 and battery.soc_percent > 0.2:
            return 'discharge', max_charge

        return 'idle', 0.0

    def _self_consumption_decision(
        self,
        net_load: float,
        battery: BatteryModel
    ) -> Tuple[str, float]:
        """Self-consumption: store excess solar, use during demand."""
        if net_load < 0:  # Excess production
            return 'charge', abs(net_load)

        elif net_load > 0 and battery.soc_percent > 0.15:
            return 'discharge', net_load

        return 'idle', 0.0

    def _hybrid_decision(
        self,
        net_load: float,
        tariff: float,
        battery: BatteryModel
    ) -> Tuple[str, float]:
        """
        Hybrid strategy: weighted combination.

        Priority: self-consumption > peak-shaving > arbitrage
        """
        # 1. First handle excess solar
        if net_load < 0:
            return 'charge', abs(net_load)

        # 2. Peak shaving during high loads
        if net_load > self.load_p75 and battery.soc_percent > 0.2:
            return 'discharge', (net_load - self.load_p75) * 0.8

        # 3. Arbitrage for remaining capacity
        max_power = battery.config.max_power_kw * self.interval_hours

        if tariff < self.avg_tariff * 0.8 and battery.soc_percent < 0.85:
            return 'charge', max_power * 0.5

        elif tariff > self.avg_tariff * 1.2 and battery.soc_percent > 0.3:
            return 'discharge', max_power * 0.5

        return 'idle', 0.0
