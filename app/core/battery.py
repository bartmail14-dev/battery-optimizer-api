"""Battery model with physical constraints."""

from dataclasses import dataclass
import structlog

from app.models.schemas import BatteryConfig

logger = structlog.get_logger()


@dataclass
class BatteryState:
    """Current state of the battery."""
    soc_kwh: float
    soc_percent: float
    total_charged_kwh: float
    total_discharged_kwh: float
    total_cycles: float
    degradation_factor: float


@dataclass
class ChargeResult:
    """Result of a charge operation."""
    charged_kwh: float
    curtailed_kwh: float
    new_soc_kwh: float
    new_soc_percent: float


@dataclass
class DischargeResult:
    """Result of a discharge operation."""
    discharged_kwh: float
    unmet_kwh: float
    new_soc_kwh: float
    new_soc_percent: float


class BatteryModel:
    """
    Physical battery model with efficiency, degradation, and constraints.

    Uses industry-standard lithium-ion battery characteristics.
    """

    def __init__(self, config: BatteryConfig):
        self.config = config
        self._soc_kwh = config.capacity_kwh * 0.5  # Start at 50%
        self._total_charged = 0.0
        self._total_discharged = 0.0
        self._cycles = 0.0
        self._degradation = 1.0

    @property
    def capacity_kwh(self) -> float:
        """Current capacity accounting for degradation."""
        return self.config.capacity_kwh * self._degradation

    @property
    def soc_kwh(self) -> float:
        """Current state of charge in kWh."""
        return self._soc_kwh

    @property
    def soc_percent(self) -> float:
        """Current state of charge as percentage (0-1)."""
        return self._soc_kwh / self.capacity_kwh if self.capacity_kwh > 0 else 0

    @property
    def available_charge_capacity(self) -> float:
        """Available capacity for charging (kWh)."""
        max_soc = self.capacity_kwh * self.config.max_soc
        return max(0, max_soc - self._soc_kwh)

    @property
    def available_discharge_capacity(self) -> float:
        """Available capacity for discharging (kWh)."""
        min_soc = self.capacity_kwh * self.config.min_soc
        return max(0, self._soc_kwh - min_soc)

    def charge(self, energy_kwh: float, interval_hours: float = 0.25) -> ChargeResult:
        """
        Charge the battery.

        Args:
            energy_kwh: Desired charge energy (kWh)
            interval_hours: Time interval (default 15 min = 0.25 h)

        Returns:
            ChargeResult with actual charged amount and new state
        """
        if energy_kwh <= 0:
            return ChargeResult(
                charged_kwh=0,
                curtailed_kwh=0,
                new_soc_kwh=self._soc_kwh,
                new_soc_percent=self.soc_percent
            )

        # Power constraint
        max_power_kwh = self.config.max_power_kw * interval_hours

        # Capacity constraint
        available = self.available_charge_capacity / self.config.charge_efficiency

        # Actual charge (limited by power, capacity, and requested amount)
        actual_kwh = min(energy_kwh, max_power_kwh, available)
        stored_kwh = actual_kwh * self.config.charge_efficiency

        # Update state
        self._soc_kwh += stored_kwh
        self._total_charged += stored_kwh

        return ChargeResult(
            charged_kwh=actual_kwh,
            curtailed_kwh=max(0, energy_kwh - actual_kwh),
            new_soc_kwh=self._soc_kwh,
            new_soc_percent=self.soc_percent
        )

    def discharge(self, energy_kwh: float, interval_hours: float = 0.25) -> DischargeResult:
        """
        Discharge the battery.

        Args:
            energy_kwh: Desired discharge energy (kWh)
            interval_hours: Time interval (default 15 min = 0.25 h)

        Returns:
            DischargeResult with actual discharged amount and new state
        """
        if energy_kwh <= 0:
            return DischargeResult(
                discharged_kwh=0,
                unmet_kwh=0,
                new_soc_kwh=self._soc_kwh,
                new_soc_percent=self.soc_percent
            )

        # Power constraint
        max_power_kwh = self.config.max_power_kw * interval_hours

        # Capacity constraint (accounting for efficiency loss)
        available = self.available_discharge_capacity * self.config.discharge_efficiency

        # Actual discharge
        actual_kwh = min(energy_kwh, max_power_kwh, available)
        consumed_from_battery = actual_kwh / self.config.discharge_efficiency

        # Update state
        self._soc_kwh -= consumed_from_battery
        self._total_discharged += consumed_from_battery

        # Update cycle count
        self._cycles = self._total_discharged / self.config.capacity_kwh

        return DischargeResult(
            discharged_kwh=actual_kwh,
            unmet_kwh=max(0, energy_kwh - actual_kwh),
            new_soc_kwh=self._soc_kwh,
            new_soc_percent=self.soc_percent
        )

    def get_state(self) -> BatteryState:
        """Get current battery state."""
        return BatteryState(
            soc_kwh=round(self._soc_kwh, 3),
            soc_percent=round(self.soc_percent, 3),
            total_charged_kwh=round(self._total_charged, 3),
            total_discharged_kwh=round(self._total_discharged, 3),
            total_cycles=round(self._cycles, 2),
            degradation_factor=round(self._degradation, 4)
        )

    def apply_degradation(self, years: float) -> float:
        """
        Apply calendar and cycle degradation.

        Returns new capacity factor (0-1).
        """
        # Calendar degradation
        calendar_factor = (1 - self.config.degradation_rate) ** years

        # Cycle degradation (20% of capacity lost at rated cycle life)
        cycle_factor = 1 - (self._cycles / self.config.cycle_life) * 0.2
        cycle_factor = max(0.8, cycle_factor)  # Floor at 80%

        self._degradation = calendar_factor * cycle_factor
        return self._degradation

    def reset(self, initial_soc_percent: float = 0.5):
        """Reset battery to initial state."""
        self._soc_kwh = self.config.capacity_kwh * initial_soc_percent
        self._total_charged = 0.0
        self._total_discharged = 0.0
        self._cycles = 0.0
        self._degradation = 1.0

    def clone(self) -> 'BatteryModel':
        """Create a deep copy for parallel simulations."""
        new_battery = BatteryModel(self.config)
        new_battery._soc_kwh = self._soc_kwh
        new_battery._total_charged = self._total_charged
        new_battery._total_discharged = self._total_discharged
        new_battery._cycles = self._cycles
        new_battery._degradation = self._degradation
        return new_battery
