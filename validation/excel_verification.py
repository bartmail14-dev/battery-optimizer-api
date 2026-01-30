"""
===============================================================================
FASE 4: EXCEL VERIFICATIE (HANDMATIGE STEEKPROEF)
===============================================================================

Dit script exporteert de eerste 24 uur van een simulatie naar Excel,
zodat iemand de berekeningen handmatig kan narekenen.

Output: validation/steekproef_24uur.xlsx

Run: python validation/excel_verification.py
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


def create_24h_profile() -> pd.DataFrame:
    """Maak 24-uurs testprofiel met herkenbare pieken."""
    intervals = 24 * 4  # 96 intervallen van 15 minuten
    start = datetime(2024, 1, 15, 0, 0)  # Maandag

    loads = []
    timestamps = []

    for i in range(intervals):
        ts = start + timedelta(minutes=15*i)
        timestamps.append(ts)
        hour = ts.hour

        # Duidelijk patroon voor makkelijke verificatie
        if 0 <= hour < 6:  # Nacht: laag
            load = 20
        elif 6 <= hour < 8:  # Ochtend opstart
            load = 35
        elif 8 <= hour < 10:  # Ochtend piek
            load = 55
        elif 10 <= hour < 12:  # Hoge productie piek
            load = 75  # PIEK
        elif 12 <= hour < 13:  # Lunch dip
            load = 40
        elif 13 <= hour < 16:  # Middag
            load = 60
        elif 16 <= hour < 18:  # Tweede piek
            load = 70
        elif 18 <= hour < 21:  # Avond afbouw
            load = 45
        else:  # Nacht
            load = 25

        loads.append(load / 4)  # kW naar kWh per 15 min

    return pd.DataFrame({
        'timestamp': timestamps,
        'afname_kwh': loads,
        'teruglevering_kwh': [0.0] * intervals
    })


def export_to_excel(output_path: str = "validation/steekproef_24uur.xlsx"):
    """
    Exporteer 24-uurs simulatie naar Excel met alle details.
    """
    print("\n" + "="*70)
    print("FASE 4: EXCEL VERIFICATIE EXPORT")
    print("="*70 + "\n")

    # Setup
    profile = create_24h_profile()
    capacity_kwh = 50
    max_power_kw = 25
    capex_per_kwh = 400
    capex = capacity_kwh * capex_per_kwh

    simulator = BatteryDispatchSimulator(
        capacity_kwh=capacity_kwh,
        max_power_kw=max_power_kw,
        chemistry=BatteryChemistry.LFP,
        initial_soc=0.50,
        min_soc=0.10,
        max_soc=0.90
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

    # Bouw Excel data
    data = []
    cumulative_savings = 0

    for interval in result.hourly_results:
        # Bepaal tarief (piek of dal)
        hour = interval.timestamp.hour
        is_peak = 7 <= hour < 21
        tariff = tariffs.peak_rate if is_peak else tariffs.off_peak_rate
        tariff_type = "Piek" if is_peak else "Dal"

        # Bereken kosten
        original_cost = interval.original_load_kwh * tariff
        new_cost = interval.new_load_kwh * tariff
        interval_savings = original_cost - new_cost
        cumulative_savings += interval_savings

        data.append({
            'Timestamp': interval.timestamp.strftime('%Y-%m-%d %H:%M'),
            'Uur': hour,
            'Tarief_Type': tariff_type,
            'Tarief_EUR_kWh': tariff,
            'Origineel_kWh': round(interval.original_load_kwh, 4),
            'Origineel_kW': round(interval.original_load_kwh * 4, 2),  # kWh/15min -> kW
            'Charge_kWh': round(interval.charge_kwh, 4),
            'Discharge_kWh': round(interval.discharge_kwh, 4),
            'Nieuw_kWh': round(interval.new_load_kwh, 4),
            'Nieuw_kW': round(interval.new_load_kwh * 4, 2),
            'SoC_kWh': round(interval.soc_kwh, 2),
            'SoC_Percent': round(interval.soc_percent * 100, 1),
            'Efficiency': round(interval.efficiency, 4),
            'Kosten_Origineel_EUR': round(original_cost, 4),
            'Kosten_Nieuw_EUR': round(new_cost, 4),
            'Besparing_EUR': round(interval_savings, 4),
            'Cumulatief_EUR': round(cumulative_savings, 4),
            'Strategie': interval.strategy_used
        })

    df = pd.DataFrame(data)

    # Maak Excel met meerdere sheets
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        # Sheet 1: Detaildata
        df.to_excel(writer, sheet_name='Simulatie_Details', index=False)

        # Sheet 2: Samenvatting
        summary_data = {
            'Metric': [
                'Simulatie Periode',
                'Batterij Capaciteit (kWh)',
                'Max Vermogen (kW)',
                'Min SoC (%)',
                'Max SoC (%)',
                'CAPEX (€/kWh)',
                'Totaal CAPEX (€)',
                '',
                'Originele Piek (kW)',
                'Nieuwe Piek (kW)',
                'Piekvermindering (kW)',
                'Piekvermindering (%)',
                '',
                'Totaal Origineel Verbruik (kWh)',
                'Totaal Nieuw Verbruik (kWh)',
                'Totaal Geladen (kWh)',
                'Totaal Ontladen (kWh)',
                '',
                'Totale Besparing (€)',
                'Besparing per Uur (€)',
                'Geschatte Jaarlijkse Besparing (€)',
                'Geschatte Terugverdientijd (jaar)',
            ],
            'Waarde': [
                '24 uur (15-min intervallen)',
                capacity_kwh,
                max_power_kw,
                10,
                90,
                capex_per_kwh,
                capex,
                '',
                round(result.summary.original_peak_kw, 2),
                round(result.summary.new_peak_kw, 2),
                round(result.summary.peak_reduction_kw, 2),
                round(result.summary.peak_reduction_kw / result.summary.original_peak_kw * 100, 1) if result.summary.original_peak_kw > 0 else 0,
                '',
                round(df['Origineel_kWh'].sum(), 2),
                round(df['Nieuw_kWh'].sum(), 2),
                round(df['Charge_kWh'].sum(), 2),
                round(df['Discharge_kWh'].sum(), 2),
                '',
                round(cumulative_savings, 2),
                round(cumulative_savings / 24, 4),
                round(cumulative_savings * 365, 2),
                round(capex / (cumulative_savings * 365), 1) if cumulative_savings > 0 else 'N/A',
            ],
            'Eenheid': [
                '',
                'kWh',
                'kW',
                '%',
                '%',
                '€/kWh',
                '€',
                '',
                'kW',
                'kW',
                'kW',
                '%',
                '',
                'kWh',
                'kWh',
                'kWh',
                'kWh',
                '',
                '€',
                '€/uur',
                '€/jaar',
                'jaar',
            ]
        }
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='Samenvatting', index=False)

        # Sheet 3: Tarieven info
        tariff_data = {
            'Parameter': [
                'Piek Tarief',
                'Piek Uren',
                'Dal Tarief',
                'Dal Uren',
                'Capaciteitstarief',
                'Teruglevering',
            ],
            'Waarde': [
                tariffs.peak_rate,
                f"{tariffs.peak_hours_start}:00 - {tariffs.peak_hours_end}:00",
                tariffs.off_peak_rate,
                f"{tariffs.peak_hours_end}:00 - {tariffs.peak_hours_start}:00",
                tariffs.capacity_tariff,
                tariffs.feed_in_tariff,
            ],
            'Eenheid': [
                '€/kWh',
                '',
                '€/kWh',
                '',
                '€/kW/maand',
                '€/kWh',
            ]
        }
        tariff_df = pd.DataFrame(tariff_data)
        tariff_df.to_excel(writer, sheet_name='Tarieven', index=False)

        # Sheet 4: Verificatie formules (uitleg)
        formulas = {
            'Kolom': [
                'Nieuw_kWh',
                'Kosten_Origineel_EUR',
                'Kosten_Nieuw_EUR',
                'Besparing_EUR',
                'Origineel_kW',
                'SoC_Percent',
            ],
            'Formule': [
                '= Origineel_kWh - Discharge_kWh + Charge_kWh',
                '= Origineel_kWh × Tarief_EUR_kWh',
                '= Nieuw_kWh × Tarief_EUR_kWh',
                '= Kosten_Origineel_EUR - Kosten_Nieuw_EUR',
                '= Origineel_kWh × 4 (15-min → uur)',
                '= SoC_kWh / Batterij_Capaciteit × 100',
            ],
            'Beschrijving': [
                'Grid exchange na batterij actie',
                'Kosten zonder batterij',
                'Kosten met batterij',
                'Verschil in kosten dit interval',
                'Vermogen in kW (power)',
                'State of Charge als percentage',
            ]
        }
        formula_df = pd.DataFrame(formulas)
        formula_df.to_excel(writer, sheet_name='Verificatie_Formules', index=False)

    print(f"✅ Excel bestand gemaakt: {output_file.absolute()}")
    print(f"\nInhoud:")
    print(f"  - Sheet 'Simulatie_Details': {len(df)} regels met alle intervaldata")
    print(f"  - Sheet 'Samenvatting': Overzicht key metrics")
    print(f"  - Sheet 'Tarieven': Gebruikte tarief parameters")
    print(f"  - Sheet 'Verificatie_Formules': Uitleg berekeningen")

    print(f"\n📊 Key Resultaten:")
    print(f"  - Originele piek: {result.summary.original_peak_kw:.1f} kW")
    print(f"  - Nieuwe piek: {result.summary.new_peak_kw:.1f} kW")
    print(f"  - Piekvermindering: {result.summary.peak_reduction_kw:.1f} kW ({result.summary.peak_reduction_kw/result.summary.original_peak_kw*100:.0f}%)")
    print(f"  - 24u besparing: €{cumulative_savings:.2f}")
    print(f"  - Geschatte jaarbesparing: €{cumulative_savings * 365:.0f}")

    print(f"\n" + "-"*70)
    print("Je kunt nu de Excel openen en handmatig de formules narekenen!")
    print("-"*70 + "\n")

    return output_file


if __name__ == "__main__":
    export_to_excel()
