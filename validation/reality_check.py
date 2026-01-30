"""
===============================================================================
FASE 3: REALISME-CHECK TEGEN BEKENDE WAARDEN
===============================================================================

Dit script controleert of uitkomsten binnen realistische industrie-bandbreedtes
vallen.

Benchmarks gebaseerd op:
- BloombergNEF Battery Price Survey 2024
- IRENA Electricity Storage Report
- Nederlandse marktdata (Enexis, TenneT)

Run: python validation/reality_check.py
===============================================================================
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from app.engine.simulation import (
    BatteryDispatchSimulator,
    DispatchStrategy,
    TariffStructure,
)
from app.engine.degradation import BatteryChemistry


class CheckStatus(Enum):
    GREEN = "🟢 GROEN"
    ORANGE = "🟠 ORANJE"
    RED = "🔴 ROOD"


class RealityCheck:
    """Container voor reality check resultaat."""
    def __init__(self, check_name: str, status: CheckStatus, value: float,
                 range_min: float, range_max: float, unit: str, message: str):
        self.check_name = check_name
        self.status = status
        self.value = value
        self.range_min = range_min
        self.range_max = range_max
        self.unit = unit
        self.message = message

    def __str__(self):
        return f"{self.status.value} | {self.check_name}: {self.value:.1f} {self.unit} ({self.message})"


# =============================================================================
# INDUSTRIE BENCHMARKS
# =============================================================================
BENCHMARKS = {
    'capex_per_kwh': {
        'min': 250,
        'max': 800,
        'orange_low': 300,
        'orange_high': 700,
        'unit': '€/kWh'
    },
    'payback_years': {
        'min': 2,
        'max': 15,
        'orange_low': 3,
        'orange_high': 12,
        'unit': 'jaar'
    },
    'cycles_per_year': {
        'min': 100,
        'max': 800,
        'orange_low': 150,
        'orange_high': 600,
        'unit': 'cycli/jaar'
    },
    'round_trip_efficiency': {
        'min': 0.85,
        'max': 0.95,
        'orange_low': 0.87,
        'orange_high': 0.93,
        'unit': '%'
    },
    'peak_reduction_percent': {
        'min': 5,
        'max': 50,
        'orange_low': 10,
        'orange_high': 40,
        'unit': '%'
    }
}


def get_status(value: float, benchmark: dict) -> CheckStatus:
    """Bepaal status op basis van benchmark ranges."""
    if value < benchmark['min'] or value > benchmark['max']:
        return CheckStatus.RED
    elif value < benchmark['orange_low'] or value > benchmark['orange_high']:
        return CheckStatus.ORANGE
    else:
        return CheckStatus.GREEN


def create_test_profile(days: int = 30) -> pd.DataFrame:
    """Maak representatief industrieel profiel voor 1 maand."""
    intervals = days * 24 * 4
    start = datetime(2024, 1, 1)

    np.random.seed(42)
    loads = []
    timestamps = []

    for i in range(intervals):
        ts = start + timedelta(minutes=15*i)
        timestamps.append(ts)

        hour = ts.hour
        weekday = ts.weekday()

        # Industrieel patroon
        if weekday >= 5:
            base = 15  # Weekend basis
        elif 8 <= hour <= 17:
            base = 50 + np.random.uniform(-10, 20)
            if hour in [10, 11, 14, 15]:  # Piektijden
                base *= 1.5
        elif 6 <= hour <= 8 or 17 <= hour <= 20:
            base = 30
        else:
            base = 10

        loads.append(base * np.random.uniform(0.9, 1.1) / 4)

    return pd.DataFrame({
        'timestamp': timestamps,
        'afname_kwh': loads,
        'teruglevering_kwh': [0.0] * intervals
    })


def check_capex_per_kwh(capacity_kwh: float, capex_per_kwh: float = 400) -> RealityCheck:
    """Check of CAPEX per kWh realistisch is."""
    benchmark = BENCHMARKS['capex_per_kwh']
    status = get_status(capex_per_kwh, benchmark)

    if status == CheckStatus.GREEN:
        message = f"Normaal voor commercieel ({benchmark['orange_low']}-{benchmark['orange_high']} €/kWh)"
    elif status == CheckStatus.ORANGE:
        if capex_per_kwh < benchmark['orange_low']:
            message = f"Laag - mogelijk subsidie of groot volume"
        else:
            message = f"Hoog - mogelijk inclusief installatie/BMS"
    else:
        if capex_per_kwh < benchmark['min']:
            message = f"ONREALISTISCH LAAG - controleer input"
        else:
            message = f"ONREALISTISCH HOOG - controleer input"

    return RealityCheck(
        check_name="CAPEX per kWh",
        status=status,
        value=capex_per_kwh,
        range_min=benchmark['min'],
        range_max=benchmark['max'],
        unit=benchmark['unit'],
        message=message
    )


def check_payback_years(capex: float, annual_savings: float) -> RealityCheck:
    """Check of terugverdientijd realistisch is."""
    benchmark = BENCHMARKS['payback_years']

    if annual_savings <= 0:
        return RealityCheck(
            check_name="Terugverdientijd",
            status=CheckStatus.RED,
            value=float('inf'),
            range_min=benchmark['min'],
            range_max=benchmark['max'],
            unit=benchmark['unit'],
            message="Geen positieve besparing - geen terugverdientijd"
        )

    payback = capex / annual_savings
    status = get_status(payback, benchmark)

    if status == CheckStatus.GREEN:
        message = f"Typisch voor peak shaving + arbitrage"
    elif status == CheckStatus.ORANGE:
        if payback < benchmark['orange_low']:
            message = f"ZEER SNEL - valideer aannames"
        else:
            message = f"Lang - mogelijk alleen peak shaving"
    else:
        if payback < benchmark['min']:
            message = f"ONREALISTISCH SNEL - waarschijnlijk fout in berekening"
        else:
            message = f"Te lang - business case niet haalbaar"

    return RealityCheck(
        check_name="Terugverdientijd",
        status=status,
        value=payback,
        range_min=benchmark['min'],
        range_max=benchmark['max'],
        unit=benchmark['unit'],
        message=message
    )


def check_cycles_per_year(cycles: float) -> RealityCheck:
    """Check of aantal cycli realistisch is."""
    benchmark = BENCHMARKS['cycles_per_year']
    status = get_status(cycles, benchmark)

    if status == CheckStatus.GREEN:
        message = f"Typisch voor HYBRID strategie"
    elif status == CheckStatus.ORANGE:
        if cycles < benchmark['orange_low']:
            message = f"Laag - batterij onderbenut"
        else:
            message = f"Hoog - versnelde degradatie mogelijk"
    else:
        if cycles < benchmark['min']:
            message = f"Zeer laag - overweeg kleinere batterij"
        else:
            message = f"ONREALISTISCH HOOG - garantie in gevaar"

    return RealityCheck(
        check_name="Cycli per jaar",
        status=status,
        value=cycles,
        range_min=benchmark['min'],
        range_max=benchmark['max'],
        unit=benchmark['unit'],
        message=message
    )


def check_efficiency(efficiency: float) -> RealityCheck:
    """Check of round-trip efficiency realistisch is."""
    benchmark = BENCHMARKS['round_trip_efficiency']

    # Convert to percentage for display
    eff_pct = efficiency * 100
    min_pct = benchmark['min'] * 100
    max_pct = benchmark['max'] * 100

    status = get_status(efficiency, benchmark)

    if status == CheckStatus.GREEN:
        message = f"Typisch voor LFP batterijen"
    elif status == CheckStatus.ORANGE:
        if efficiency < benchmark['orange_low']:
            message = f"Laag - mogelijk hoge C-rates"
        else:
            message = f"Optimistisch - check batterij specs"
    else:
        if efficiency < benchmark['min']:
            message = f"TE LAAG - check batterij type"
        else:
            message = f"ONMOGELIJK HOOG - fysisch niet haalbaar"

    return RealityCheck(
        check_name="Round-trip efficiency",
        status=status,
        value=eff_pct,
        range_min=min_pct,
        range_max=max_pct,
        unit=benchmark['unit'],
        message=message
    )


def check_peak_reduction(original_peak: float, new_peak: float) -> RealityCheck:
    """Check of piekvermindering realistisch is."""
    benchmark = BENCHMARKS['peak_reduction_percent']

    if original_peak <= 0:
        return RealityCheck(
            check_name="Piekvermindering",
            status=CheckStatus.RED,
            value=0,
            range_min=benchmark['min'],
            range_max=benchmark['max'],
            unit=benchmark['unit'],
            message="Geen originele piek om te reduceren"
        )

    reduction_pct = (original_peak - new_peak) / original_peak * 100
    status = get_status(reduction_pct, benchmark)

    if status == CheckStatus.GREEN:
        message = f"Normaal voor industrieel profiel"
    elif status == CheckStatus.ORANGE:
        if reduction_pct < benchmark['orange_low']:
            message = f"Laag - mogelijk vlak profiel of te kleine batterij"
        else:
            message = f"Hoog - grote batterij of extreme pieken"
    else:
        if reduction_pct < benchmark['min']:
            message = f"Zeer laag - weinig peak shaving potentieel"
        else:
            message = f"ONREALISTISCH HOOG - controleer berekening"

    return RealityCheck(
        check_name="Piekvermindering",
        status=status,
        value=reduction_pct,
        range_min=benchmark['min'],
        range_max=benchmark['max'],
        unit=benchmark['unit'],
        message=message
    )


# =============================================================================
# MAIN: RUN REALITY CHECKS
# =============================================================================
def run_reality_checks() -> list[RealityCheck]:
    """Run alle reality checks tegen gesimuleerde resultaten."""
    print("\n" + "="*70)
    print("FASE 3: REALISME-CHECK TEGEN INDUSTRIE BENCHMARKS")
    print("="*70 + "\n")

    # Setup simulatie
    profile = create_test_profile(days=30)
    capacity_kwh = 100
    capex_per_kwh = 400
    capex = capacity_kwh * capex_per_kwh

    simulator = BatteryDispatchSimulator(
        capacity_kwh=capacity_kwh,
        max_power_kw=50,
        chemistry=BatteryChemistry.LFP,
        initial_soc=0.50
    )

    tariffs = TariffStructure(
        peak_rate=0.28,
        off_peak_rate=0.14,
        capacity_tariff=52.0
    )

    result = simulator.simulate(
        profile_df=profile,
        strategy=DispatchStrategy.HYBRID,
        tariffs=tariffs
    )

    print(f"Simulatie uitgevoerd voor {capacity_kwh} kWh batterij, {profile.shape[0]} datapunten\n")

    # Run checks
    checks = []

    # 1. CAPEX check
    check = check_capex_per_kwh(capacity_kwh, capex_per_kwh)
    checks.append(check)
    print(check)

    # 2. Terugverdientijd check
    check = check_payback_years(capex, result.summary.total_savings_eur_year)
    checks.append(check)
    print(check)

    # 3. Cycli check
    check = check_cycles_per_year(result.summary.cycles_per_year)
    checks.append(check)
    print(check)

    # 4. Efficiency check
    check = check_efficiency(result.summary.average_efficiency)
    checks.append(check)
    print(check)

    # 5. Piekvermindering check
    check = check_peak_reduction(
        result.summary.original_peak_kw,
        result.summary.new_peak_kw
    )
    checks.append(check)
    print(check)

    # Summary
    print("\n" + "-"*70)
    green = sum(1 for c in checks if c.status == CheckStatus.GREEN)
    orange = sum(1 for c in checks if c.status == CheckStatus.ORANGE)
    red = sum(1 for c in checks if c.status == CheckStatus.RED)

    print(f"RESULTAAT: {green} GROEN, {orange} ORANJE, {red} ROOD")

    if red == 0 and orange == 0:
        print("✅ ALLE UITKOMSTEN BINNEN NORMALE RANGES")
    elif red == 0:
        print("⚠️  SOMMIGE UITKOMSTEN BUITEN NORMALE RANGES - REVIEW AANBEVOLEN")
    else:
        print("❌ ONREALISTISCHE UITKOMSTEN GEVONDEN - CONTROLEER BEREKENINGEN")

    print("-"*70 + "\n")

    return checks


def save_reality_report(checks: list[RealityCheck], output_dir: str = "validation"):
    """Sla reality check rapport op."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = Path(output_dir) / f"reality_report_{timestamp}.txt"

    with open(filename, 'w', encoding='utf-8') as f:
        f.write("="*70 + "\n")
        f.write("BATTERY OPTIMIZER - REALISME VALIDATIE RAPPORT\n")
        f.write("="*70 + "\n\n")
        f.write(f"Datum/tijd: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Fase: 3 - Realisme-check tegen industrie benchmarks\n\n")

        green = sum(1 for c in checks if c.status == CheckStatus.GREEN)
        orange = sum(1 for c in checks if c.status == CheckStatus.ORANGE)
        red = sum(1 for c in checks if c.status == CheckStatus.RED)

        f.write(f"TOTAAL: {green} GROEN, {orange} ORANJE, {red} ROOD\n\n")
        f.write("-"*70 + "\n\n")

        for check in checks:
            status = check.status.value
            f.write(f"[{status}] {check.check_name}\n")
            f.write(f"       Waarde: {check.value:.1f} {check.unit}\n")
            f.write(f"       Range:  {check.range_min:.0f} - {check.range_max:.0f} {check.unit}\n")
            f.write(f"       {check.message}\n\n")

        f.write("="*70 + "\n")
        f.write("INDUSTRIE BENCHMARKS REFERENTIES:\n")
        f.write("- BloombergNEF Battery Price Survey 2024\n")
        f.write("- IRENA Electricity Storage Report 2023\n")
        f.write("- Nederlandse marktdata (Enexis, TenneT, 2024)\n")
        f.write("="*70 + "\n")

    print(f"Rapport opgeslagen: {filename}")
    return filename


if __name__ == "__main__":
    checks = run_reality_checks()
    save_reality_report(checks)
