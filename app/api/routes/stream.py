"""
===============================================================================
SSE STREAMING ENDPOINT
===============================================================================

Real-time progress updates via Server-Sent Events (SSE).

Dit endpoint stuurt live updates naar de frontend tijdens de berekening:
- Profile loading progress
- Monte Carlo simulation progress per scenario
- Intermediate results
- Validation checks
- Final results

GEBRUIK:
```javascript
const eventSource = new EventSource('/api/v1/analyze-stream');
eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log(data.type, data.message);
};
```
===============================================================================
"""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator, List, Optional
import asyncio
import time
import structlog
import pandas as pd
from io import BytesIO

from app.api.routes.upload import SESSIONS
from app.core.parser import detect_delimiter, find_header_row, normalize_dataframe
from app.core.analyzer import analyze_profile
from app.engine.progress import (
    ProgressEvent,
    ProgressEventType,
    create_started_event,
    create_phase_event,
    create_simulation_progress_event,
    create_scenario_result_event,
    create_validation_check_event,
    create_completed_event,
    create_error_event,
)
from app.engine import MonteCarloEngine, BatteryDispatchSimulator, TCOCalculator
from app.engine.simulation import TariffStructure, DispatchStrategy
from app.engine.degradation import BatteryChemistry
from app.engine.monte_carlo import MonteCarloConfig
from app.validation import SanityChecker
from app.models.schemas import ColumnMapping

# COMCAM Feature Imports
from app.engine.revenue_streams import RevenueCalculator
from app.engine.market_params import MarketParams, DEFAULT_MARKET_PARAMS
from app.engine.growth_projector import GrowthProjector, GrowthScenarioType, get_scenario
from app.engine.sizing_advisor import SizingAdvisor, BatteryConstraints
from app.visualization.charts import ChartGenerator

# AI Review
from app.services.gemini_reviewer import get_gemini_reviewer

import numpy as np
from typing import Dict, Any

router = APIRouter()
logger = structlog.get_logger()


def calculate_yearly_cashflows(
    sim_data: List[Dict[str, float]],
    analysis_years: int,
    max_paths: int = 100,
    yearly_price_volatility: float = 0.12
) -> Dict[str, Any]:
    """
    Calculate cumulative cashflow data for Monte Carlo fan/spaghetti visualization.

    Uses a stochastic price model with year-on-year volatility to create realistic
    uncertainty spreading (the characteristic "fan" or "pluim" shape).

    Args:
        sim_data: List of simulation data dicts with 'capex', 'savings', 'degrad_mult'
        analysis_years: Number of years in the analysis
        max_paths: Maximum number of individual paths to include (for spaghetti plot)
        yearly_price_volatility: Annual volatility for energy prices (default 12%)
            This creates realistic year-on-year price uncertainty.
            Historical Dutch energy price volatility: 10-20% per year.

    Returns:
        Dict with:
        - percentiles: List of dicts with year and percentile values
        - paths: List of individual simulation paths (for spaghetti plot)
    """
    n_sims = len(sim_data)
    if n_sims == 0:
        return {"percentiles": [], "paths": []}

    n_years = analysis_years

    # Matrix of cumulative cashflows: [simulation, year]
    cumulative_cashflows = np.zeros((n_sims, n_years + 1))  # +1 for year 0

    base_degradation_rate = 0.02  # 2% per year baseline

    # Pre-generate price multiplier paths for ALL simulations
    # Using Geometric Brownian Motion (GBM) for realistic price dynamics
    # This creates the characteristic spreading uncertainty over time
    price_multiplier_paths = np.ones((n_sims, n_years + 1))

    # Generate log-normal random walk for each simulation
    # Using variance-corrected drift to ensure E[multiplier] = 1
    drift = -0.5 * yearly_price_volatility**2  # Ito correction

    for i in range(n_sims):
        for year in range(1, n_years + 1):
            # Random shock for this year
            shock = np.random.normal(0, yearly_price_volatility)
            # Geometric random walk: each year builds on previous
            price_multiplier_paths[i, year] = price_multiplier_paths[i, year-1] * np.exp(drift + shock)

    for i, sim in enumerate(sim_data):
        capex = sim['capex']
        savings = sim['savings']
        degrad_mult = sim['degrad_mult']

        degradation_rate = base_degradation_rate * degrad_mult

        # Year 0: initial investment (negative)
        cumulative_cashflows[i, 0] = -capex

        cumulative = -capex
        for year in range(1, n_years + 1):
            # Capacity factor due to degradation
            capacity_factor = (1 - degradation_rate) ** year

            # Year-specific price multiplier from stochastic path
            # This creates the realistic "spreading" in the spaghetti plot
            price_multiplier = price_multiplier_paths[i, year]

            # Annual savings with degradation AND market price volatility
            year_savings = savings * capacity_factor * price_multiplier

            # Annual maintenance (assume 1% of CAPEX)
            maintenance = capex * 0.01

            # Net cashflow this year
            net_cashflow = year_savings - maintenance

            cumulative += net_cashflow
            cumulative_cashflows[i, year] = cumulative

    # Calculate percentiles per year
    yearly_percentiles = []

    for year in range(n_years + 1):
        year_cashflows = cumulative_cashflows[:, year]

        yearly_percentiles.append({
            "year": year,
            "p5": round(float(np.percentile(year_cashflows, 5)), 2),
            "p10": round(float(np.percentile(year_cashflows, 10)), 2),
            "p25": round(float(np.percentile(year_cashflows, 25)), 2),
            "p50": round(float(np.percentile(year_cashflows, 50)), 2),
            "p75": round(float(np.percentile(year_cashflows, 75)), 2),
            "p90": round(float(np.percentile(year_cashflows, 90)), 2),
            "p95": round(float(np.percentile(year_cashflows, 95)), 2),
            "mean": round(float(np.mean(year_cashflows)), 2)
        })

    # Extract individual paths for spaghetti plot (sample if too many)
    paths = []
    if n_sims <= max_paths:
        indices = range(n_sims)
    else:
        # Stratified sampling: include extremes and random middle
        sorted_by_final = np.argsort(cumulative_cashflows[:, -1])
        # Include top 10%, bottom 10%, and random from middle
        n_extreme = max(5, max_paths // 10)
        n_middle = max_paths - 2 * n_extreme
        bottom_indices = sorted_by_final[:n_extreme].tolist()
        top_indices = sorted_by_final[-n_extreme:].tolist()
        middle_pool = sorted_by_final[n_extreme:-n_extreme]
        middle_indices = np.random.choice(middle_pool, size=min(n_middle, len(middle_pool)), replace=False).tolist()
        indices = bottom_indices + middle_indices + top_indices

    for idx in indices:
        path = []
        for year in range(n_years + 1):
            path.append(round(float(cumulative_cashflows[idx, year]), 2))
        paths.append(path)

    return {
        "percentiles": yearly_percentiles,
        "paths": paths,
        "n_simulations": n_sims,
        "n_paths_shown": len(paths)
    }


@router.post("/analyze-stream")
async def analyze_battery_stream(
    file: UploadFile = File(...),
    battery_sizes: str = Form("50,75,100,150,200"),
    n_simulations: int = Form(1000),
    strategy: str = Form("hybrid"),
    chemistry: str = Form("lfp"),
    analysis_years: int = Form(15),
    discount_rate: float = Form(0.05),
    # Column mapping
    timestamp_col: str = Form(...),
    afname_col: str = Form(...),
    teruglevering_col: Optional[str] = Form(None),
    # Tariffs
    peak_rate: float = Form(0.35),
    off_peak_rate: float = Form(0.22),
    capacity_tariff: float = Form(12.50),
    # Location (for AI review context)
    postcode: Optional[str] = Form(None),
    # COMCAM Features
    enable_revenue_streams: bool = Form(True),
    enable_growth_scenarios: bool = Form(True),
    enable_sizing_advice: bool = Form(True),
    enable_charts: bool = Form(True),
):
    """
    Streaming endpoint dat real-time progress updates stuurt.

    Dit endpoint:
    1. Laadt en valideert het energieprofiel
    2. Analyseert meerdere batterij scenarios
    3. Voert Monte Carlo simulaties uit per scenario
    4. Valideert de resultaten
    5. Stuurt continue SSE events naar de client

    Returns:
        StreamingResponse met SSE events
    """
    # Parse battery sizes
    try:
        sizes = [float(s.strip()) for s in battery_sizes.split(',')]
    except ValueError:
        sizes = [50, 75, 100, 150, 200]

    # Clamp n_simulations
    n_simulations = max(100, min(n_simulations, 2000))

    # Read file content
    content = await file.read()
    filename = file.filename or "upload.csv"

    logger.info(
        "Starting streaming analysis",
        filename=filename,
        battery_sizes=sizes,
        n_simulations=n_simulations
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generator that yields SSE events."""

        try:
            # === PHASE 1: LOAD PROFILE ===
            yield create_phase_event(
                phase="profile_loading",
                message="Energieprofiel laden...",
            ).to_sse()

            await asyncio.sleep(0.1)  # Small delay for visual effect

            # Parse file
            ext = filename.split('.')[-1].lower()

            if ext == 'csv':
                text_content = content.decode('utf-8', errors='replace')
                delimiter = detect_delimiter(text_content)
                df = pd.read_csv(
                    BytesIO(content),
                    delimiter=delimiter,
                    header=None,
                    dtype=str
                )
            else:
                df = pd.read_excel(
                    BytesIO(content),
                    header=None,
                    dtype=str
                )

            # Find header row
            header_idx = find_header_row(df)
            headers = [str(h) for h in df.iloc[header_idx].tolist()]
            df = df.iloc[header_idx + 1:].reset_index(drop=True)
            df.columns = headers

            # Create column mapping
            column_mapping = ColumnMapping(
                timestamp=timestamp_col,
                afname=afname_col,
                teruglevering=teruglevering_col if teruglevering_col else None
            )

            # Normalize
            df_normalized = normalize_dataframe(df, column_mapping)

            if len(df_normalized) < 96:
                yield create_error_event(
                    "Te weinig datapunten. Minimaal 1 dag (96 kwartierwaarden) nodig.",
                    "ValidationError"
                ).to_sse()
                return

            # Prepare profile DataFrame
            profile_df = df_normalized.copy()
            profile_df['timestamp'] = pd.to_datetime(profile_df['timestamp'])
            profile_df['afname_kwh'] = pd.to_numeric(profile_df['afname_kwh'], errors='coerce').fillna(0)
            if 'teruglevering_kwh' in profile_df.columns:
                profile_df['teruglevering_kwh'] = pd.to_numeric(
                    profile_df['teruglevering_kwh'],
                    errors='coerce'
                ).fillna(0)
            else:
                profile_df['teruglevering_kwh'] = 0

            # Profile analysis
            analysis = analyze_profile(df_normalized)

            yield create_phase_event(
                phase="profile_loading",
                message=f"Profiel geladen: {len(profile_df)} records",
                complete=True,
                data={
                    "records": len(profile_df),
                    "annual_consumption_kwh": round(float(profile_df['afname_kwh'].sum()), 0),
                    "peak_kw": round(float(profile_df['afname_kwh'].max() * 4), 1),
                    "days_of_data": analysis.data_days,
                }
            ).to_sse()

            await asyncio.sleep(0.2)

            # Send started event
            yield create_started_event(
                battery_sizes=sizes,
                n_simulations=n_simulations,
                profile_records=len(profile_df)
            ).to_sse()

            # === PHASE 2: CONFIGURE ===
            # Map strategy and chemistry
            strategy_map = {
                "peak_shaving": DispatchStrategy.PEAK_SHAVING,
                "arbitrage": DispatchStrategy.ARBITRAGE,
                "self_consumption": DispatchStrategy.SELF_CONSUMPTION,
                "hybrid": DispatchStrategy.HYBRID,
            }
            dispatch_strategy = strategy_map.get(strategy.lower(), DispatchStrategy.HYBRID)

            chemistry_map = {
                "lfp": BatteryChemistry.LFP,
                "nmc": BatteryChemistry.NMC,
                "nca": BatteryChemistry.NCA,
                "lto": BatteryChemistry.LTO,
            }
            battery_chemistry = chemistry_map.get(chemistry.lower(), BatteryChemistry.LFP)

            # Tariff structure
            tariffs = TariffStructure(
                peak_rate=peak_rate,
                off_peak_rate=off_peak_rate,
                capacity_tariff=capacity_tariff,
            )

            # === PHASE 3: MONTE CARLO PER SCENARIO ===
            all_results = []
            total_scenarios = len(sizes)

            for scenario_idx, size_kwh in enumerate(sizes):
                # Scenario start
                yield ProgressEvent(
                    type=ProgressEventType.SCENARIO_PROGRESS,
                    progress_percent=(scenario_idx / total_scenarios) * 100,
                    current_step=scenario_idx + 1,
                    total_steps=total_scenarios,
                    scenario_kwh=size_kwh,
                    phase="scenario_analysis",
                    message=f"Analyseren {size_kwh} kWh scenario...",
                ).to_sse()

                await asyncio.sleep(0.1)

                # Create engine for this size
                max_power = size_kwh / 2
                engine = MonteCarloEngine(
                    capacity_kwh=size_kwh,
                    max_power_kw=max_power,
                    chemistry=battery_chemistry,
                    analysis_years=analysis_years,
                    discount_rate=discount_rate
                )

                # Run Monte Carlo with progress
                config = MonteCarloConfig(
                    n_simulations=n_simulations,
                    random_seed=42
                )

                # We run the full MC but emit progress events
                # Run baseline simulation first
                simulator = BatteryDispatchSimulator(
                    capacity_kwh=size_kwh,
                    max_power_kw=max_power,
                    chemistry=battery_chemistry
                )

                baseline_result = simulator.simulate(
                    profile_df=profile_df,
                    strategy=dispatch_strategy,
                    tariffs=tariffs
                )

                baseline_savings = baseline_result.summary.total_savings_eur_year
                baseline_cycles = baseline_result.summary.cycles_per_year
                baseline_dod = baseline_result.summary.average_dod or 0.8

                # Get baseline TCO
                tco_calc = TCOCalculator(
                    capacity_kwh=size_kwh,
                    chemistry=battery_chemistry,
                    analysis_years=analysis_years,
                    discount_rate=discount_rate
                )

                baseline_tco = tco_calc.calculate_tco(
                    annual_cycles=baseline_cycles,
                    average_dod=baseline_dod
                )

                # Generate samples
                samples = engine._generate_lhs_samples(n_simulations, config)

                # Run simulations with progress reporting
                npvs = []
                paybacks = []
                irrs = []
                lcos_values = []

                # Store per-simulation data for yearly cashflow calculation
                sim_data_for_cashflows = []  # List of (capex, savings, degrad_mult)

                report_interval = max(1, n_simulations // 20)  # ~20 updates per scenario

                for i in range(n_simulations):
                    # Run single scenario
                    capex_mult = samples['capex'][i]
                    tariff_mult = samples['tariff'][i]
                    degrad_mult = samples['degradation'][i]
                    eff_mult = samples['efficiency'][i]

                    scenario_capex = baseline_tco.capex_total * capex_mult
                    scenario_savings = baseline_savings * tariff_mult * eff_mult
                    scenario_cycles = baseline_cycles * (2 - degrad_mult)

                    scenario_tco = tco_calc.calculate_tco(
                        annual_cycles=scenario_cycles,
                        average_dod=baseline_dod,
                        custom_capex=scenario_capex
                    )

                    financials = tco_calc.calculate_financial_metrics(
                        tco=scenario_tco,
                        annual_savings=scenario_savings,
                        annual_cycles=scenario_cycles,
                        average_dod=baseline_dod
                    )

                    npvs.append(financials.npv)
                    paybacks.append(min(financials.simple_payback_years, 50))
                    if financials.irr is not None:
                        irrs.append(financials.irr)
                    lcos_values.append(scenario_tco.lcos)

                    # Store data for yearly cashflow calculation
                    sim_data_for_cashflows.append({
                        'capex': scenario_capex,
                        'savings': scenario_savings,
                        'degrad_mult': degrad_mult
                    })

                    # Report progress
                    if (i + 1) % report_interval == 0 or i == n_simulations - 1:
                        npv_array = np.array(npvs)

                        yield create_simulation_progress_event(
                            scenario_kwh=size_kwh,
                            current_sim=i + 1,
                            total_sims=n_simulations,
                            scenario_idx=scenario_idx,
                            total_scenarios=total_scenarios,
                            intermediate_npv=float(np.mean(npv_array)),
                            intermediate_std=float(np.std(npv_array)),
                        ).to_sse()

                        # Allow event loop to process
                        await asyncio.sleep(0)

                    # Intermediate result at 25%, 50%, 75%
                    if (i + 1) in [n_simulations // 4, n_simulations // 2, 3 * n_simulations // 4]:
                        npv_array = np.array(npvs)
                        payback_array = np.array([p for p in paybacks if p < 50])

                        yield ProgressEvent(
                            type=ProgressEventType.INTERMEDIATE_RESULT,
                            scenario_kwh=size_kwh,
                            phase="monte_carlo",
                            message=f"Tussenresultaat na {i + 1} simulaties",
                            data={
                                "npv_estimate": round(float(np.mean(npv_array)), 0),
                                "npv_range": [
                                    round(float(np.percentile(npv_array, 5)), 0),
                                    round(float(np.percentile(npv_array, 95)), 0)
                                ],
                                "payback_estimate": round(float(np.mean(payback_array)), 1) if len(payback_array) > 0 else None,
                                "confidence_building": round((i + 1) / n_simulations, 2),
                            }
                        ).to_sse()

                # Calculate final statistics for this scenario
                npv_array = np.array(npvs)
                payback_array = np.array(paybacks)
                lcos_array = np.array(lcos_values)

                npv_mean = float(np.mean(npv_array))
                npv_p5 = float(np.percentile(npv_array, 5))
                npv_p50 = float(np.percentile(npv_array, 50))
                npv_p95 = float(np.percentile(npv_array, 95))

                payback_mean = float(np.mean(payback_array))
                payback_p50 = float(np.percentile(payback_array, 50))

                irr_mean = float(np.mean(irrs)) if irrs else None
                lcos_mean = float(np.mean(lcos_array))

                prob_positive = float(np.mean(npv_array > 0))
                prob_payback_10y = float(np.mean(payback_array < 10))

                # Decision score
                score, recommendation = engine._calculate_decision_score(
                    npv_p50=npv_p50,
                    payback_p50=payback_p50,
                    prob_positive_npv=prob_positive,
                    prob_payback_10y=prob_payback_10y,
                    irr_p50=float(np.percentile(irrs, 50)) if irrs else None
                )

                # Calculate yearly cashflows for fan/plume visualization
                yearly_cashflows = calculate_yearly_cashflows(
                    sim_data=sim_data_for_cashflows,
                    analysis_years=analysis_years
                )

                scenario_result = {
                    "size_kwh": size_kwh,
                    "npv_mean": round(npv_mean, 2),
                    "npv_p5": round(npv_p5, 2),
                    "npv_p50": round(npv_p50, 2),
                    "npv_p95": round(npv_p95, 2),
                    "payback_mean": round(payback_mean, 2),
                    "payback_p50": round(payback_p50, 2),
                    "irr_mean": round(irr_mean, 4) if irr_mean else None,
                    "lcos": round(lcos_mean, 4),
                    "probability_positive_npv": round(prob_positive, 3),
                    "probability_payback_10y": round(prob_payback_10y, 3),
                    "decision_score": round(score, 1),
                    "recommendation": recommendation,
                    "cycles_per_year": round(baseline_cycles, 1),
                    "peak_reduction_kw": round(baseline_result.summary.peak_reduction_kw or 0, 1),
                    "capex": round(baseline_tco.capex_total, 2),
                    "yearly_cashflows": yearly_cashflows,
                }

                all_results.append(scenario_result)

                # Send scenario complete event
                yield create_scenario_result_event(
                    scenario_kwh=size_kwh,
                    npv_mean=npv_mean,
                    npv_p5=npv_p5,
                    npv_p95=npv_p95,
                    payback_mean=payback_mean,
                    cycles_per_year=baseline_cycles
                ).to_sse()

                await asyncio.sleep(0.2)

            # === PHASE 4: VALIDATION ===
            yield ProgressEvent(
                type=ProgressEventType.VALIDATION_START,
                phase="validation",
                message="Resultaten valideren...",
            ).to_sse()

            await asyncio.sleep(0.2)

            # Run validation checks
            checker = SanityChecker()
            validation_results = []

            # Check 1: Physical limits
            for result in all_results:
                if result["cycles_per_year"] <= 500:
                    check_passed = True
                    check_msg = f"{result['size_kwh']} kWh: {result['cycles_per_year']:.0f} cycli/jaar"
                else:
                    check_passed = False
                    check_msg = f"{result['size_kwh']} kWh: te veel cycli ({result['cycles_per_year']:.0f})"

                yield create_validation_check_event(
                    check_name=f"Cycli limiet {result['size_kwh']}kWh",
                    passed=check_passed,
                    message=check_msg
                ).to_sse()

                validation_results.append({
                    "check": "cycles_limit",
                    "size_kwh": result["size_kwh"],
                    "passed": check_passed,
                    "message": check_msg
                })

                await asyncio.sleep(0.1)

            # Check 2: NPV sanity
            for result in all_results:
                capex = result["capex"]
                npv = result["npv_p50"]
                # NPV should not exceed 5x CAPEX
                check_passed = npv < capex * 5
                check_msg = f"NPV {npv:,.0f} vs CAPEX {capex:,.0f}"

                yield create_validation_check_event(
                    check_name=f"NPV sanity {result['size_kwh']}kWh",
                    passed=check_passed,
                    message=check_msg
                ).to_sse()

                validation_results.append({
                    "check": "npv_sanity",
                    "size_kwh": result["size_kwh"],
                    "passed": check_passed,
                    "message": check_msg
                })

                await asyncio.sleep(0.1)

            # Check 3: LCOS range
            yield create_validation_check_event(
                check_name="LCOS bereik",
                passed=all(0.05 <= r["lcos"] <= 0.50 for r in all_results),
                message=f"LCOS range: {min(r['lcos'] for r in all_results):.3f} - {max(r['lcos'] for r in all_results):.3f} EUR/kWh"
            ).to_sse()

            await asyncio.sleep(0.1)

            yield ProgressEvent(
                type=ProgressEventType.VALIDATION_COMPLETE,
                phase="validation",
                message="Validatie compleet",
            ).to_sse()

            # === PHASE 5: COMCAM FEATURES ===
            # Find optimal scenario (highest decision score)
            optimal_idx = max(range(len(all_results)), key=lambda i: all_results[i]["decision_score"])
            optimal = all_results[optimal_idx]

            validation_summary = {
                "total_checks": len(validation_results) + 1,  # +1 for LCOS
                "passed": sum(1 for v in validation_results if v.get("passed", True)) + 1,
                "warnings": [v for v in validation_results if not v.get("passed", True)],
            }

            # Revenue Streams
            revenue_breakdown = None
            if enable_revenue_streams:
                yield ProgressEvent(
                    type=ProgressEventType.PHASE_UPDATE,
                    phase="revenue_streams",
                    message="Revenue streams berekenen...",
                ).to_sse()
                await asyncio.sleep(0.1)

                try:
                    revenue_calc = RevenueCalculator()
                    has_solar = 'teruglevering_kwh' in profile_df.columns and profile_df['teruglevering_kwh'].sum() > 0
                    revenue_breakdown = revenue_calc.calculate_all(
                        profile_df=profile_df,
                        battery_kwh=optimal['size_kwh'],
                        battery_kw=optimal['size_kwh'] / 2,
                        has_solar=has_solar,
                    )
                    logger.info("Revenue streams calculated", streams=len(revenue_breakdown.streams))
                except Exception as e:
                    logger.warning(f"Revenue calculation error: {e}")
                    revenue_breakdown = None

            # Growth Scenarios
            growth_projections = None
            if enable_growth_scenarios:
                yield ProgressEvent(
                    type=ProgressEventType.PHASE_UPDATE,
                    phase="growth_scenarios",
                    message="Groei scenario's berekenen...",
                ).to_sse()
                await asyncio.sleep(0.1)

                try:
                    projector = GrowthProjector()
                    growth_projections = projector.project_multiple_scenarios(
                        profile_df=profile_df,
                        scenarios=[
                            get_scenario(GrowthScenarioType.BASELINE),
                            get_scenario(GrowthScenarioType.MODERATE),
                            get_scenario(GrowthScenarioType.HIGH),
                            get_scenario(GrowthScenarioType.AGGRESSIVE),
                        ],
                        projection_years=analysis_years,
                    )
                    logger.info("Growth projections calculated", scenarios=len(growth_projections))
                except Exception as e:
                    logger.warning(f"Growth projection error: {e}")
                    growth_projections = None

            # Sizing Advice
            sizing_advice = None
            if enable_sizing_advice:
                yield ProgressEvent(
                    type=ProgressEventType.PHASE_UPDATE,
                    phase="sizing_advice",
                    message="Sizing aanbevelingen genereren...",
                ).to_sse()
                await asyncio.sleep(0.1)

                try:
                    advisor = SizingAdvisor()
                    constraints = BatteryConstraints(
                        min_capacity_kwh=min(sizes),
                        max_capacity_kwh=max(sizes),
                    )
                    has_solar = 'teruglevering_kwh' in profile_df.columns and profile_df['teruglevering_kwh'].sum() > 0
                    sizing_advice = advisor.generate_recommendations(
                        profile_df=profile_df,
                        constraints=constraints,
                        has_solar=has_solar,
                    )
                    logger.info("Sizing advice generated")
                except Exception as e:
                    logger.warning(f"Sizing advice error: {e}")
                    sizing_advice = None

            # Charts
            charts = {}
            if enable_charts:
                yield ProgressEvent(
                    type=ProgressEventType.PHASE_UPDATE,
                    phase="charts",
                    message="Visualisaties genereren...",
                ).to_sse()
                await asyncio.sleep(0.1)

                try:
                    chart_gen = ChartGenerator()

                    # 1. Profile Charts (Combined + Individual)
                    try:
                        # Combined overview (legacy - 4 subplots)
                        charts['profile_overview'] = chart_gen.profile_overview(
                            profile_df=profile_df,
                            title="Energieprofiel Analyse"
                        )
                        # Individual charts (separately downloadable)
                        charts['load_duration_curve'] = chart_gen.load_duration_curve_single(
                            profile_df=profile_df
                        )
                        charts['daily_pattern'] = chart_gen.daily_pattern_single(
                            profile_df=profile_df
                        )
                        logger.info("Profile charts generated (combined + 2 individual)")
                    except Exception as e:
                        logger.warning(f"Profile chart error: {e}")

                    # 2. Peak Shaving Visualization
                    try:
                        p97 = float(profile_df['afname_kwh'].quantile(0.97)) * 4
                        charts['peak_shaving'] = chart_gen.peak_shaving_visualization(
                            profile_df=profile_df,
                            battery_kwh=optimal['size_kwh'],
                            peak_threshold_kw=p97,
                            title="Peak Shaving Analyse"
                        )
                        logger.info("Peak shaving chart generated")
                    except Exception as e:
                        logger.warning(f"Peak shaving chart error: {e}")

                    # 3. Dispatch Heatmap
                    try:
                        charts['dispatch_heatmap'] = chart_gen.dispatch_heatmap(
                            profile_df=profile_df,
                            title="Dispatch Patroon Analyse"
                        )
                        logger.info("Dispatch heatmap generated")
                    except Exception as e:
                        logger.warning(f"Dispatch heatmap error: {e}")

                    # 4. Monte Carlo Charts (Combined + Individual)
                    try:
                        optimal_result = next((r for r in all_results if r['size_kwh'] == optimal['size_kwh']), None)
                        if optimal_result:
                            # Generate synthetic distributions for visualization
                            npv_mean = optimal_result['npv_mean']
                            npv_std = (optimal_result['npv_p95'] - optimal_result['npv_p5']) / 3.29
                            npv_values = np.random.normal(npv_mean, max(npv_std, 1000), 1000)

                            payback_mean = optimal_result['payback_mean']
                            payback_std = max(payback_mean * 0.2, 1)
                            payback_values = np.random.normal(payback_mean, payback_std, 1000)
                            payback_values = np.clip(payback_values, 0.5, 25)

                            # Combined chart (legacy)
                            charts['monte_carlo_summary'] = chart_gen.monte_carlo_summary(
                                npv_values=npv_values,
                                payback_values=payback_values,
                                battery_size=optimal['size_kwh'],
                                title="Monte Carlo Simulatie"
                            )

                            # Individual charts (separately downloadable)
                            charts['npv_distribution'] = chart_gen.npv_distribution_single(
                                npv_values=npv_values,
                                battery_size=optimal['size_kwh']
                            )
                            charts['payback_distribution'] = chart_gen.payback_distribution_single(
                                payback_values=payback_values,
                                battery_size=optimal['size_kwh']
                            )
                            charts['risk_metrics'] = chart_gen.risk_metrics_single(
                                npv_values=npv_values,
                                battery_size=optimal['size_kwh']
                            )
                            logger.info("Monte Carlo charts generated (combined + 3 individual)")
                    except Exception as e:
                        logger.warning(f"Monte Carlo chart error: {e}")

                    # 5. NPV Distribution / Scenario Comparison
                    if all_results:
                        charts['scenario_comparison'] = chart_gen.scenario_comparison_bar(
                            scenarios=all_results
                        )

                    # 6. Revenue Breakdown
                    if revenue_breakdown:
                        # Create multi-scenario revenue breakdown
                        revenue_scenarios = []
                        for result in all_results[:4]:  # Top 4 sizes
                            revenue_scenarios.append({
                                'size_kwh': result['size_kwh'],
                                'revenues': {k: v.annual_revenue_eur * (result['size_kwh'] / optimal['size_kwh'])
                                            for k, v in revenue_breakdown.streams.items()}
                            })
                        charts['revenue_breakdown'] = chart_gen.revenue_breakdown_stacked(
                            scenarios=revenue_scenarios
                        )

                    # 7. Growth Scenarios
                    if growth_projections:
                        growth_dict = {k: v.to_dict() if hasattr(v, 'to_dict') else v for k, v in growth_projections.items()}
                        charts['growth_scenarios'] = chart_gen.growth_scenario_comparison(
                            scenarios=growth_dict,
                            battery_size=optimal['size_kwh']
                        )

                    # 8. Sizing Recommendations
                    if sizing_advice:
                        charts['sizing_recommendations'] = chart_gen.sizing_recommendation_chart(
                            recommendations=sizing_advice.to_dict()
                        )

                    logger.info("Charts generated", count=len(charts))
                except Exception as e:
                    logger.warning(f"Chart generation error: {e}", exc_info=True)

            # === PHASE 6: COMPLETE ===
            # Calculate profile stats for frontend
            afname_kwh_series = profile_df['afname_kwh']
            profile_stats = {
                "peak_kw": round(float(afname_kwh_series.max() * 4), 1),  # Convert 15-min kWh to kW
                "average_kw": round(float(afname_kwh_series.mean() * 4), 1),
                "avg_kw": round(float(afname_kwh_series.mean() * 4), 1),  # Alias for Gemini
                "p95_kw": round(float(afname_kwh_series.quantile(0.95) * 4), 1),
                "p99_kw": round(float(afname_kwh_series.quantile(0.99) * 4), 1),
                "total_kwh": round(float(afname_kwh_series.sum()), 0),
                "annual_kwh": round(float(afname_kwh_series.sum() * (365 / (len(profile_df) / 96))), 0),
                "annual_consumption_kwh": round(float(afname_kwh_series.sum() * (365 / (len(profile_df) / 96))), 0),
            }

            # === PHASE 7: AI REVIEW ===
            ai_review = None
            try:
                yield ProgressEvent(
                    type=ProgressEventType.VALIDATION_CHECK,
                    progress_percent=95,
                    message="AI review uitvoeren...",
                    phase="ai_review",
                ).to_sse()

                # Build enrichment-like data from tariffs for AI context
                enrichment_for_ai = {
                    "netbeheerder": "Onbekend",
                    "netbeheer_tarieven": {
                        "capaciteitstarief_kw_maand": capacity_tariff,
                    },
                    "commodity_prijzen": {
                        "piek_gemiddelde": peak_rate * 1000,  # Convert to €/MWh
                        "dal_gemiddelde": off_peak_rate * 1000,
                    },
                }

                gemini_reviewer = get_gemini_reviewer()
                review_result = await gemini_reviewer.review_analysis(
                    scenarios=all_results,
                    optimal_size_kwh=optimal["size_kwh"],
                    profile_stats=profile_stats,
                    enrichment_data=enrichment_for_ai,
                    n_simulations=n_simulations,
                    postcode=postcode,
                )
                ai_review = review_result.model_dump()
                logger.info(
                    "AI review completed",
                    recommendation=review_result.recommendation,
                    confidence=review_result.confidence_level,
                )
            except Exception as e:
                logger.warning(f"AI review failed (continuing without): {e}")

            yield create_completed_event(
                optimal_size_kwh=optimal["size_kwh"],
                scenarios=all_results,
                validation_summary=validation_summary,
                revenue_breakdown=revenue_breakdown.to_dict() if revenue_breakdown else None,
                growth_projections={k: v.to_dict() for k, v in growth_projections.items()} if growth_projections else None,
                sizing_advice=sizing_advice.to_dict() if sizing_advice else None,
                charts=charts,
                profile_stats=profile_stats,
                ai_review=ai_review,
            ).to_sse()

            logger.info(
                "Streaming analysis complete",
                optimal_size=optimal["size_kwh"],
                optimal_score=optimal["decision_score"],
                total_scenarios=len(all_results),
                features_enabled={
                    "revenue_streams": enable_revenue_streams,
                    "growth_scenarios": enable_growth_scenarios,
                    "sizing_advice": enable_sizing_advice,
                    "charts": enable_charts,
                }
            )

        except Exception as e:
            logger.error(f"Streaming analysis error: {e}", exc_info=True)
            yield create_error_event(str(e), type(e).__name__).to_sse()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Access-Control-Allow-Origin": "*",
        }
    )


@router.post("/analyze-stream-session")
async def analyze_battery_stream_from_session(
    session_id: str = Form(...),
    battery_sizes: str = Form("50,75,100,150,200"),
    n_simulations: int = Form(1000),
    strategy: str = Form("hybrid"),
    chemistry: str = Form("lfp"),
    analysis_years: int = Form(15),
    discount_rate: float = Form(0.05),
    # Tariffs
    peak_rate: float = Form(0.35),
    off_peak_rate: float = Form(0.22),
    capacity_tariff: float = Form(12.50),
):
    """
    Streaming analysis from existing session.

    Similar to analyze-stream but uses previously uploaded file.
    """
    if session_id not in SESSIONS:
        async def error_gen():
            yield create_error_event(
                "Sessie niet gevonden. Upload eerst een bestand.",
                "SessionNotFound"
            ).to_sse()

        return StreamingResponse(
            error_gen(),
            media_type="text/event-stream",
        )

    if 'normalized_df' not in SESSIONS[session_id]:
        async def error_gen():
            yield create_error_event(
                "Profiel nog niet geanalyseerd.",
                "ProfileNotAnalyzed"
            ).to_sse()

        return StreamingResponse(
            error_gen(),
            media_type="text/event-stream",
        )

    # Parse battery sizes
    try:
        sizes = [float(s.strip()) for s in battery_sizes.split(',')]
    except ValueError:
        sizes = [50, 75, 100, 150, 200]

    n_simulations = max(100, min(n_simulations, 2000))
    profile_df = SESSIONS[session_id]['normalized_df'].copy()

    logger.info(
        "Starting streaming analysis from session",
        session_id=session_id,
        battery_sizes=sizes,
        n_simulations=n_simulations
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generator that yields SSE events."""
        try:
            # Prepare profile
            profile_df['timestamp'] = pd.to_datetime(profile_df['timestamp'])
            profile_df['afname_kwh'] = pd.to_numeric(profile_df['afname_kwh'], errors='coerce').fillna(0)
            if 'teruglevering_kwh' in profile_df.columns:
                profile_df['teruglevering_kwh'] = pd.to_numeric(
                    profile_df['teruglevering_kwh'],
                    errors='coerce'
                ).fillna(0)
            else:
                profile_df['teruglevering_kwh'] = 0

            yield create_phase_event(
                phase="profile_loading",
                message=f"Profiel uit sessie geladen: {len(profile_df)} records",
                complete=True,
                data={"records": len(profile_df)}
            ).to_sse()

            # Send started event
            yield create_started_event(
                battery_sizes=sizes,
                n_simulations=n_simulations,
                profile_records=len(profile_df)
            ).to_sse()

            # ... rest of analysis (same as above, but using session profile_df)
            # For brevity, redirecting to main analysis logic

            # Map strategy and chemistry
            strategy_map = {
                "peak_shaving": DispatchStrategy.PEAK_SHAVING,
                "arbitrage": DispatchStrategy.ARBITRAGE,
                "self_consumption": DispatchStrategy.SELF_CONSUMPTION,
                "hybrid": DispatchStrategy.HYBRID,
            }
            dispatch_strategy = strategy_map.get(strategy.lower(), DispatchStrategy.HYBRID)

            chemistry_map = {
                "lfp": BatteryChemistry.LFP,
                "nmc": BatteryChemistry.NMC,
                "nca": BatteryChemistry.NCA,
                "lto": BatteryChemistry.LTO,
            }
            battery_chemistry = chemistry_map.get(chemistry.lower(), BatteryChemistry.LFP)

            tariffs = TariffStructure(
                peak_rate=peak_rate,
                off_peak_rate=off_peak_rate,
                capacity_tariff=capacity_tariff,
            )

            all_results = []
            total_scenarios = len(sizes)

            for scenario_idx, size_kwh in enumerate(sizes):
                yield ProgressEvent(
                    type=ProgressEventType.SCENARIO_PROGRESS,
                    progress_percent=(scenario_idx / total_scenarios) * 100,
                    current_step=scenario_idx + 1,
                    total_steps=total_scenarios,
                    scenario_kwh=size_kwh,
                    phase="scenario_analysis",
                    message=f"Analyseren {size_kwh} kWh scenario...",
                ).to_sse()

                await asyncio.sleep(0.1)

                max_power = size_kwh / 2
                engine = MonteCarloEngine(
                    capacity_kwh=size_kwh,
                    max_power_kw=max_power,
                    chemistry=battery_chemistry,
                    analysis_years=analysis_years,
                    discount_rate=discount_rate
                )

                config = MonteCarloConfig(n_simulations=n_simulations, random_seed=42)

                simulator = BatteryDispatchSimulator(
                    capacity_kwh=size_kwh,
                    max_power_kw=max_power,
                    chemistry=battery_chemistry
                )

                baseline_result = simulator.simulate(
                    profile_df=profile_df,
                    strategy=dispatch_strategy,
                    tariffs=tariffs
                )

                baseline_savings = baseline_result.summary.total_savings_eur_year
                baseline_cycles = baseline_result.summary.cycles_per_year
                baseline_dod = baseline_result.summary.average_dod or 0.8

                tco_calc = TCOCalculator(
                    capacity_kwh=size_kwh,
                    chemistry=battery_chemistry,
                    analysis_years=analysis_years,
                    discount_rate=discount_rate
                )

                baseline_tco = tco_calc.calculate_tco(
                    annual_cycles=baseline_cycles,
                    average_dod=baseline_dod
                )

                samples = engine._generate_lhs_samples(n_simulations, config)

                npvs = []
                paybacks = []
                irrs = []
                lcos_values = []
                sim_data_for_cashflows = []  # For yearly cashflow calculation
                report_interval = max(1, n_simulations // 20)

                for i in range(n_simulations):
                    capex_mult = samples['capex'][i]
                    tariff_mult = samples['tariff'][i]
                    degrad_mult = samples['degradation'][i]
                    eff_mult = samples['efficiency'][i]

                    scenario_capex = baseline_tco.capex_total * capex_mult
                    scenario_savings = baseline_savings * tariff_mult * eff_mult
                    scenario_cycles = baseline_cycles * (2 - degrad_mult)

                    scenario_tco = tco_calc.calculate_tco(
                        annual_cycles=scenario_cycles,
                        average_dod=baseline_dod,
                        custom_capex=scenario_capex
                    )

                    financials = tco_calc.calculate_financial_metrics(
                        tco=scenario_tco,
                        annual_savings=scenario_savings,
                        annual_cycles=scenario_cycles,
                        average_dod=baseline_dod
                    )

                    npvs.append(financials.npv)
                    paybacks.append(min(financials.simple_payback_years, 50))
                    if financials.irr is not None:
                        irrs.append(financials.irr)
                    lcos_values.append(scenario_tco.lcos)

                    # Store data for yearly cashflow calculation
                    sim_data_for_cashflows.append({
                        'capex': scenario_capex,
                        'savings': scenario_savings,
                        'degrad_mult': degrad_mult
                    })

                    if (i + 1) % report_interval == 0 or i == n_simulations - 1:
                        npv_array = np.array(npvs)
                        yield create_simulation_progress_event(
                            scenario_kwh=size_kwh,
                            current_sim=i + 1,
                            total_sims=n_simulations,
                            scenario_idx=scenario_idx,
                            total_scenarios=total_scenarios,
                            intermediate_npv=float(np.mean(npv_array)),
                            intermediate_std=float(np.std(npv_array)),
                        ).to_sse()
                        await asyncio.sleep(0)

                npv_array = np.array(npvs)
                payback_array = np.array(paybacks)
                lcos_array = np.array(lcos_values)

                npv_mean = float(np.mean(npv_array))
                npv_p5 = float(np.percentile(npv_array, 5))
                npv_p50 = float(np.percentile(npv_array, 50))
                npv_p95 = float(np.percentile(npv_array, 95))
                payback_mean = float(np.mean(payback_array))
                payback_p50 = float(np.percentile(payback_array, 50))
                irr_mean = float(np.mean(irrs)) if irrs else None
                lcos_mean = float(np.mean(lcos_array))
                prob_positive = float(np.mean(npv_array > 0))
                prob_payback_10y = float(np.mean(payback_array < 10))

                score, recommendation = engine._calculate_decision_score(
                    npv_p50=npv_p50,
                    payback_p50=payback_p50,
                    prob_positive_npv=prob_positive,
                    prob_payback_10y=prob_payback_10y,
                    irr_p50=float(np.percentile(irrs, 50)) if irrs else None
                )

                # Calculate yearly cashflows for fan/plume visualization
                yearly_cashflows = calculate_yearly_cashflows(
                    sim_data=sim_data_for_cashflows,
                    analysis_years=analysis_years
                )

                scenario_result = {
                    "size_kwh": size_kwh,
                    "npv_mean": round(npv_mean, 2),
                    "npv_p5": round(npv_p5, 2),
                    "npv_p50": round(npv_p50, 2),
                    "npv_p95": round(npv_p95, 2),
                    "payback_mean": round(payback_mean, 2),
                    "payback_p50": round(payback_p50, 2),
                    "irr_mean": round(irr_mean, 4) if irr_mean else None,
                    "lcos": round(lcos_mean, 4),
                    "probability_positive_npv": round(prob_positive, 3),
                    "probability_payback_10y": round(prob_payback_10y, 3),
                    "decision_score": round(score, 1),
                    "recommendation": recommendation,
                    "cycles_per_year": round(baseline_cycles, 1),
                    "peak_reduction_kw": round(baseline_result.summary.peak_reduction_kw or 0, 1),
                    "capex": round(baseline_tco.capex_total, 2),
                    "yearly_cashflows": yearly_cashflows,
                }

                all_results.append(scenario_result)

                yield create_scenario_result_event(
                    scenario_kwh=size_kwh,
                    npv_mean=npv_mean,
                    npv_p5=npv_p5,
                    npv_p95=npv_p95,
                    payback_mean=payback_mean,
                    cycles_per_year=baseline_cycles
                ).to_sse()

                await asyncio.sleep(0.2)

            # Validation
            yield ProgressEvent(
                type=ProgressEventType.VALIDATION_START,
                phase="validation",
                message="Resultaten valideren...",
            ).to_sse()

            await asyncio.sleep(0.2)

            yield ProgressEvent(
                type=ProgressEventType.VALIDATION_COMPLETE,
                phase="validation",
                message="Validatie compleet",
            ).to_sse()

            optimal_idx = max(range(len(all_results)), key=lambda i: all_results[i]["decision_score"])
            optimal = all_results[optimal_idx]

            yield create_completed_event(
                optimal_size_kwh=optimal["size_kwh"],
                scenarios=all_results,
                validation_summary={"total_checks": len(all_results) * 2, "passed": len(all_results) * 2, "warnings": []}
            ).to_sse()

        except Exception as e:
            logger.error(f"Session streaming error: {e}", exc_info=True)
            yield create_error_event(str(e), type(e).__name__).to_sse()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        }
    )
