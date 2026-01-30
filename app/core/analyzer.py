"""Profile analysis module."""

import pandas as pd
import numpy as np
from typing import List
import structlog

from app.models.schemas import ProfileAnalysis, HourlyProfile

logger = structlog.get_logger()


def analyze_profile(df: pd.DataFrame) -> ProfileAnalysis:
    """
    Comprehensive analysis of energy profile.

    Args:
        df: DataFrame with columns: timestamp, afname_kwh, teruglevering_kwh

    Returns:
        ProfileAnalysis with all metrics
    """
    logger.info("Analyzing profile", rows=len(df))

    # Basic totals
    total_afname = float(df['afname_kwh'].sum())
    total_teruglevering = float(df['teruglevering_kwh'].sum())
    netto = total_afname - total_teruglevering

    # Detect interval (minutes)
    time_diffs = df['timestamp'].diff().dt.total_seconds() / 60
    interval_minutes = float(time_diffs.median()) if time_diffs.notna().any() else 15
    intervals_per_hour = 60 / interval_minutes

    # Convert kWh to kW (power)
    df = df.copy()
    df['afname_kw'] = df['afname_kwh'] * intervals_per_hour
    df['teruglevering_kw'] = df['teruglevering_kwh'] * intervals_per_hour

    # Peak and average
    peak_afname_kw = float(df['afname_kw'].max())
    avg_afname_kw = float(df['afname_kw'].mean())

    # Baseload (10th percentile)
    baseload_kw = float(df['afname_kw'].quantile(0.10))

    # Load factor
    load_factor = avg_afname_kw / peak_afname_kw if peak_afname_kw > 0 else 0

    # Hourly profile
    df['hour'] = df['timestamp'].dt.hour
    hourly_stats = df.groupby('hour').agg({
        'afname_kw': ['mean', 'max', 'std'],
        'teruglevering_kw': ['mean']
    }).reset_index()

    # Flatten MultiIndex columns
    hourly_stats.columns = ['hour', 'afname_mean', 'afname_max', 'afname_std', 'teruglevering_mean']

    hourly_profile = [
        HourlyProfile(
            hour=int(row['hour']),
            avg_afname_kw=round(float(row['afname_mean']), 3),
            avg_teruglevering_kw=round(float(row['teruglevering_mean']), 3),
            peak_afname_kw=round(float(row['afname_max']), 3),
            std_dev=round(float(row['afname_std']), 3)
            if pd.notna(row['afname_std']) else 0
        )
        for _, row in hourly_stats.iterrows()
    ]

    # Peak hours (hours above average + 1 std)
    hourly_avgs = [h.avg_afname_kw for h in hourly_profile]
    threshold = np.mean(hourly_avgs) + np.std(hourly_avgs)
    peak_hours = [h.hour for h in hourly_profile if h.avg_afname_kw > threshold]

    # Monthly totals
    df['month'] = df['timestamp'].dt.strftime('%Y-%m')
    monthly_totals = {k: round(v, 2) for k, v in df.groupby('month')['afname_kwh'].sum().to_dict().items()}

    # Data days
    date_range = df['timestamp'].max() - df['timestamp'].min()
    data_days = max(1, date_range.days + 1)

    # Has solar data
    has_solar = total_teruglevering > 0

    # Generate recommendations
    recommendations = generate_recommendations(
        load_factor=load_factor,
        peak_kw=peak_afname_kw,
        has_solar=has_solar,
        total_kwh=total_afname
    )

    return ProfileAnalysis(
        total_afname_kwh=round(total_afname, 2),
        total_teruglevering_kwh=round(total_teruglevering, 2),
        netto_verbruik_kwh=round(netto, 2),
        peak_afname_kw=round(peak_afname_kw, 2),
        avg_afname_kw=round(avg_afname_kw, 2),
        baseload_kw=round(baseload_kw, 2),
        load_factor=round(load_factor, 3),
        peak_hours=peak_hours,
        hourly_profile=hourly_profile,
        monthly_totals=monthly_totals,
        has_solar_data=has_solar,
        data_days=data_days,
        recommendations=recommendations
    )


def generate_recommendations(
    load_factor: float,
    peak_kw: float,
    has_solar: bool,
    total_kwh: float
) -> List[str]:
    """Generate battery recommendations based on profile characteristics."""
    recommendations = []

    if load_factor < 0.35:
        recommendations.append(
            f"Load factor van {load_factor:.0%} indiceert significant piekgedrag. "
            "Peak shaving strategie aanbevolen voor maximale capaciteitstarief besparing."
        )
    elif load_factor < 0.55:
        recommendations.append(
            f"Gemiddelde load factor ({load_factor:.0%}). "
            "Combinatie van peak shaving en arbitrage biedt optimaal rendement."
        )
    else:
        recommendations.append(
            f"Vlak verbruiksprofiel (load factor {load_factor:.0%}). "
            "Beperkt peak shaving potentieel, focus op arbitrage of eigen verbruik optimalisatie."
        )

    if has_solar:
        recommendations.append(
            "Teruglevering gedetecteerd. Self-consumption optimalisatie kan "
            "terugleververgoeding verbeteren door eigen opwek te bufferen."
        )

    if peak_kw > 100:
        recommendations.append(
            f"Piekvermogen van {peak_kw:.0f} kW suggereert industrieel profiel. "
            "Overweeg grotere batterijcapaciteit voor significante piekvermindering."
        )

    # Size recommendations based on consumption
    annual_kwh = total_kwh * (365 / max(1, total_kwh / 100))  # Rough annualization
    if annual_kwh > 100000:
        recommendations.append(
            "Hoog jaarverbruik. Batterij van 50-200 kWh biedt beste rendement."
        )
    elif annual_kwh > 20000:
        recommendations.append(
            "Gemiddeld verbruik. Batterij van 10-50 kWh is waarschijnlijk optimaal."
        )

    return recommendations


def calculate_load_duration_curve(df: pd.DataFrame) -> List[dict]:
    """Calculate load duration curve data for visualization."""
    if 'afname_kw' not in df.columns:
        # Calculate if not present
        time_diffs = df['timestamp'].diff().dt.total_seconds() / 60
        interval_minutes = float(time_diffs.median()) if time_diffs.notna().any() else 15
        intervals_per_hour = 60 / interval_minutes
        df = df.copy()
        df['afname_kw'] = df['afname_kwh'] * intervals_per_hour

    sorted_loads = df['afname_kw'].sort_values(ascending=False).reset_index(drop=True)
    n = len(sorted_loads)

    return [
        {
            'percentile': round(i / n * 100, 1),
            'load_kw': round(float(sorted_loads.iloc[i]), 2)
        }
        for i in range(0, n, max(1, n // 100))
    ]
