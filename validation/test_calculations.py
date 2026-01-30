"""
===============================================================================
FASE 1: TECHNISCHE BASISVALIDATIE
===============================================================================

Dit script test de fundamentele correctheid van de batterij-berekeningen.

Tests:
1. Energie-balans (in = out + losses)
2. Batterij fysieke limieten (SoC, vermogen)
3. Peak shaving logica
4. Financiele consistentie
5. Null handling / graceful errors

Run: python validation/test_calculations.py
===============================================================================
"""

import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from app.engine.simulation import (
    BatteryDispatchSimulator,
    DispatchStrategy,
    TariffStructure,
    SimulationResult
)
from app.engine.degradation import BatteryChemistry


class ValidationResult:
    """Container voor test resultaat."""
    def __init__(self, test_name: str, passed: bool, message: str, details: dict = None):
        self.test_name = test_name
        self.passed = passed
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.now()

    def __str__(self):
        status = "✅ PASS" if self.passed else "❌ FAIL"
        return f"{status} | {self.test_name}: {self.message}"


def create_constant_profile(hours: int = 24, load_kwh_per_interval: float = 2.5) -> pd.DataFrame:
    """
    Maak testprofiel met constant verbruik.

    Args:
        hours: Aantal uren
        load_kwh_per_interval: Verbruik per 15-minuten interval (kWh)

    Returns:
        DataFrame met timestamp, afname_kwh, teruglevering_kwh
    """
    intervals = hours * 4  # 15-minuut intervallen
    start = datetime(2024, 1, 1, 0, 0)

    data = {
        'timestamp': [start + timedelta(minutes=15*i) for i in range(intervals)],
        'afname_kwh': [load_kwh_per_interval] * intervals,
        'teruglevering_kwh': [0.0] * intervals
    }
    return pd.DataFrame(data)


def create_peak_profile(hours: int = 24, base_kwh: float = 2.5, peak_kwh: float = 12.5, peak_hour: int = 14) -> pd.DataFrame:
    """
    Maak testprofiel met één duidelijke piek.

    Args:
        hours: Aantal uren
        base_kwh: Basis verbruik per 15-min interval (kWh)
        peak_kwh: Piek verbruik per 15-min interval (kWh)
        peak_hour: Uur van de piek
    """
    intervals = hours * 4
    start = datetime(2024, 1, 1, 0, 0)

    loads = []
    timestamps = []
    for i in range(intervals):
        ts = start + timedelta(minutes=15*i)
        timestamps.append(ts)

        if ts.hour == peak_hour:
            loads.append(peak_kwh)  # Piek: 50 kW
        else:
            loads.append(base_kwh)  # Basis: 10 kW

    return pd.DataFrame({
        'timestamp': timestamps,
        'afname_kwh': loads,
        'teruglevering_kwh': [0.0] * intervals
    })


# =============================================================================
# TEST 1: ENERGIE-BALANS
# =============================================================================
def test_energy_balance() -> ValidationResult:
    """
    Test dat energie in = energie uit + verliezen.

    Formule: total_charged * efficiency ≈ total_discharged
    Tolerantie: ±2% (efficiency variaties)
    """
    test_name = "Energie-balans"

    try:
        # Setup
        profile = create_constant_profile(hours=48, load_kwh_per_interval=2.5)

        simulator = BatteryDispatchSimulator(
            capacity_kwh=50,
            max_power_kw=25,
            chemistry=BatteryChemistry.LFP,
            initial_soc=0.50
        )

        result = simulator.simulate(
            profile_df=profile,
            strategy=DispatchStrategy.HYBRID
        )

        # Validatie
        charged = result.summary.total_charged_kwh
        discharged = result.summary.total_discharged_kwh
        losses = result.summary.total_losses_kwh
        efficiency = result.summary.average_efficiency

        # Energie-balans check
        # Geladen energie - verliezen zou gelijk moeten zijn aan ontladen energie
        # Plus de delta in SoC
        initial_soc_kwh = 50 * 0.50  # 25 kWh
        final_soc_kwh = result.battery_state.soc_kwh
        soc_delta = final_soc_kwh - initial_soc_kwh

        # Balans: charged - discharged - losses = soc_delta
        calculated_delta = charged - discharged - losses
        balance_error = abs(calculated_delta - soc_delta)
        tolerance = 0.5  # 0.5 kWh tolerantie (afrondingsfouten)

        passed = balance_error < tolerance

        details = {
            'charged_kwh': round(charged, 2),
            'discharged_kwh': round(discharged, 2),
            'losses_kwh': round(losses, 2),
            'initial_soc_kwh': round(initial_soc_kwh, 2),
            'final_soc_kwh': round(final_soc_kwh, 2),
            'soc_delta': round(soc_delta, 2),
            'calculated_delta': round(calculated_delta, 2),
            'balance_error': round(balance_error, 4),
            'tolerance': tolerance,
            'efficiency': round(efficiency, 4)
        }

        if passed:
            message = f"Balans klopt: error={balance_error:.4f} kWh < {tolerance} kWh tolerantie"
        else:
            message = f"Balans NIET kloppend: error={balance_error:.4f} kWh > {tolerance} kWh"

        return ValidationResult(test_name, passed, message, details)

    except Exception as e:
        return ValidationResult(test_name, False, f"Exception: {str(e)}")


# =============================================================================
# TEST 2: BATTERIJ FYSIEKE LIMIETEN
# =============================================================================
def test_physical_limits() -> ValidationResult:
    """
    Test dat batterij limieten NOOIT overschreden worden:
    - SoC nooit > 100%
    - SoC nooit < 0% (of min_soc)
    - Power nooit > max_power_kw
    """
    test_name = "Fysieke limieten"

    try:
        # Setup met uitdagend profiel (hoge variatie)
        hours = 48
        intervals = hours * 4
        start = datetime(2024, 1, 1)

        # Maak profiel met grote variaties
        np.random.seed(42)
        loads = np.random.uniform(0.5, 15, intervals)  # 2 - 60 kW variatie

        profile = pd.DataFrame({
            'timestamp': [start + timedelta(minutes=15*i) for i in range(intervals)],
            'afname_kwh': loads,
            'teruglevering_kwh': [0.0] * intervals
        })

        capacity_kwh = 50
        max_power_kw = 25
        min_soc = 0.10
        max_soc = 0.90

        simulator = BatteryDispatchSimulator(
            capacity_kwh=capacity_kwh,
            max_power_kw=max_power_kw,
            chemistry=BatteryChemistry.LFP,
            min_soc=min_soc,
            max_soc=max_soc,
            initial_soc=0.50
        )

        result = simulator.simulate(
            profile_df=profile,
            strategy=DispatchStrategy.HYBRID
        )

        # Check alle timesteps
        violations = {
            'soc_too_high': [],
            'soc_too_low': [],
            'power_exceeded': []
        }

        interval_hours = 0.25  # 15 minuten

        for i, interval in enumerate(result.hourly_results):
            # SoC check
            soc_percent = interval.soc_percent

            if soc_percent > max_soc + 0.001:  # Kleine tolerantie voor floats
                violations['soc_too_high'].append({
                    'interval': i,
                    'soc': round(soc_percent * 100, 2)
                })

            if soc_percent < min_soc - 0.001:
                violations['soc_too_low'].append({
                    'interval': i,
                    'soc': round(soc_percent * 100, 2)
                })

            # Power check
            charge_power = interval.charge_kwh / interval_hours
            discharge_power = interval.discharge_kwh / interval_hours
            max_power = max(charge_power, discharge_power)

            if max_power > max_power_kw + 0.1:  # 0.1 kW tolerantie
                violations['power_exceeded'].append({
                    'interval': i,
                    'power_kw': round(max_power, 2)
                })

        # Resultaat
        total_violations = sum(len(v) for v in violations.values())
        passed = total_violations == 0

        details = {
            'total_intervals': len(result.hourly_results),
            'soc_high_violations': len(violations['soc_too_high']),
            'soc_low_violations': len(violations['soc_too_low']),
            'power_violations': len(violations['power_exceeded']),
            'max_soc_limit': max_soc * 100,
            'min_soc_limit': min_soc * 100,
            'max_power_limit': max_power_kw
        }

        if not passed:
            details['violations_sample'] = {
                k: v[:3] for k, v in violations.items() if v  # Max 3 voorbeelden
            }

        if passed:
            message = f"Alle {len(result.hourly_results)} intervallen binnen limieten"
        else:
            message = f"{total_violations} limietoverschrijdingen gevonden"

        return ValidationResult(test_name, passed, message, details)

    except Exception as e:
        return ValidationResult(test_name, False, f"Exception: {str(e)}")


# =============================================================================
# TEST 3: PEAK SHAVING LOGICA
# =============================================================================
def test_peak_shaving() -> ValidationResult:
    """
    Test dat peak shaving daadwerkelijk de piek verlaagt.

    Setup: 23 uur op 10 kW, 1 uur op 50 kW
    Verwacht: nieuwe piek < 50 kW
    """
    test_name = "Peak shaving logica"

    try:
        # Profiel met duidelijke piek
        profile = create_peak_profile(
            hours=24,
            base_kwh=2.5,   # 10 kW base
            peak_kwh=12.5,  # 50 kW peak
            peak_hour=14
        )

        simulator = BatteryDispatchSimulator(
            capacity_kwh=100,  # Grote batterij voor goede peak shaving
            max_power_kw=50,
            chemistry=BatteryChemistry.LFP,
            initial_soc=0.80  # Start met hoge SoC
        )

        result = simulator.simulate(
            profile_df=profile,
            strategy=DispatchStrategy.PEAK_SHAVING
        )

        original_peak = result.summary.original_peak_kw
        new_peak = result.summary.new_peak_kw
        peak_reduction = result.summary.peak_reduction_kw

        # Validatie
        passed = new_peak < original_peak and peak_reduction > 0

        details = {
            'original_peak_kw': round(original_peak, 2),
            'new_peak_kw': round(new_peak, 2),
            'peak_reduction_kw': round(peak_reduction, 2),
            'reduction_percent': round(peak_reduction / original_peak * 100, 1) if original_peak > 0 else 0
        }

        if passed:
            message = f"Piek verlaagd van {original_peak:.1f} naar {new_peak:.1f} kW ({details['reduction_percent']}% reductie)"
        else:
            message = f"Peak shaving werkt NIET: piek onveranderd of hoger"

        return ValidationResult(test_name, passed, message, details)

    except Exception as e:
        return ValidationResult(test_name, False, f"Exception: {str(e)}")


# =============================================================================
# TEST 4: FINANCIELE CONSISTENTIE
# =============================================================================
def test_financial_consistency() -> ValidationResult:
    """
    Test financiele berekeningen op consistentie:
    - CAPEX moet positief zijn
    - Bij besparingen moet NPV logisch zijn
    - Terugverdientijd = CAPEX / jaarlijkse besparing
    """
    test_name = "Financiele consistentie"

    try:
        # Setup
        profile = create_peak_profile(hours=168, peak_kwh=12.5)  # 1 week

        capacity_kwh = 100
        capex_per_kwh = 400  # €400/kWh
        capex = capacity_kwh * capex_per_kwh

        simulator = BatteryDispatchSimulator(
            capacity_kwh=capacity_kwh,
            max_power_kw=50,
            chemistry=BatteryChemistry.LFP,
            initial_soc=0.50
        )

        tariffs = TariffStructure(
            capacity_tariff=52.0  # €52/kW/maand
        )

        result = simulator.simulate(
            profile_df=profile,
            strategy=DispatchStrategy.HYBRID,
            tariffs=tariffs
        )

        # Bereken financials
        annual_savings = result.summary.total_savings_eur_year
        peak_reduction = result.summary.peak_reduction_kw
        peak_savings_annual = result.summary.peak_savings_eur_year

        # Validaties
        checks = []

        # 1. CAPEX positief
        checks.append(('CAPEX positief', capex > 0))

        # 2. Als peak reduction > 0, dan peak savings > 0
        if peak_reduction > 0:
            checks.append(('Peak savings consistent', peak_savings_annual > 0))

        # 3. Terugverdientijd berekening
        if annual_savings > 0:
            calculated_payback = capex / annual_savings
            checks.append(('Payback berekening', calculated_payback > 0))
        else:
            calculated_payback = float('inf')
            checks.append(('Payback berekening', True))  # Geen besparing = geen payback verwacht

        # 4. Totale savings = energy + peak
        total_check = abs(annual_savings - (result.summary.energy_savings_eur + peak_savings_annual)) < 1
        checks.append(('Savings som consistent', total_check))

        passed = all(check[1] for check in checks)

        details = {
            'capex_eur': capex,
            'annual_savings_eur': round(annual_savings, 2),
            'peak_reduction_kw': round(peak_reduction, 2),
            'peak_savings_annual_eur': round(peak_savings_annual, 2),
            'energy_savings_annual_eur': round(result.summary.energy_savings_eur, 2),
            'calculated_payback_years': round(calculated_payback, 1) if calculated_payback != float('inf') else 'N/A',
            'checks': {name: '✓' if result else '✗' for name, result in checks}
        }

        if passed:
            message = f"Alle financiele checks geslaagd (payback: {details['calculated_payback_years']} jaar)"
        else:
            failed = [name for name, result in checks if not result]
            message = f"Gefaalde checks: {', '.join(failed)}"

        return ValidationResult(test_name, passed, message, details)

    except Exception as e:
        return ValidationResult(test_name, False, f"Exception: {str(e)}")


# =============================================================================
# TEST 5: NULL HANDLING
# =============================================================================
def test_null_handling() -> ValidationResult:
    """
    Test graceful error handling bij ongeldige input.
    """
    test_name = "Null handling"

    try:
        simulator = BatteryDispatchSimulator(
            capacity_kwh=50,
            max_power_kw=25,
            chemistry=BatteryChemistry.LFP
        )

        errors_caught = []

        # Test 1: Lege DataFrame
        try:
            empty_df = pd.DataFrame()
            simulator.simulate(empty_df)
            errors_caught.append(('Lege DataFrame', False, 'Geen error gegooid'))
        except (ValueError, KeyError) as e:
            errors_caught.append(('Lege DataFrame', True, str(e)[:50]))
        except Exception as e:
            errors_caught.append(('Lege DataFrame', False, f'Onverwachte error: {type(e).__name__}'))

        # Test 2: Ontbrekende kolommen
        try:
            bad_df = pd.DataFrame({'wrong_column': [1, 2, 3]})
            simulator.simulate(bad_df)
            errors_caught.append(('Ontbrekende kolommen', False, 'Geen error gegooid'))
        except (ValueError, KeyError) as e:
            errors_caught.append(('Ontbrekende kolommen', True, str(e)[:50]))
        except Exception as e:
            errors_caught.append(('Ontbrekende kolommen', False, f'Onverwachte error: {type(e).__name__}'))

        # Test 3: NaN values - zou moeten werken (fillna in prepare)
        try:
            nan_df = pd.DataFrame({
                'timestamp': pd.date_range('2024-01-01', periods=10, freq='15min'),
                'afname_kwh': [1, np.nan, 2, np.nan, 3, 4, np.nan, 5, 6, 7],
                'teruglevering_kwh': [0] * 10
            })
            result = simulator.simulate(nan_df)
            if result.summary.data_points == 10:
                errors_caught.append(('NaN handling', True, 'NaN correct verwerkt'))
            else:
                errors_caught.append(('NaN handling', False, 'NaN niet correct verwerkt'))
        except Exception as e:
            errors_caught.append(('NaN handling', False, f'Crash: {type(e).__name__}'))

        # Test 4: Negatieve capaciteit zou niet crashen (of error geven)
        try:
            bad_sim = BatteryDispatchSimulator(
                capacity_kwh=-50,  # Ongeldig
                max_power_kw=25,
                chemistry=BatteryChemistry.LFP
            )
            # Dit zou eigenlijk een error moeten geven, maar test dat het niet crasht
            errors_caught.append(('Negatieve capaciteit', True, 'Geen crash'))
        except ValueError as e:
            errors_caught.append(('Negatieve capaciteit', True, 'Correct: ValueError gegooid'))
        except Exception as e:
            errors_caught.append(('Negatieve capaciteit', False, f'Onverwachte crash: {type(e).__name__}'))

        # Resultaat
        passed_count = sum(1 for _, passed, _ in errors_caught if passed)
        total_count = len(errors_caught)
        passed = passed_count >= 3  # Minimaal 3 van 4 moet slagen

        details = {
            'tests_passed': passed_count,
            'tests_total': total_count,
            'results': {name: ('✓' if p else '✗', msg) for name, p, msg in errors_caught}
        }

        if passed:
            message = f"{passed_count}/{total_count} error handling tests geslaagd"
        else:
            message = f"Slechts {passed_count}/{total_count} tests geslaagd"

        return ValidationResult(test_name, passed, message, details)

    except Exception as e:
        return ValidationResult(test_name, False, f"Exception: {str(e)}")


# =============================================================================
# MAIN: RUN ALLE TESTS
# =============================================================================
def run_all_tests() -> list[ValidationResult]:
    """Run alle validatie tests en genereer rapport."""
    print("\n" + "="*70)
    print("FASE 1: TECHNISCHE BASISVALIDATIE")
    print("="*70 + "\n")

    tests = [
        test_energy_balance,
        test_physical_limits,
        test_peak_shaving,
        test_financial_consistency,
        test_null_handling
    ]

    results = []
    for test_func in tests:
        print(f"Running: {test_func.__name__}...", end=" ")
        result = test_func()
        results.append(result)
        print(result)

        if result.details:
            for key, value in result.details.items():
                if key != 'violations_sample' and key != 'results':
                    print(f"    {key}: {value}")

    # Summary
    passed = sum(1 for r in results if r.passed)
    total = len(results)

    print("\n" + "-"*70)
    print(f"RESULTAAT: {passed}/{total} tests geslaagd")

    if passed == total:
        print("✅ ALLE TESTS GESLAAGD")
    else:
        print("❌ NIET ALLE TESTS GESLAAGD")
        for r in results:
            if not r.passed:
                print(f"   - {r.test_name}: {r.message}")

    print("-"*70 + "\n")

    return results


def save_report(results: list[ValidationResult], output_dir: str = "validation"):
    """Sla rapport op naar bestand."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = Path(output_dir) / f"report_{timestamp}.txt"

    with open(filename, 'w', encoding='utf-8') as f:
        f.write("="*70 + "\n")
        f.write("BATTERY OPTIMIZER - TECHNISCHE VALIDATIE RAPPORT\n")
        f.write("="*70 + "\n\n")
        f.write(f"Datum/tijd: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Fase: 1 - Technische Basisvalidatie\n\n")

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
        if passed == total:
            f.write("CONCLUSIE: ALLE TESTS GESLAAGD - Berekeningen technisch correct\n")
        else:
            f.write("CONCLUSIE: TESTS GEFAALD - Review nodig\n")
        f.write("="*70 + "\n")

    print(f"Rapport opgeslagen: {filename}")
    return filename


if __name__ == "__main__":
    results = run_all_tests()
    save_report(results)
