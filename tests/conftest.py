"""Pytest configuration and fixtures."""

import pytest
from fastapi.testclient import TestClient
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from app.main import app
from app.models.schemas import BatteryConfig, TariffStructure


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def sample_profile_df():
    """Create sample energy profile DataFrame."""
    # Generate 7 days of 15-minute data
    n_intervals = 7 * 24 * 4  # 7 days, 24 hours, 4 intervals per hour
    start_date = datetime(2024, 1, 1)

    timestamps = [start_date + timedelta(minutes=15 * i) for i in range(n_intervals)]

    # Generate realistic consumption pattern
    hours = [t.hour for t in timestamps]
    base_load = 0.5  # kWh per 15 min (2 kW baseload)

    # Add daily pattern
    afname = []
    teruglevering = []

    for i, t in enumerate(timestamps):
        hour = t.hour

        # Consumption: higher during day, peaks at morning and evening
        if 7 <= hour < 9:  # Morning peak
            load = base_load + np.random.uniform(0.3, 0.6)
        elif 17 <= hour < 21:  # Evening peak
            load = base_load + np.random.uniform(0.4, 0.8)
        elif 9 <= hour < 17:  # Day
            load = base_load + np.random.uniform(0.1, 0.3)
        else:  # Night
            load = base_load + np.random.uniform(-0.1, 0.1)

        afname.append(max(0, load))

        # Solar production: during day, peaking at noon
        if 8 <= hour < 18 and np.random.random() > 0.2:  # Some cloudy intervals
            solar = np.sin((hour - 8) / 10 * np.pi) * np.random.uniform(0.3, 0.8)
            teruglevering.append(max(0, solar))
        else:
            teruglevering.append(0)

    return pd.DataFrame({
        'timestamp': pd.to_datetime(timestamps),
        'afname_kwh': afname,
        'teruglevering_kwh': teruglevering
    })


@pytest.fixture
def sample_battery_config():
    """Create sample battery configuration."""
    return BatteryConfig(
        capacity_kwh=50,
        max_power_kw=25,
        charge_efficiency=0.959,
        discharge_efficiency=0.959,
        min_soc=0.1,
        max_soc=0.9,
        degradation_rate=0.02,
        cycle_life=6000,
        price_per_kwh=450
    )


@pytest.fixture
def sample_tariffs():
    """Create sample tariff structure."""
    return TariffStructure(
        peak_rate=0.35,
        off_peak_rate=0.22,
        peak_hours_start=7,
        peak_hours_end=21,
        capacity_tariff=12.50,
        feed_in_tariff=0.08
    )


@pytest.fixture
def sample_csv_content():
    """Create sample CSV content."""
    return """Datum;Tijd;Afname (kWh);Teruglevering (kWh)
01-01-2024;00:00;0,52;0,00
01-01-2024;00:15;0,48;0,00
01-01-2024;00:30;0,51;0,00
01-01-2024;00:45;0,49;0,00
01-01-2024;01:00;0,47;0,00
01-01-2024;01:15;0,45;0,00
"""
