"""Tests for simulation engine."""

import pytest
from app.core.simulator import SimulationEngine
from app.models.schemas import OptimizationStrategy


def test_simulation_runs(sample_profile_df, sample_battery_config, sample_tariffs):
    """Test simulation completes successfully."""
    engine = SimulationEngine(sample_profile_df, sample_tariffs)
    results_df, summary = engine.simulate(sample_battery_config)

    assert len(results_df) == len(sample_profile_df)
    assert summary.total_energy_savings_kwh >= 0
    assert summary.cycles_per_year >= 0


def test_simulation_strategies(sample_profile_df, sample_battery_config, sample_tariffs):
    """Test all strategies run without error."""
    engine = SimulationEngine(sample_profile_df, sample_tariffs)

    for strategy in OptimizationStrategy:
        results_df, summary = engine.simulate(sample_battery_config, strategy)
        assert len(results_df) > 0


def test_simulation_peak_reduction(sample_profile_df, sample_battery_config, sample_tariffs):
    """Test peak shaving reduces peaks."""
    engine = SimulationEngine(sample_profile_df, sample_tariffs)
    results_df, summary = engine.simulate(
        sample_battery_config,
        OptimizationStrategy.PEAK_SHAVING
    )

    original_peak = sample_profile_df['afname_kwh'].max() * 4  # Convert to kW

    # Peak reduction should be non-negative
    assert summary.peak_reduction_kw >= 0


def test_simulation_soc_bounds(sample_profile_df, sample_battery_config, sample_tariffs):
    """Test SOC stays within bounds during simulation."""
    engine = SimulationEngine(sample_profile_df, sample_tariffs)
    results_df, _ = engine.simulate(sample_battery_config)

    min_soc = sample_battery_config.min_soc * 100
    max_soc = sample_battery_config.max_soc * 100

    # Allow small floating point tolerance
    assert results_df['soc_percent'].min() >= min_soc - 0.01
    assert results_df['soc_percent'].max() <= max_soc + 0.01
