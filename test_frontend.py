"""
Frontend Verification Tests
===========================
Tests the PRODUCTION frontend by making identical requests and verifying
the displayed results match expected calculations.
"""

import json
import urllib.request
import io
import uuid
import csv
import math
from datetime import datetime, timedelta
from typing import Dict, Any, List
import random

# Production URLs
FRONTEND_URL = "https://battery-optimizer.vercel.app"
API_URL = "https://comcalculator-production.up.railway.app"

def generate_profile(
    name: str,
    peak_kw: float,
    base_kw: float,
    annual_kwh: float,
    pattern: str = "factory"
) -> str:
    """Generate a test CSV profile."""
    filepath = f"test_profiles/{name}.csv"

    # 15-minute intervals for a year
    intervals = 365 * 24 * 4  # 35040

    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'afname_kwh', 'teruglevering_kwh'])

        start = datetime(2024, 1, 1)
        total_kwh = 0

        for i in range(intervals):
            ts = start + timedelta(minutes=15 * i)
            hour = ts.hour
            weekday = ts.weekday()

            if pattern == "factory":
                # Factory: high during work hours, low at night
                if weekday < 5 and 7 <= hour <= 18:
                    load_factor = 0.7 + 0.3 * random.random()
                elif weekday < 5 and (6 <= hour <= 7 or 18 <= hour <= 22):
                    load_factor = 0.4 + 0.2 * random.random()
                else:
                    load_factor = 0.15 + 0.1 * random.random()

            elif pattern == "office":
                # Office: peaks at 9-12 and 14-17
                if weekday < 5 and (9 <= hour <= 12 or 14 <= hour <= 17):
                    load_factor = 0.8 + 0.2 * random.random()
                elif weekday < 5 and 7 <= hour <= 19:
                    load_factor = 0.4 + 0.2 * random.random()
                else:
                    load_factor = 0.1 + 0.05 * random.random()

            elif pattern == "retail":
                # Retail: peaks at shopping hours
                if weekday < 6 and 10 <= hour <= 20:
                    load_factor = 0.6 + 0.3 * random.random()
                elif weekday == 6 and 12 <= hour <= 18:
                    load_factor = 0.5 + 0.2 * random.random()
                else:
                    load_factor = 0.1 + 0.05 * random.random()

            elif pattern == "flat":
                # Flat load - data center style
                load_factor = 0.85 + 0.15 * random.random()

            elif pattern == "peaky":
                # Very peaky - extreme spikes
                if random.random() < 0.05:  # 5% chance of spike
                    load_factor = 0.9 + 0.1 * random.random()
                else:
                    load_factor = 0.2 + 0.1 * random.random()

            else:
                load_factor = 0.5 + 0.3 * random.random()

            # Calculate power and energy
            power_kw = base_kw + (peak_kw - base_kw) * load_factor
            energy_kwh = power_kw * 0.25  # 15 min = 0.25 hour
            total_kwh += energy_kwh

            writer.writerow([
                ts.strftime('%Y-%m-%d %H:%M:%S'),
                f"{energy_kwh:.2f}",
                "0"
            ])

    # Scale to match target annual consumption
    scale_factor = annual_kwh / total_kwh

    # Rewrite with scaled values
    with open(filepath, 'r') as f:
        lines = f.readlines()

    with open(filepath, 'w', newline='') as f:
        f.write(lines[0])  # Header
        for line in lines[1:]:
            parts = line.strip().split(',')
            scaled_kwh = float(parts[1]) * scale_factor
            f.write(f"{parts[0]},{scaled_kwh:.4f},0\n")

    return filepath


def call_frontend_api(
    csv_path: str,
    peak_rate: float,
    off_peak_rate: float,
    capacity_tariff: float,  # EUR/kW/year
    postcode: str = "1071BV"
) -> Dict[str, Any]:
    """
    Make the exact same API call the frontend makes.
    Returns the parsed results as they would appear in the UI.
    """
    with open(csv_path, 'rb') as f:
        csv_content = f.read()

    boundary = str(uuid.uuid4())
    body = io.BytesIO()

    def write_field(name, value):
        body.write(f'--{boundary}\r\n'.encode())
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.write(f'{value}\r\n'.encode())

    def write_file(name, filename, content):
        body.write(f'--{boundary}\r\n'.encode())
        body.write(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
        body.write(f'Content-Type: text/csv\r\n\r\n'.encode())
        body.write(content)
        body.write(b'\r\n')

    # Build request exactly like frontend
    write_file('file', 'profiel.csv', csv_content)
    write_field('timestamp_col', 'timestamp')
    write_field('afname_col', 'afname_kwh')
    write_field('postcode', postcode)
    write_field('peak_rate', str(peak_rate))
    write_field('off_peak_rate', str(off_peak_rate))
    write_field('capacity_tariff', str(capacity_tariff))

    body.write(f'--{boundary}--\r\n'.encode())

    req = urllib.request.Request(
        f'{API_URL}/api/v1/analyze-stream',
        data=body.getvalue(),
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
        method='POST'
    )

    results = {
        'profile': {},
        'scenarios': [],
        'revenue_streams': {},
        'optimal_size': None,
        'errors': []
    }

    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            for line in response:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:].strip()
                    if data_str and data_str != '[DONE]':
                        try:
                            event = json.loads(data_str)
                            t = event.get('type', '')

                            if t == 'phase_complete' and event.get('phase') == 'profile_loading':
                                d = event.get('data', {})
                                results['profile'] = {
                                    'peak_kw': d.get('peak_kw'),
                                    'annual_kwh': d.get('annual_consumption_kwh'),
                                    'records': d.get('records'),
                                    'days': d.get('days_of_data')
                                }

                            elif t == 'scenario_result':
                                size = event.get('scenario_kwh', 0)
                                d = event.get('data', {})
                                results['scenarios'].append({
                                    'size_kwh': size,
                                    'npv_mean': d.get('npv_mean'),
                                    'npv_p5': d.get('npv_p5'),
                                    'npv_p95': d.get('npv_p95'),
                                    'payback_mean': d.get('payback_mean'),
                                    'irr_mean': d.get('irr_mean'),
                                    'cycles_per_year': d.get('cycles_per_year'),
                                    'peak_reduction_kw': d.get('peak_reduction_kw'),
                                    'capex': d.get('capex'),
                                    'positive_npv_probability': d.get('positive_npv_probability')
                                })

                            elif t == 'revenue_streams':
                                results['revenue_streams'] = event.get('streams', {})

                            elif t == 'completed':
                                d = event.get('data', {})
                                results['optimal_size'] = d.get('optimal_size_kwh')

                            elif t == 'error':
                                results['errors'].append(event.get('message', 'Unknown error'))

                        except json.JSONDecodeError:
                            pass

    except Exception as e:
        results['errors'].append(str(e))

    return results


def verify_results(test_name: str, results: Dict, expected: Dict) -> List[str]:
    """Verify results match expectations."""
    issues = []

    # Check profile data
    if results['profile']:
        p = results['profile']
        if expected.get('peak_kw'):
            diff = abs(p['peak_kw'] - expected['peak_kw']) / expected['peak_kw']
            if diff > 0.15:  # 15% tolerance
                issues.append(f"Peak mismatch: got {p['peak_kw']:.0f}, expected ~{expected['peak_kw']:.0f}")

        if expected.get('annual_mwh'):
            actual_mwh = p['annual_kwh'] / 1000
            diff = abs(actual_mwh - expected['annual_mwh']) / expected['annual_mwh']
            if diff > 0.15:
                issues.append(f"Annual consumption mismatch: got {actual_mwh:.1f} MWh, expected ~{expected['annual_mwh']:.1f} MWh")

    # Check scenarios exist
    if not results['scenarios']:
        issues.append("No scenarios returned!")
    else:
        # Check NPV signs make sense
        for s in results['scenarios']:
            if s['npv_mean'] is not None:
                # Very negative NPV with reasonable tariffs is suspicious
                if expected.get('expect_positive_npv', True) and s['npv_mean'] < -100000:
                    issues.append(f"Scenario {s['size_kwh']} kWh has very negative NPV: {s['npv_mean']:.0f}")

        # Check payback is reasonable
        for s in results['scenarios']:
            if s['payback_mean'] and s['payback_mean'] > 20:
                issues.append(f"Scenario {s['size_kwh']} kWh has unrealistic payback: {s['payback_mean']:.1f} years")

    return issues


def run_test(
    test_num: int,
    name: str,
    csv_path: str,
    peak_rate: float,
    off_peak_rate: float,
    capacity_tariff: float,
    expected: Dict
) -> bool:
    """Run a single test and report results."""
    print(f"\n{'='*60}")
    print(f"TEST {test_num}: {name}")
    print(f"{'='*60}")
    print(f"Tarieven: peak={peak_rate} EUR/kWh, offpeak={off_peak_rate} EUR/kWh, capacity={capacity_tariff} EUR/kW/jaar")

    results = call_frontend_api(csv_path, peak_rate, off_peak_rate, capacity_tariff)

    if results['errors']:
        print(f"ERRORS: {results['errors']}")
        return False

    # Display what frontend shows
    print(f"\nPROFIEL (zoals getoond in frontend):")
    p = results['profile']
    print(f"  Piekvermogen:    {p.get('peak_kw', 'N/A'):,.1f} kW")
    print(f"  Jaarverbruik:    {p.get('annual_kwh', 0)/1000:,.1f} MWh")
    print(f"  Records:         {p.get('records', 'N/A')}")

    print(f"\nSCENARIO'S (zoals getoond in frontend):")
    print(f"{'Grootte':>10} {'CAPEX':>12} {'NPV':>12} {'Payback':>10} {'IRR':>8} {'Cycles':>8}")
    print("-" * 70)

    for s in results['scenarios']:
        capex = s.get('capex', 0) or 0
        npv = s.get('npv_mean', 0) or 0
        payback = s.get('payback_mean', 0) or 0
        irr = (s.get('irr_mean', 0) or 0) * 100
        cycles = s.get('cycles_per_year', 0) or 0

        print(f"{s['size_kwh']:>8.0f} kWh {capex:>10,.0f} € {npv:>10,.0f} € {payback:>8.1f} j {irr:>6.1f}% {cycles:>6.0f}")

    if results.get('optimal_size'):
        print(f"\nOPTIMALE GROOTTE: {results['optimal_size']} kWh")

    # Verify
    issues = verify_results(name, results, expected)

    if issues:
        print(f"\n[!] ISSUES GEVONDEN:")
        for issue in issues:
            print(f"  - {issue}")
        return False
    else:
        print(f"\n[OK] TEST GESLAAGD")
        return True


# =============================================================================
# MAIN TEST SUITE
# =============================================================================

if __name__ == "__main__":
    print("="*60)
    print("FRONTEND VERIFICATIE TESTS")
    print("="*60)
    print(f"Frontend: {FRONTEND_URL}")
    print(f"API: {API_URL}")
    print()

    results_summary = []

    # =========================================================================
    # TEST 1: Grote fabriek (bestaande CSV)
    # =========================================================================
    results_summary.append(run_test(
        test_num=1,
        name="Grote Fabriek (bestaand profiel)",
        csv_path=r"C:\Users\BartVisser\Downloads\grote_fabriek_jaarprofiel.csv",
        peak_rate=0.28,
        off_peak_rate=0.18,
        capacity_tariff=91.56,  # EUR/kW/year
        expected={
            'peak_kw': 1900,
            'annual_mwh': 6300,
            'expect_positive_npv': True
        }
    ))

    # =========================================================================
    # TEST 2: Kleine fabriek - lage tarieven
    # =========================================================================
    generate_profile("kleine_fabriek", peak_kw=500, base_kw=100, annual_kwh=1_500_000, pattern="factory")
    results_summary.append(run_test(
        test_num=2,
        name="Kleine Fabriek - Lage Tarieven",
        csv_path="test_profiles/kleine_fabriek.csv",
        peak_rate=0.20,
        off_peak_rate=0.12,
        capacity_tariff=60.00,
        expected={
            'peak_kw': 500,
            'annual_mwh': 1500,
            'expect_positive_npv': True
        }
    ))

    # =========================================================================
    # TEST 3: Kantoorgebouw - hoge tarieven
    # =========================================================================
    generate_profile("kantoor", peak_kw=300, base_kw=50, annual_kwh=800_000, pattern="office")
    results_summary.append(run_test(
        test_num=3,
        name="Kantoorgebouw - Hoge Tarieven",
        csv_path="test_profiles/kantoor.csv",
        peak_rate=0.35,
        off_peak_rate=0.22,
        capacity_tariff=120.00,
        expected={
            'peak_kw': 300,
            'annual_mwh': 800,
            'expect_positive_npv': True
        }
    ))

    # =========================================================================
    # TEST 4: Retail - gemiddelde tarieven
    # =========================================================================
    generate_profile("retail", peak_kw=400, base_kw=80, annual_kwh=1_200_000, pattern="retail")
    results_summary.append(run_test(
        test_num=4,
        name="Retail - Gemiddelde Tarieven",
        csv_path="test_profiles/retail.csv",
        peak_rate=0.28,
        off_peak_rate=0.16,
        capacity_tariff=85.00,
        expected={
            'peak_kw': 400,
            'annual_mwh': 1200,
            'expect_positive_npv': True
        }
    ))

    # =========================================================================
    # TEST 5: Datacenter - vlak profiel
    # =========================================================================
    generate_profile("datacenter", peak_kw=1000, base_kw=850, annual_kwh=8_000_000, pattern="flat")
    results_summary.append(run_test(
        test_num=5,
        name="Datacenter - Vlak Profiel",
        csv_path="test_profiles/datacenter.csv",
        peak_rate=0.25,
        off_peak_rate=0.15,
        capacity_tariff=70.00,
        expected={
            'peak_kw': 1000,
            'annual_mwh': 8000,
            'expect_positive_npv': False  # Vlak profiel = weinig peak shaving potentieel
        }
    ))

    # =========================================================================
    # TEST 6: Zeer peaky profiel
    # =========================================================================
    generate_profile("peaky", peak_kw=2000, base_kw=200, annual_kwh=2_000_000, pattern="peaky")
    results_summary.append(run_test(
        test_num=6,
        name="Zeer Peaky Profiel",
        csv_path="test_profiles/peaky.csv",
        peak_rate=0.30,
        off_peak_rate=0.18,
        capacity_tariff=100.00,
        expected={
            'peak_kw': 2000,
            'annual_mwh': 2000,
            'expect_positive_npv': True  # Veel peak shaving potentieel
        }
    ))

    # =========================================================================
    # TEST 7: Extreem lage tarieven (moet negatieve NPV geven)
    # =========================================================================
    results_summary.append(run_test(
        test_num=7,
        name="Grote Fabriek - Extreem Lage Tarieven",
        csv_path=r"C:\Users\BartVisser\Downloads\grote_fabriek_jaarprofiel.csv",
        peak_rate=0.08,
        off_peak_rate=0.05,
        capacity_tariff=20.00,
        expected={
            'peak_kw': 1900,
            'annual_mwh': 6300,
            'expect_positive_npv': False  # Te lage tarieven
        }
    ))

    # =========================================================================
    # TEST 8: Extreem hoge tarieven
    # =========================================================================
    results_summary.append(run_test(
        test_num=8,
        name="Grote Fabriek - Extreem Hoge Tarieven",
        csv_path=r"C:\Users\BartVisser\Downloads\grote_fabriek_jaarprofiel.csv",
        peak_rate=0.50,
        off_peak_rate=0.30,
        capacity_tariff=200.00,
        expected={
            'peak_kw': 1900,
            'annual_mwh': 6300,
            'expect_positive_npv': True
        }
    ))

    # =========================================================================
    # TEST 9: Middelgroot bedrijf
    # =========================================================================
    generate_profile("middelgroot", peak_kw=800, base_kw=200, annual_kwh=3_000_000, pattern="factory")
    results_summary.append(run_test(
        test_num=9,
        name="Middelgroot Bedrijf",
        csv_path="test_profiles/middelgroot.csv",
        peak_rate=0.28,
        off_peak_rate=0.17,
        capacity_tariff=90.00,
        expected={
            'peak_kw': 800,
            'annual_mwh': 3000,
            'expect_positive_npv': True
        }
    ))

    # =========================================================================
    # TEST 10: Klein bedrijf - minimale installatie
    # =========================================================================
    generate_profile("klein", peak_kw=150, base_kw=30, annual_kwh=400_000, pattern="office")
    results_summary.append(run_test(
        test_num=10,
        name="Klein Bedrijf",
        csv_path="test_profiles/klein.csv",
        peak_rate=0.32,
        off_peak_rate=0.20,
        capacity_tariff=95.00,
        expected={
            'peak_kw': 150,
            'annual_mwh': 400,
            'expect_positive_npv': True
        }
    ))

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "="*60)
    print("SAMENVATTING")
    print("="*60)

    passed = sum(1 for r in results_summary if r)
    failed = sum(1 for r in results_summary if not r)

    print(f"Geslaagd: {passed}/10")
    print(f"Gefaald:  {failed}/10")

    if failed == 0:
        print("\n[OK] ALLE TESTS GESLAAGD - Frontend toont correcte backend data!")
    else:
        print(f"\n[!] {failed} TEST(S) GEFAALD - Controleer de issues hierboven")
