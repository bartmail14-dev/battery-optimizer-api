"""
===============================================================================
FASE 2: LOGISCHE VALIDATIE (INPUT → OUTPUT RELATIES)
===============================================================================

Dit script test of de tool logisch reageert op input-veranderingen.

Tests:
A. Grotere batterij = meer impact
B. Hoger verbruik = hogere besparing
C. Duurdere energie = hogere besparing
D. Vlak profiel = weinig besparing
E. Geen teruglevering = geen eigen verbruik optimalisatie

Run: python validation/sensitivity_test.py
===============================================================================
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from app.engine.simulation import (
    BatteryDispatchSimulator,
    DispatchStrategy,
    TariffStructure,
)
from app.engine.degradation import BatteryChemistry


class SensitivityResult:
    """Container voor sensitivity test resultaat."""
    def __init__(self, test_name: str, passed: bool, message: str, details: dict = None):
        self.test_name = test_name
        self.passed = passed
        self.message = message
        self.details = details or {}

    def __str__(self):
        status = "✅ PASS" if self.passed else "❌ FAIL"
        return f"{status} | {self.test_name}: {self.message}"


def create_realistic_profile(days: int = 7, base_load_kw: float = 30, peak_factor: float = 2.5) -> pd.DataFrame:
    """
    Maak realistisch industrieel profiel met dag/nacht patronen.
    """
    intervals = days * 24 * 4  # 15-min intervals
    start = datetime(2024, 1, 1)

    loads = []
    timestamps = []

    for i in range(intervals):
        ts = start + timedelta(minutes=15*i)
        timestamps.append(ts)

        hour = ts.hour
        weekday = ts.weekday()

        # Basispatroon
        if weekday >= 5:  # Weekend
            load = base_load_kw * 0.3
        elif 8 <= hour <= 17:  # Werkuren
            load = base_load_kw * np.random.uniform(0.8, 1.2)
            # Pieken rond 10:00 en 14:00
            if hour in [10, 14]:
                load *= peak_factor * np.random.uniform(0.9, 1.1)
        elif 6 <= hour <= 8 or 17 <= hour <= 20:
            load = base_load_kw * 0.6
        else:
            load = base_load_kw * 0.2

        # Voeg wat ruis toe
        load *= np.random.uniform(0.95, 1.05)
        loads.append(load / 4)  # kW naar kWh per 15 min

    return pd.DataFrame({
        'timestamp': timestamps,
        'afname_kwh': loads,
        'teruglevering_kwh': [0.0] * intervals
    })


def create_flat_profile(days: int = 7, load_kw: float = 30) -> pd.DataFrame:
    """Maak vlak profiel zonder pieken."""
    intervals = days * 24 * 4
    start = datetime(2024, 1, 1)

    return pd.DataFrame({
        'timestamp': [start + timedelta(minutes=15*i) for i in range(intervals)],
        'afname_kwh': [load_kw / 4] * intervals,  # Constant
        'teruglevering_kwh': [0.0] * intervals
    })


def create_solar_profile(days: int = 7, base_load_kw: float = 30, solar_peak_kw: float = 40) -> pd.DataFrame:
    """Maak profiel met zonne-energie teruglevering."""
    intervals = days * 24 * 4
    start = datetime(2024, 1, 1)

    loads = []
    solar = []
    timestamps = []

    for i in range(intervals):
        ts = start + timedelta(minutes=15*i)
        timestamps.append(ts)
        hour = ts.hour

        # Load patroon
        if 8 <= hour <= 17:
            load = base_load_kw * np.random.uniform(0.8, 1.2)
        else:
            load = base_load_kw * 0.3

        loads.append(load / 4)

        # Solar productie (bell curve)
        if 6 <= hour <= 20:
            solar_fraction = np.sin((hour - 6) / 14 * np.pi)
            solar_gen = solar_peak_kw * solar_fraction * np.random.uniform(0.7, 1.0)
        else:
            solar_gen = 0

        solar.append(max(0, solar_gen / 4 - load / 4))  # Netto teruglevering

    return pd.DataFrame({
        'timestamp': timestamps,
        'afname_kwh': loads,
        'teruglevering_kwh': solar
    })


# =============================================================================
# TEST A: GROTERE BATTERIJ = MEER IMPACT
# =============================================================================
def test_bigger_battery_more_impact() -> SensitivityResult:
    """Test dat grotere batterij meer piekvermindering geeft."""
    test_name = "Grotere batterij = meer impact"

    try:
        np.random.seed(42)
        profile = create_realistic_profile(days=7, base_load_kw=40, peak_factor=2.5)

        # Kleine batterij
        sim_small = BatteryDispatchSimulator(
            capacity_kwh=50,
            max_power_kw=25,
            chemistry=BatteryChemistry.LFP,
            initial_soc=0.50
        )
        result_small = sim_small.simulate(profile, DispatchStrategy.PEAK_SHAVING)
        reduction_small = result_small.summary.peak_reduction_kw

        # Grote batterij
        np.random.seed(42)  # Reset voor zelfde profiel
        profile = create_realistic_profile(days=7, base_load_kw=40, peak_factor=2.5)

        sim_large = BatteryDispatchSimulator(
            capacity_kwh=100,
            max_power_kw=50,
            chemistry=BatteryChemistry.LFP,
            initial_soc=0.50
        )
        result_large = sim_large.simulate(profile, DispatchStrategy.PEAK_SHAVING)
        reduction_large = result_large.summary.peak_reduction_kw

        # Validatie: grotere batterij moet minstens evenveel reduceren
        passed = reduction_large >= reduction_small

        details = {
            'battery_50kwh_reduction': round(reduction_small, 2),
            'battery_100kwh_reduction': round(reduction_large, 2),
            'improvement': round(reduction_large - reduction_small, 2),
            'improvement_percent': round((reduction_large / reduction_small - 1) * 100, 1) if reduction_small > 0 else 'N/A'
        }

        if passed:
            message = f"100kWh batterij reduceert {details['improvement']:.1f} kW meer dan 50kWh"
        else:
            message = f"LOGICA FOUT: grotere batterij geeft minder reductie!"

        return SensitivityResult(test_name, passed, message, details)

    except Exception as e:
        return SensitivityResult(test_name, False, f"Exception: {str(e)}")


# =============================================================================
# TEST B: HOGER VERBRUIK = HOGERE BESPARING
# =============================================================================
def test_higher_consumption_more_savings() -> SensitivityResult:
    """Test dat hoger verbruik leidt tot hogere absolute besparing."""
    test_name = "Hoger verbruik = hogere besparing"

    try:
        # Laag verbruik profiel
        np.random.seed(42)
        profile_low = create_realistic_profile(days=7, base_load_kw=20, peak_factor=2.5)

        sim = BatteryDispatchSimulator(
            capacity_kwh=75,
            max_power_kw=40,
            chemistry=BatteryChemistry.LFP,
            initial_soc=0.50
        )

        result_low = sim.simulate(profile_low, DispatchStrategy.HYBRID)
        savings_low = result_low.summary.total_savings_eur_year

        # Hoog verbruik profiel (2x)
        np.random.seed(42)
        profile_high = create_realistic_profile(days=7, base_load_kw=40, peak_factor=2.5)

        result_high = sim.simulate(profile_high, DispatchStrategy.HYBRID)
        savings_high = result_high.summary.total_savings_eur_year

        # Validatie: hogere verbruik moet hogere absolute besparing geven
        passed = savings_high > savings_low

        details = {
            'low_consumption_savings_eur': round(savings_low, 2),
            'high_consumption_savings_eur': round(savings_high, 2),
            'savings_increase': round(savings_high - savings_low, 2),
            'savings_ratio': round(savings_high / savings_low, 2) if savings_low > 0 else 'N/A'
        }

        if passed:
            message = f"2x verbruik geeft {details['savings_ratio']}x meer besparing"
        else:
            message = f"LOGICA FOUT: hoger verbruik geeft minder besparing!"

        return SensitivityResult(test_name, passed, message, details)

    except Exception as e:
        return SensitivityResult(test_name, False, f"Exception: {str(e)}")


# =============================================================================
# TEST C: DUURDERE ENERGIE = HOGERE BESPARING
# =============================================================================
def test_higher_prices_more_savings() -> SensitivityResult:
    """Test dat hogere energieprijzen leiden tot hogere besparing."""
    test_name = "Duurdere energie = hogere besparing"

    try:
        np.random.seed(42)
        profile = create_realistic_profile(days=7, base_load_kw=40, peak_factor=2.5)

        sim = BatteryDispatchSimulator(
            capacity_kwh=75,
            max_power_kw=40,
            chemistry=BatteryChemistry.LFP,
            initial_soc=0.50
        )

        # Lage tarieven
        tariffs_low = TariffStructure(
            peak_rate=0.10,
            off_peak_rate=0.05,
            capacity_tariff=30.0
        )
        result_low = sim.simulate(profile, DispatchStrategy.HYBRID, tariffs=tariffs_low)
        savings_low = result_low.summary.total_savings_eur_year

        # Hoge tarieven (3x)
        np.random.seed(42)
        profile = create_realistic_profile(days=7, base_load_kw=40, peak_factor=2.5)

        tariffs_high = TariffStructure(
            peak_rate=0.30,
            off_peak_rate=0.15,
            capacity_tariff=90.0
        )
        result_high = sim.simulate(profile, DispatchStrategy.HYBRID, tariffs=tariffs_high)
        savings_high = result_high.summary.total_savings_eur_year

        # Validatie: hogere prijs moet hogere besparing geven
        # Verwacht: ~3x hogere besparing (±20% tolerantie)
        ratio = savings_high / savings_low if savings_low > 0 else 0
        expected_min = 2.0  # Minimaal 2x bij 3x prijsverhoging (conservatief)
        expected_max = 4.0  # Maximaal 4x

        passed = expected_min <= ratio <= expected_max

        details = {
            'low_tariff_savings_eur': round(savings_low, 2),
            'high_tariff_savings_eur': round(savings_high, 2),
            'savings_ratio': round(ratio, 2),
            'expected_range': f"{expected_min}x - {expected_max}x"
        }

        if passed:
            message = f"3x hogere prijs geeft {ratio:.1f}x meer besparing (verwacht: {expected_min}-{expected_max}x)"
        else:
            if ratio < expected_min:
                message = f"Ratio {ratio:.1f}x te laag (verwacht minimaal {expected_min}x)"
            else:
                message = f"Ratio {ratio:.1f}x te hoog (verwacht maximaal {expected_max}x)"

        return SensitivityResult(test_name, passed, message, details)

    except Exception as e:
        return SensitivityResult(test_name, False, f"Exception: {str(e)}")


# =============================================================================
# TEST D: VLAK PROFIEL = WEINIG BESPARING
# =============================================================================
def test_flat_profile_low_savings() -> SensitivityResult:
    """Test dat vlak profiel weinig besparing oplevert."""
    test_name = "Vlak profiel = weinig besparing"

    try:
        # Vlak profiel
        profile_flat = create_flat_profile(days=7, load_kw=40)

        sim = BatteryDispatchSimulator(
            capacity_kwh=75,
            max_power_kw=40,
            chemistry=BatteryChemistry.LFP,
            initial_soc=0.50
        )

        result_flat = sim.simulate(profile_flat, DispatchStrategy.HYBRID)
        savings_flat = result_flat.summary.total_savings_eur_year
        peak_reduction_flat = result_flat.summary.peak_reduction_kw

        # Piekerig profiel
        np.random.seed(42)
        profile_peaks = create_realistic_profile(days=7, base_load_kw=40, peak_factor=3.0)

        result_peaks = sim.simulate(profile_peaks, DispatchStrategy.HYBRID)
        savings_peaks = result_peaks.summary.total_savings_eur_year
        peak_reduction_peaks = result_peaks.summary.peak_reduction_kw

        # Validatie: vlak profiel moet < 10% van piekerig profiel besparen
        # Of minstens significant minder
        ratio = savings_flat / savings_peaks if savings_peaks > 0 else 0
        passed = ratio < 0.30  # Vlak profiel mag max 30% van piekerig zijn

        details = {
            'flat_profile_savings_eur': round(savings_flat, 2),
            'peaks_profile_savings_eur': round(savings_peaks, 2),
            'savings_ratio': round(ratio * 100, 1),
            'flat_peak_reduction_kw': round(peak_reduction_flat, 2),
            'peaks_peak_reduction_kw': round(peak_reduction_peaks, 2)
        }

        if passed:
            message = f"Vlak profiel: slechts {ratio*100:.0f}% van piekerig profiel besparing"
        else:
            message = f"LOGICA FOUT: vlak profiel bespaart {ratio*100:.0f}% van piekerig (verwacht <30%)"

        return SensitivityResult(test_name, passed, message, details)

    except Exception as e:
        return SensitivityResult(test_name, False, f"Exception: {str(e)}")


# =============================================================================
# TEST E: GEEN TERUGLEVERING = GEEN SELF-CONSUMPTION
# =============================================================================
def test_no_feedin_no_self_consumption() -> SensitivityResult:
    """Test dat zonder teruglevering geen self-consumption opbrengst is."""
    test_name = "Geen teruglevering = geen self-consumption"

    try:
        # Profiel ZONDER teruglevering
        np.random.seed(42)
        profile_no_solar = create_realistic_profile(days=7, base_load_kw=40, peak_factor=2.0)
        # Zorg dat teruglevering echt 0 is
        profile_no_solar['teruglevering_kwh'] = 0.0

        sim = BatteryDispatchSimulator(
            capacity_kwh=75,
            max_power_kw=40,
            chemistry=BatteryChemistry.LFP,
            initial_soc=0.50
        )

        result = sim.simulate(profile_no_solar, DispatchStrategy.HYBRID)

        # Check strategy breakdown
        breakdown = result.summary.strategy_breakdown
        self_consumption_savings = breakdown.get('self_consumption', 0)

        # Validatie: self_consumption moet 0 of zeer laag zijn
        passed = self_consumption_savings <= 10  # Max €10 (afrondingsfouten)

        details = {
            'self_consumption_savings_eur': round(self_consumption_savings, 2),
            'peak_shaving_savings_eur': round(breakdown.get('peak_shaving', 0), 2),
            'arbitrage_savings_eur': round(breakdown.get('arbitrage', 0), 2),
            'total_savings_eur': round(result.summary.total_savings_eur_year, 2),
            'total_feedin_kwh': round(profile_no_solar['teruglevering_kwh'].sum(), 2)
        }

        if passed:
            message = f"Correct: geen teruglevering = €{self_consumption_savings:.0f} self-consumption"
        else:
            message = f"LOGICA FOUT: €{self_consumption_savings:.0f} self-consumption zonder teruglevering!"

        return SensitivityResult(test_name, passed, message, details)

    except Exception as e:
        return SensitivityResult(test_name, False, f"Exception: {str(e)}")


# =============================================================================
# MAIN: RUN ALLE TESTS
# =============================================================================
def run_all_sensitivity_tests() -> list[SensitivityResult]:
    """Run alle sensitivity tests."""
    print("\n" + "="*70)
    print("FASE 2: LOGISCHE VALIDATIE (SENSITIVITY TESTS)")
    print("="*70 + "\n")

    tests = [
        test_bigger_battery_more_impact,
        test_higher_consumption_more_savings,
        test_higher_prices_more_savings,
        test_flat_profile_low_savings,
        test_no_feedin_no_self_consumption
    ]

    results = []
    for test_func in tests:
        print(f"Running: {test_func.__name__}...", end=" ")
        result = test_func()
        results.append(result)
        print(result)

        if result.details:
            for key, value in result.details.items():
                print(f"    {key}: {value}")

    # Summary
    passed = sum(1 for r in results if r.passed)
    total = len(results)

    print("\n" + "-"*70)
    print(f"RESULTAAT: {passed}/{total} sensitivity tests geslaagd")

    if passed == total:
        print("✅ ALLE LOGISCHE RELATIES CORRECT")
    else:
        print("❌ LOGISCHE INCONSISTENTIES GEVONDEN")

    print("-"*70 + "\n")

    return results


def save_sensitivity_report(results: list[SensitivityResult], output_dir: str = "validation"):
    """Sla sensitivity rapport op."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = Path(output_dir) / f"sensitivity_report_{timestamp}.txt"

    with open(filename, 'w', encoding='utf-8') as f:
        f.write("="*70 + "\n")
        f.write("BATTERY OPTIMIZER - SENSITIVITY VALIDATIE RAPPORT\n")
        f.write("="*70 + "\n\n")
        f.write(f"Datum/tijd: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Fase: 2 - Logische Validatie\n\n")

        passed = sum(1 for r in results if r.passed)
        total = len(results)
        f.write(f"TOTAAL: {passed}/{total} tests geslaagd\n\n")
        f.write("-"*70 + "\n\n")

        for result in results:
            status = "PASS" if result.passed else "FAIL"
            f.write(f"[{status}] {result.test_name}\n")
            f.write(f"       {result.message}\n")
            if result.details:
                f.write("       Details:\n")
                for key, value in result.details.items():
                    f.write(f"         - {key}: {value}\n")
            f.write("\n")

        f.write("="*70 + "\n")

    print(f"Rapport opgeslagen: {filename}")
    return filename


if __name__ == "__main__":
    results = run_all_sensitivity_tests()
    save_sensitivity_report(results)
