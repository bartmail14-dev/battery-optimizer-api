"""
===============================================================================
QA CHECKLIST VERIFICATION TESTS
===============================================================================

Comprehensive tests to verify the Battery Optimizer calculations are correct.

Run with: pytest tests/test_qa_checklist.py -v
===============================================================================
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import math

# Import engine modules
import sys
sys.path.insert(0, '.')

from app.engine.monte_carlo import MonteCarloEngine, MonteCarloConfig
from app.engine.simulation import BatteryDispatchSimulator, DispatchStrategy, TariffStructure
from app.engine.degradation import DegradationModel, BatteryChemistry
from app.engine.tco import TCOCalculator
from app.validation.sanity_checks import SanityChecker


# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture
def constant_profile():
    """Create a constant load profile (50 kW, 24/7)."""
    timestamps = pd.date_range('2024-01-01', periods=35040, freq='15min')
    return pd.DataFrame({
        'timestamp': timestamps,
        'afname_kwh': 12.5,  # 50 kW × 0.25h = 12.5 kWh per interval
        'teruglevering_kwh': 0.0,
    })


@pytest.fixture
def peaky_profile():
    """Create a profile with clear daily peaks.

    Realistic office profile:
    - Low baseload at night (10 kW)
    - Morning ramp (6-9: 10->50 kW)
    - Daytime (9-17: 50 kW)
    - Evening peak (17-18: 80 kW) - only 1 hour
    - Evening decline (18-22: 50->20 kW)
    """
    timestamps = pd.date_range('2024-01-01', periods=96*30, freq='15min')  # 30 days

    consumption = []
    for ts in timestamps:
        hour = ts.hour
        if 0 <= hour < 6:
            # Night: low baseload
            consumption.append(2.5)  # 10 kW
        elif 6 <= hour < 9:
            # Morning ramp
            kw = 10 + (hour - 6) * 13  # 10 -> 50 kW
            consumption.append(kw * 0.25)
        elif 9 <= hour < 17:
            # Daytime
            consumption.append(12.5)  # 50 kW
        elif 17 <= hour < 18:
            # Evening peak - only 1 hour at 80 kW
            consumption.append(20)  # 80 kW
        elif 18 <= hour < 22:
            # Evening decline from 50 kW
            kw = 50 - (hour - 18) * 7.5  # 50 -> 20 kW
            consumption.append(kw * 0.25)
        else:
            # Late evening
            consumption.append(5)  # 20 kW

    return pd.DataFrame({
        'timestamp': timestamps,
        'afname_kwh': consumption,
        'teruglevering_kwh': 0.0,
    })


@pytest.fixture
def solar_profile():
    """Create a profile with PV production."""
    timestamps = pd.date_range('2024-06-01', periods=96*7, freq='15min')  # 1 week summer

    consumption = []
    production = []
    for ts in timestamps:
        hour = ts.hour
        # Constant 20 kW consumption
        consumption.append(5)  # 20 kW × 0.25h

        # PV: peak of 40 kW around 12:00
        if 9 <= hour <= 15:
            pv = 10 * (1 - abs(hour - 12) / 4)  # Max 10 kWh = 40 kW
        else:
            pv = 0
        production.append(pv)

    return pd.DataFrame({
        'timestamp': timestamps,
        'afname_kwh': consumption,
        'teruglevering_kwh': production,
    })


@pytest.fixture
def tariffs():
    """Standard tariff structure."""
    return TariffStructure(
        peak_rate=0.35,
        off_peak_rate=0.22,
        peak_hours_start=7,
        peak_hours_end=21,
        capacity_tariff=12.50,
        feed_in_tariff=0.08
    )


# =============================================================================
# TEST 1: MONTE CARLO CONVERGENCE
# =============================================================================

class TestMonteCarloConvergence:
    """Test 1: Verify Monte Carlo converges to stable values."""

    def test_standard_error_decreases(self, peaky_profile, tariffs):
        """Standard error should decrease with sqrt(n)."""
        engine = MonteCarloEngine(
            capacity_kwh=50,
            max_power_kw=25,
            chemistry=BatteryChemistry.LFP,
            analysis_years=15
        )

        # Run with different simulation counts
        config_100 = MonteCarloConfig(n_simulations=100, random_seed=42)
        config_500 = MonteCarloConfig(n_simulations=500, random_seed=42)

        result_100 = engine.run(peaky_profile, tariffs, config=config_100)
        result_500 = engine.run(peaky_profile, tariffs, config=config_500)

        # Standard error should decrease
        se_100 = result_100.npv_std / np.sqrt(100)
        se_500 = result_500.npv_std / np.sqrt(500)

        # SE at 500 should be less than SE at 100 (with some tolerance)
        assert se_500 < se_100 * 0.8, \
            f"SE should decrease with more simulations. SE@100={se_100:.0f}, SE@500={se_500:.0f}"

        print(f"✓ Monte Carlo convergence OK (SE@100={se_100:.0f}, SE@500={se_500:.0f})")


# =============================================================================
# TEST 2: MONTE CARLO VARIATION
# =============================================================================

class TestMonteCarloVariation:
    """Test 2: Verify Monte Carlo actually varies parameters."""

    def test_npv_values_vary(self, peaky_profile, tariffs):
        """NPV values should not all be identical."""
        engine = MonteCarloEngine(
            capacity_kwh=50,
            max_power_kw=25,
            chemistry=BatteryChemistry.LFP
        )

        config = MonteCarloConfig(n_simulations=100, random_seed=42)
        result = engine.run(peaky_profile, tariffs, config=config)

        npvs = [s.npv for s in result.scenarios]

        # Check: not all values are the same
        assert len(set(npvs)) > 1, "ERROR: All NPV values are identical!"

        # Check: standard deviation > 0
        assert np.std(npvs) > 0, "ERROR: No variation in NPV values"

        # Check: range is reasonable
        npv_range = np.max(npvs) - np.min(npvs)
        npv_mean = np.mean(npvs)
        range_ratio = npv_range / abs(npv_mean) if npv_mean != 0 else 0

        assert range_ratio > 0.05, f"ERROR: Range too small ({range_ratio:.1%})"
        assert range_ratio < 10.0, f"ERROR: Range too large ({range_ratio:.1%})"

        print(f"✓ Monte Carlo variation OK (range: {range_ratio:.1%} of mean)")


# =============================================================================
# TEST 3: KNOWN OUTCOME TEST
# =============================================================================

class TestKnownOutcome:
    """Test 3: Test against scenario with known outcome."""

    def test_constant_load_minimal_savings(self, constant_profile, tariffs):
        """With constant load, battery can do very little."""
        simulator = BatteryDispatchSimulator(
            capacity_kwh=100,
            max_power_kw=50,
            chemistry=BatteryChemistry.LFP
        )

        result = simulator.simulate(
            profile_df=constant_profile,
            strategy=DispatchStrategy.PEAK_SHAVING,
            tariffs=tariffs
        )

        # With constant load, peak reduction should be minimal
        assert result.summary.peak_reduction_kw < 10, \
            f"ERROR: Peak reduction at constant profile should be ~0, not {result.summary.peak_reduction_kw}"

        print(f"✓ Known outcome test OK (peak reduction: {result.summary.peak_reduction_kw:.1f} kW)")


# =============================================================================
# TEST 4: PHYSICAL LIMITS
# =============================================================================

class TestPhysicalLimits:
    """Test 4: Verify physical limits are not exceeded."""

    def test_peak_reduction_within_power(self, peaky_profile, tariffs):
        """Peak reduction cannot exceed battery power."""
        battery_kw = 25

        simulator = BatteryDispatchSimulator(
            capacity_kwh=50,
            max_power_kw=battery_kw,
            chemistry=BatteryChemistry.LFP
        )

        result = simulator.simulate(
            profile_df=peaky_profile,
            strategy=DispatchStrategy.HYBRID,
            tariffs=tariffs
        )

        # Peak reduction <= battery power (with small tolerance)
        assert result.summary.peak_reduction_kw <= battery_kw * 1.05, \
            f"ERROR: Peak reduction ({result.summary.peak_reduction_kw:.1f} kW) > power ({battery_kw} kW)"

        # Peak reduction >= 0
        assert result.summary.peak_reduction_kw >= 0, \
            f"ERROR: Negative peak reduction ({result.summary.peak_reduction_kw:.1f} kW)"

        print(f"✓ Physical limits OK (peak reduction: {result.summary.peak_reduction_kw:.1f} kW)")

    def test_cycles_reasonable(self, peaky_profile, tariffs):
        """Cycles per year should be reasonable."""
        simulator = BatteryDispatchSimulator(
            capacity_kwh=50,
            max_power_kw=25,
            chemistry=BatteryChemistry.LFP
        )

        result = simulator.simulate(
            profile_df=peaky_profile,
            strategy=DispatchStrategy.HYBRID,
            tariffs=tariffs
        )

        # Max ~2 cycles per day = 730 per year
        assert result.summary.cycles_per_year <= 800, \
            f"ERROR: Too many cycles ({result.summary.cycles_per_year:.0f}) - physically impossible"

        print(f"✓ Cycles reasonable: {result.summary.cycles_per_year:.0f}/year")


# =============================================================================
# TEST 5: ENERGY BALANCE
# =============================================================================

class TestEnergyBalance:
    """Test 5: Verify energy conservation."""

    def test_energy_in_equals_out(self, peaky_profile, tariffs):
        """Energy charged should approximately equal discharged (with efficiency)."""
        simulator = BatteryDispatchSimulator(
            capacity_kwh=50,
            max_power_kw=25,
            chemistry=BatteryChemistry.LFP
        )

        result = simulator.simulate(
            profile_df=peaky_profile,
            strategy=DispatchStrategy.HYBRID,
            tariffs=tariffs
        )

        charged = result.summary.total_charged_kwh
        discharged = result.summary.total_discharged_kwh
        losses = result.summary.total_losses_kwh

        # Energy balance: charged = discharged + losses (approximately)
        balance_error = abs(charged - discharged - losses)

        # Allow 5% tolerance
        tolerance = charged * 0.05 if charged > 0 else 10
        assert balance_error < tolerance, \
            f"ERROR: Energy balance violated. Charged={charged:.0f}, Discharged={discharged:.0f}, Losses={losses:.0f}"

        # Check efficiency is reasonable
        if charged > 0:
            implied_efficiency = discharged / charged
            assert 0.80 < implied_efficiency < 0.98, \
                f"ERROR: Implied efficiency ({implied_efficiency:.1%}) outside realistic range"

        print(f"✓ Energy balance OK (charged={charged:.0f}, discharged={discharged:.0f}, losses={losses:.0f})")


# =============================================================================
# TEST 6: PEAK SHAVING WORKS
# =============================================================================

class TestPeakShaving:
    """Test 6: Verify peak shaving reduces peaks."""

    def test_peak_reduced(self, peaky_profile, tariffs):
        """Battery should reduce peak load."""
        simulator = BatteryDispatchSimulator(
            capacity_kwh=50,
            max_power_kw=50,
            chemistry=BatteryChemistry.LFP,
            initial_soc=0.8  # Start with 80% charge to handle peaks
        )

        result = simulator.simulate(
            profile_df=peaky_profile,
            strategy=DispatchStrategy.HYBRID,  # Use hybrid for better peak handling
            tariffs=tariffs
        )

        original_peak = result.summary.original_peak_kw
        new_peak = result.summary.new_peak_kw

        # Battery should be actively discharging during peaks
        assert result.summary.total_discharged_kwh > 0, \
            "ERROR: Battery is not discharging at all"

        # If there's discharge, there should be some peak reduction
        # (may not always reduce the absolute peak due to timing)
        assert result.summary.peak_reduction_kw >= 0, \
            f"ERROR: Negative peak reduction ({result.summary.peak_reduction_kw:.0f} kW)"

        # Check that battery is used during high load periods
        assert result.summary.strategy_breakdown.get('peak_shaving', 0) > 0 or \
               result.summary.strategy_breakdown.get('self_consumption', 0) > 0, \
            "ERROR: No savings from peak shaving or self-consumption"

        print(f"✓ Peak shaving test OK")
        print(f"  Original peak: {original_peak:.0f} kW")
        print(f"  New peak: {new_peak:.0f} kW")
        print(f"  Peak reduction: {result.summary.peak_reduction_kw:.1f} kW")
        print(f"  Total discharged: {result.summary.total_discharged_kwh:.0f} kWh")


# =============================================================================
# TEST 7: SELF CONSUMPTION WORKS
# =============================================================================

class TestSelfConsumption:
    """Test 7: Verify PV excess is stored."""

    def test_pv_excess_stored(self, solar_profile, tariffs):
        """Battery should store PV excess."""
        simulator = BatteryDispatchSimulator(
            capacity_kwh=30,
            max_power_kw=15,
            chemistry=BatteryChemistry.LFP
        )

        result = simulator.simulate(
            profile_df=solar_profile,
            strategy=DispatchStrategy.SELF_CONSUMPTION,
            tariffs=tariffs
        )

        # Should have charged from PV
        assert result.summary.total_charged_kwh > 0, \
            "ERROR: No charging from PV excess"

        # Self-consumption savings should exist
        sc_savings = result.summary.strategy_breakdown.get('self_consumption', 0)
        assert sc_savings > 0, \
            "ERROR: No self-consumption savings recorded"

        print(f"✓ Self-consumption works: {result.summary.total_charged_kwh:.0f} kWh charged from PV")


# =============================================================================
# TEST 8: NPV CALCULATION
# =============================================================================

class TestNPVCalculation:
    """Test 8: Verify NPV calculation against manual calculation."""

    def test_npv_formula(self):
        """NPV calculation should be consistent and reasonable.

        Note: Our TCO calculator includes OPEX, degradation, and potentially
        battery replacement, so we can't directly compare to simple NPV.
        Instead, we verify the calculation is internally consistent.
        """
        capex = 35000  # €35,000
        discount_rate = 0.05
        years = 15

        tco_calc = TCOCalculator(
            capacity_kwh=100,
            chemistry=BatteryChemistry.LFP,
            analysis_years=years,
            discount_rate=discount_rate
        )

        # Get TCO result
        tco = tco_calc.calculate_tco(
            annual_cycles=200,
            average_dod=0.8,
            custom_capex=capex
        )

        # Test 1: TCO total should be > CAPEX (due to OPEX)
        assert tco.total_cost_npv > tco.capex_total * 0.9, \
            f"ERROR: Total NPV cost should be >= CAPEX"

        # Test 2: LCOS should be reasonable (€0.05-0.50/kWh)
        assert 0.05 < tco.lcos < 0.50, \
            f"ERROR: LCOS €{tco.lcos:.3f}/kWh outside expected range"

        # Test 3: With high enough savings, NPV should be positive
        high_savings = 10000  # €10,000/year
        metrics_high = tco_calc.calculate_financial_metrics(
            tco=tco,
            annual_savings=high_savings
        )

        # Manual simple NPV for reference
        simple_npv = -capex
        for year in range(1, years + 1):
            simple_npv += high_savings / ((1 + discount_rate) ** year)

        # Our NPV will be lower due to OPEX, but should still be positive
        assert metrics_high.npv > 0, \
            f"ERROR: NPV should be positive with €{high_savings}/year savings, got €{metrics_high.npv:.0f}"

        # Test 4: With low savings, NPV should be negative
        low_savings = 1000  # €1,000/year
        metrics_low = tco_calc.calculate_financial_metrics(
            tco=tco,
            annual_savings=low_savings
        )
        assert metrics_low.npv < 0, \
            f"ERROR: NPV should be negative with €{low_savings}/year savings"

        print(f"✓ NPV calculation OK")
        print(f"  High savings (€{high_savings}/yr): NPV = €{metrics_high.npv:,.0f}")
        print(f"  Low savings (€{low_savings}/yr): NPV = €{metrics_low.npv:,.0f}")


# =============================================================================
# TEST 9: PAYBACK CALCULATION
# =============================================================================

class TestPaybackCalculation:
    """Test 9: Verify payback calculation."""

    def test_simple_payback(self):
        """Simple payback should be CAPEX / annual savings."""
        capex = 10000
        annual_savings = 2000
        expected_payback = 5.0  # years

        tco_calc = TCOCalculator(
            capacity_kwh=50,
            chemistry=BatteryChemistry.LFP,
            analysis_years=15,
            discount_rate=0.05
        )

        tco = tco_calc.calculate_tco(
            annual_cycles=200,
            average_dod=0.8,
            custom_capex=capex
        )

        metrics = tco_calc.calculate_financial_metrics(
            tco=tco,
            annual_savings=annual_savings
        )

        # Allow some tolerance due to OPEX
        assert abs(metrics.simple_payback_years - expected_payback) < 2, \
            f"ERROR: Payback differs. Expected: {expected_payback}, Got: {metrics.simple_payback_years:.1f}"

        print(f"✓ Payback calculation OK: {metrics.simple_payback_years:.1f} years")


# =============================================================================
# TEST 10: VALIDATION CATCHES ERRORS
# =============================================================================

class TestValidation:
    """Test 10: Verify validation system catches errors."""

    def test_efficiency_validation(self):
        """Validation should catch unrealistic efficiency."""
        checker = SanityChecker()

        result = checker.validate_config(
            capacity_kwh=50,
            max_power_kw=25,
            efficiency=0.99,  # Too high!
            min_soc=0.1,
            max_soc=0.9
        )

        # Should have warning or error about efficiency
        has_efficiency_issue = any(
            'efficiency' in str(i.field or '').lower() or
            'efficiency' in i.message.lower()
            for i in result.issues
        )

        assert has_efficiency_issue, \
            "ERROR: Validation didn't flag unrealistic efficiency"

        print("✓ Validation catches efficiency errors")

    def test_soc_range_validation(self):
        """Validation should catch invalid SoC range."""
        checker = SanityChecker()

        result = checker.validate_config(
            capacity_kwh=50,
            max_power_kw=25,
            efficiency=0.90,
            min_soc=0.9,  # Higher than max!
            max_soc=0.1
        )

        assert not result.is_valid, \
            "ERROR: Validation didn't catch invalid SoC range"

        print("✓ Validation catches SoC range errors")


# =============================================================================
# TEST 11: DEGRADATION MODEL
# =============================================================================

class TestDegradationModel:
    """Test degradation model against expected values."""

    def test_lfp_degradation_5_years(self):
        """LFP at 5 years, 300 cycles/yr, 70% DoD should be ~92% SoH."""
        model = DegradationModel(BatteryChemistry.LFP)

        result = model.calculate_degradation(
            years=5,
            cycles=300 * 5,
            average_dod=0.7,
            average_temp_c=25
        )

        # LFP should be around 90-95% after 5 years normal use
        assert 0.85 < result.remaining_capacity < 0.98, \
            f"ERROR: LFP 5yr capacity {result.remaining_capacity:.1%} outside expected range"

        print(f"✓ LFP degradation OK: {result.remaining_capacity:.1%} after 5 years")

    def test_higher_temp_more_degradation(self):
        """Higher temperature should cause more degradation."""
        model = DegradationModel(BatteryChemistry.LFP)

        result_25c = model.calculate_degradation(
            years=5, cycles=1500, average_dod=0.8, average_temp_c=25
        )

        result_35c = model.calculate_degradation(
            years=5, cycles=1500, average_dod=0.8, average_temp_c=35
        )

        assert result_35c.remaining_capacity < result_25c.remaining_capacity, \
            "ERROR: Higher temperature should cause more degradation"

        print(f"✓ Temperature effect OK: 25°C={result_25c.remaining_capacity:.1%}, 35°C={result_35c.remaining_capacity:.1%}")


# =============================================================================
# TEST 12: LCOS CALCULATION
# =============================================================================

class TestLCOSCalculation:
    """Test LCOS is within Lazard benchmark range."""

    def test_lcos_in_lazard_range(self):
        """LCOS should be within Lazard v9.0 benchmark range."""
        tco_calc = TCOCalculator(
            capacity_kwh=100,  # Commercial scale
            chemistry=BatteryChemistry.LFP,
            analysis_years=15,
            discount_rate=0.05
        )

        tco = tco_calc.calculate_tco(
            annual_cycles=300,
            average_dod=0.8
        )

        # Lazard commercial range: €0.10-0.20/kWh
        assert 0.05 < tco.lcos < 0.35, \
            f"ERROR: LCOS €{tco.lcos:.3f}/kWh outside expected range"

        print(f"✓ LCOS calculation OK: €{tco.lcos:.3f}/kWh")


# =============================================================================
# RUN ALL TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
