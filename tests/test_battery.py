"""Tests for battery model."""

import pytest
from app.core.battery import BatteryModel
from app.models.schemas import BatteryConfig


def test_battery_initialization(sample_battery_config):
    """Test battery initializes correctly."""
    battery = BatteryModel(sample_battery_config)

    assert battery.capacity_kwh == 50
    assert battery.soc_kwh == 25  # 50% of 50 kWh
    assert battery.soc_percent == 0.5


def test_battery_charge(sample_battery_config):
    """Test battery charging."""
    battery = BatteryModel(sample_battery_config)

    result = battery.charge(5, interval_hours=0.25)

    assert result.charged_kwh > 0
    assert result.charged_kwh <= 5
    assert battery.soc_kwh > 25


def test_battery_discharge(sample_battery_config):
    """Test battery discharging."""
    battery = BatteryModel(sample_battery_config)

    result = battery.discharge(5, interval_hours=0.25)

    assert result.discharged_kwh > 0
    assert result.discharged_kwh <= 5
    assert battery.soc_kwh < 25


def test_battery_soc_limits(sample_battery_config):
    """Test SOC stays within limits."""
    battery = BatteryModel(sample_battery_config)

    # Try to discharge beyond min SOC
    for _ in range(100):
        battery.discharge(10, interval_hours=0.25)

    assert battery.soc_percent >= sample_battery_config.min_soc

    # Reset and try to charge beyond max SOC
    battery.reset()
    for _ in range(100):
        battery.charge(10, interval_hours=0.25)

    assert battery.soc_percent <= sample_battery_config.max_soc


def test_battery_power_limit(sample_battery_config):
    """Test power limit is respected."""
    battery = BatteryModel(sample_battery_config)

    # Try to charge more than power limit allows
    max_power_kwh = sample_battery_config.max_power_kw * 0.25  # 15 min interval
    result = battery.charge(100, interval_hours=0.25)

    assert result.charged_kwh <= max_power_kwh


def test_battery_clone(sample_battery_config):
    """Test battery cloning."""
    battery = BatteryModel(sample_battery_config)
    battery.charge(5, interval_hours=0.25)

    clone = battery.clone()

    assert clone.soc_kwh == battery.soc_kwh

    # Modify original, clone should not change
    battery.charge(5, interval_hours=0.25)
    assert clone.soc_kwh != battery.soc_kwh
