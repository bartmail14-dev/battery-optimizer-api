"""
===============================================================================
PROFILE ANALYSIS ENDPOINTS
===============================================================================

Endpoints voor energieprofiel analyse en Monte Carlo simulatie.

Belangrijkste endpoints:
- POST /analyze: Basis profiel analyse
- POST /analyze/monte-carlo: Volledige Monte Carlo simulatie
- GET /analyze/{session_id}/hourly: Uurlijkse aggregatie
- GET /analyze/{session_id}/load-duration: Load duration curve

NOTITIE:
- ALLE berekeningen gebeuren in de backend (Python)
- Frontend doet ALLEEN visualisatie
- Monte Carlo runtime: 30-120 seconden (verwacht)
===============================================================================
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import structlog
import pandas as pd
from io import BytesIO

from app.models.schemas import AnalyzeRequest, AnalysisResult, ColumnMapping
from app.core.parser import normalize_dataframe
from app.core.analyzer import analyze_profile
from app.api.routes.upload import SESSIONS
from app.engine import MonteCarloEngine, BatteryDispatchSimulator, TCOCalculator
from app.engine.simulation import TariffStructure, DispatchStrategy
from app.engine.degradation import BatteryChemistry
from app.validation import SanityChecker

router = APIRouter()
logger = structlog.get_logger()


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class TariffConfig(BaseModel):
    """Tarief configuratie voor simulatie."""
    peak_rate: float = Field(default=0.35, ge=0, description="€/kWh piek")
    off_peak_rate: float = Field(default=0.22, ge=0, description="€/kWh dal")
    peak_hours_start: int = Field(default=7, ge=0, le=23)
    peak_hours_end: int = Field(default=21, ge=0, le=23)
    capacity_tariff: float = Field(default=12.50, ge=0, description="€/kW/maand")
    feed_in_tariff: float = Field(default=0.08, ge=0, description="€/kWh teruglevering")


class BatteryConfigRequest(BaseModel):
    """Batterij configuratie voor simulatie."""
    capacity_kwh: float = Field(gt=0, description="Batterijcapaciteit in kWh")
    max_power_kw: Optional[float] = Field(default=None, description="Max vermogen in kW (default: capacity/2)")
    chemistry: str = Field(default="lfp", description="Chemie: lfp, nmc, nca, lto")
    min_soc: float = Field(default=0.10, ge=0, le=1)
    max_soc: float = Field(default=0.90, ge=0, le=1)


class MonteCarloRequest(BaseModel):
    """Request voor Monte Carlo analyse."""
    session_id: str
    battery: BatteryConfigRequest
    tariffs: TariffConfig = Field(default_factory=TariffConfig)
    strategy: str = Field(default="hybrid", description="Strategie: peak_shaving, arbitrage, self_consumption, hybrid")
    analysis_years: int = Field(default=15, ge=1, le=25)
    discount_rate: float = Field(default=0.05, ge=0, le=0.3)
    n_simulations: int = Field(default=1000, ge=100, le=5000)
    custom_capex: Optional[float] = Field(default=None, description="Override CAPEX in €")


class OptimizeSizeRequest(BaseModel):
    """Request voor optimale batterijgrootte."""
    session_id: str
    tariffs: TariffConfig = Field(default_factory=TariffConfig)
    strategy: str = Field(default="hybrid")
    chemistry: str = Field(default="lfp")
    analysis_years: int = Field(default=15)
    discount_rate: float = Field(default=0.05)
    min_capacity_kwh: Optional[float] = Field(default=None)
    max_capacity_kwh: Optional[float] = Field(default=None)
    n_sizes: int = Field(default=10, ge=3, le=20)
    mc_simulations_per_size: int = Field(default=100, ge=50, le=500)


@router.post("/analyze", response_model=AnalysisResult)
async def analyze_energy_profile(request: AnalyzeRequest):
    """
    Analyze energy profile and return statistics.

    Requires a valid session_id from a previous upload.
    """
    session_id = request.session_id

    if session_id not in SESSIONS:
        raise HTTPException(
            status_code=404,
            detail="Sessie niet gevonden. Upload eerst een bestand."
        )

    session = SESSIONS[session_id]
    contents = session['contents']
    filename = session['filename']

    logger.info("Starting profile analysis", session_id=session_id)

    try:
        # Reload and parse the file
        ext = filename.split('.')[-1].lower()

        if ext == 'csv':
            # Detect delimiter
            text_content = contents.decode('utf-8', errors='replace')
            from app.core.parser import detect_delimiter, find_header_row
            delimiter = detect_delimiter(text_content)

            df = pd.read_csv(
                BytesIO(contents),
                delimiter=delimiter,
                header=None,
                dtype=str
            )
        else:
            df = pd.read_excel(
                BytesIO(contents),
                header=None,
                dtype=str
            )

        # Find header row
        from app.core.parser import find_header_row
        header_idx = find_header_row(df)
        headers = [str(h) for h in df.iloc[header_idx].tolist()]
        df = df.iloc[header_idx + 1:].reset_index(drop=True)
        df.columns = headers

        # Normalize using provided mapping
        df_normalized = normalize_dataframe(df, request.column_mapping)

        if len(df_normalized) < 96:
            raise HTTPException(
                status_code=400,
                detail="Te weinig geldige datapunten. Minimaal 1 dag (96 kwartierwaarden) nodig."
            )

        # Store normalized data in session for optimization
        SESSIONS[session_id]['normalized_df'] = df_normalized

        # Analyze profile
        analysis = analyze_profile(df_normalized)

        logger.info(
            "Profile analysis complete",
            session_id=session_id,
            total_kwh=analysis.total_afname_kwh,
            peak_kw=analysis.peak_afname_kw
        )

        return AnalysisResult(
            success=True,
            session_id=session_id,
            analysis=analysis,
            error=None
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Analysis failed", session_id=session_id, error=str(e))
        return AnalysisResult(
            success=False,
            session_id=session_id,
            analysis=None,
            error=str(e)
        )


@router.get("/analyze/{session_id}/hourly")
async def get_hourly_profile(session_id: str):
    """Get hourly aggregated profile data."""
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Sessie niet gevonden")

    if 'normalized_df' not in SESSIONS[session_id]:
        raise HTTPException(
            status_code=400,
            detail="Profiel nog niet geanalyseerd. Roep eerst /analyze aan."
        )

    df = SESSIONS[session_id]['normalized_df']
    analysis = analyze_profile(df)

    return {
        "hourly_profile": [h.model_dump() for h in analysis.hourly_profile]
    }


@router.get("/analyze/{session_id}/load-duration")
async def get_load_duration_curve(session_id: str):
    """Get load duration curve data."""
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Sessie niet gevonden")

    if 'normalized_df' not in SESSIONS[session_id]:
        raise HTTPException(
            status_code=400,
            detail="Profiel nog niet geanalyseerd. Roep eerst /analyze aan."
        )

    df = SESSIONS[session_id]['normalized_df']

    from app.core.analyzer import calculate_load_duration_curve
    ldc = calculate_load_duration_curve(df)

    return {"load_duration_curve": ldc}


# =============================================================================
# MONTE CARLO ENDPOINT
# =============================================================================

@router.post("/analyze/monte-carlo")
async def run_monte_carlo_analysis(request: MonteCarloRequest):
    """
    Voer volledige Monte Carlo simulatie uit.

    Dit endpoint voert 1000+ simulaties uit met parametervariatie om
    een robuuste inschatting te geven van financiële resultaten.

    Runtime: 30-120 seconden afhankelijk van profiel grootte.

    Returns:
        Complete analyse met:
        - NPV distributie (P10, P50, P90)
        - Payback distributie
        - IRR distributie
        - LCOS
        - Decision score (0-100)
        - Aanbeveling (GO/CAUTION/NO-GO)
        - Histogram data voor visualisatie
    """
    session_id = request.session_id

    if session_id not in SESSIONS:
        raise HTTPException(
            status_code=404,
            detail="Sessie niet gevonden. Upload eerst een bestand."
        )

    if 'normalized_df' not in SESSIONS[session_id]:
        raise HTTPException(
            status_code=400,
            detail="Profiel nog niet geanalyseerd. Roep eerst /analyze aan."
        )

    df = SESSIONS[session_id]['normalized_df']

    logger.info(
        "Starting Monte Carlo analysis",
        session_id=session_id,
        capacity_kwh=request.battery.capacity_kwh,
        n_simulations=request.n_simulations
    )

    try:
        # === VALIDEER INPUT ===
        checker = SanityChecker()

        # Valideer profiel
        profile_validation = checker.validate_profile(df)
        if not profile_validation.is_valid:
            return {
                "success": False,
                "error": "Profile validation failed",
                "validation": profile_validation.to_dict()
            }

        # Map chemistry string naar enum
        chemistry_map = {
            "lfp": BatteryChemistry.LFP,
            "nmc": BatteryChemistry.NMC,
            "nca": BatteryChemistry.NCA,
            "lto": BatteryChemistry.LTO,
        }
        chemistry = chemistry_map.get(request.battery.chemistry.lower(), BatteryChemistry.LFP)

        # Map strategy string naar enum
        strategy_map = {
            "peak_shaving": DispatchStrategy.PEAK_SHAVING,
            "arbitrage": DispatchStrategy.ARBITRAGE,
            "self_consumption": DispatchStrategy.SELF_CONSUMPTION,
            "hybrid": DispatchStrategy.HYBRID,
        }
        strategy = strategy_map.get(request.strategy.lower(), DispatchStrategy.HYBRID)

        # Maak tarief structuur
        tariffs = TariffStructure(
            peak_rate=request.tariffs.peak_rate,
            off_peak_rate=request.tariffs.off_peak_rate,
            peak_hours_start=request.tariffs.peak_hours_start,
            peak_hours_end=request.tariffs.peak_hours_end,
            capacity_tariff=request.tariffs.capacity_tariff,
            feed_in_tariff=request.tariffs.feed_in_tariff
        )

        # === BEREID PROFIEL DATA VOOR ===
        # Converteer naar formaat voor engine
        profile_df = df.copy()
        profile_df['timestamp'] = pd.to_datetime(profile_df['timestamp'])
        profile_df['afname_kwh'] = pd.to_numeric(profile_df['afname_kwh'], errors='coerce').fillna(0)
        if 'teruglevering_kwh' in profile_df.columns:
            profile_df['teruglevering_kwh'] = pd.to_numeric(
                profile_df['teruglevering_kwh'],
                errors='coerce'
            ).fillna(0)
        else:
            profile_df['teruglevering_kwh'] = 0

        # === INITIALISEER ENGINE ===
        max_power = request.battery.max_power_kw or (request.battery.capacity_kwh / 2)

        engine = MonteCarloEngine(
            capacity_kwh=request.battery.capacity_kwh,
            max_power_kw=max_power,
            chemistry=chemistry,
            analysis_years=request.analysis_years,
            discount_rate=request.discount_rate,
            custom_capex=request.custom_capex
        )

        # === RUN MONTE CARLO ===
        from app.engine.monte_carlo import MonteCarloConfig

        config = MonteCarloConfig(
            n_simulations=request.n_simulations,
            random_seed=42  # Voor reproduceerbaarheid
        )

        mc_result = engine.run(
            profile_df=profile_df,
            tariffs=tariffs,
            strategy=strategy,
            config=config
        )

        # === RUN BASELINE SIMULATIE (voor details) ===
        simulator = BatteryDispatchSimulator(
            capacity_kwh=request.battery.capacity_kwh,
            max_power_kw=max_power,
            chemistry=chemistry,
            min_soc=request.battery.min_soc,
            max_soc=request.battery.max_soc
        )

        baseline_result = simulator.simulate(
            profile_df=profile_df,
            strategy=strategy,
            tariffs=tariffs
        )

        # === BEREKEN TCO DETAILS ===
        tco_calc = TCOCalculator(
            capacity_kwh=request.battery.capacity_kwh,
            chemistry=chemistry,
            analysis_years=request.analysis_years,
            discount_rate=request.discount_rate
        )

        tco_result = tco_calc.calculate_tco(
            annual_cycles=baseline_result.summary.cycles_per_year,
            average_dod=baseline_result.summary.average_dod or 0.8,
            custom_capex=request.custom_capex
        )

        # === VALIDEER RESULTATEN ===
        results_validation = checker.validate_results(
            capex=tco_result.capex_total,
            capex_per_kwh=tco_result.capex_per_kwh,
            lcos=tco_result.lcos,
            annual_savings=baseline_result.summary.total_savings_eur_year,
            payback_years=mc_result.payback_p50,
            npv=mc_result.npv_p50,
            irr=mc_result.irr_p50,
            cycles_per_year=baseline_result.summary.cycles_per_year,
            efficiency=baseline_result.summary.average_efficiency,
            capacity_kwh=request.battery.capacity_kwh
        )

        logger.info(
            "Monte Carlo analysis complete",
            session_id=session_id,
            decision_score=mc_result.decision_score,
            recommendation=mc_result.recommendation,
            computation_time=mc_result.computation_time_seconds
        )

        # === BUILD RESPONSE ===
        return {
            "success": True,
            "session_id": session_id,

            # Monte Carlo results
            "monte_carlo": mc_result.to_dict(),

            # Baseline simulation details
            "simulation": {
                "total_charged_kwh": baseline_result.summary.total_charged_kwh,
                "total_discharged_kwh": baseline_result.summary.total_discharged_kwh,
                "total_losses_kwh": baseline_result.summary.total_losses_kwh,
                "average_efficiency": baseline_result.summary.average_efficiency,
                "cycles_per_year": baseline_result.summary.cycles_per_year,
                "average_dod": baseline_result.summary.average_dod,
                "peak_reduction_kw": baseline_result.summary.peak_reduction_kw,
                "original_peak_kw": baseline_result.summary.original_peak_kw,
                "new_peak_kw": baseline_result.summary.new_peak_kw,
                "energy_savings_eur_year": baseline_result.summary.energy_savings_eur,
                "peak_savings_eur_year": baseline_result.summary.peak_savings_eur_year,
                "total_savings_eur_year": baseline_result.summary.total_savings_eur_year,
                "strategy_breakdown": baseline_result.summary.strategy_breakdown,
                "data_days": baseline_result.summary.data_days,
                "data_points": baseline_result.summary.data_points,
            },

            # TCO details
            "tco": tco_result.to_dict(),

            # Configuration used
            "config": {
                "capacity_kwh": request.battery.capacity_kwh,
                "max_power_kw": max_power,
                "chemistry": chemistry.value,
                "strategy": strategy.value,
                "analysis_years": request.analysis_years,
                "discount_rate": request.discount_rate,
                "n_simulations": request.n_simulations,
            },

            # Validation
            "validation": results_validation.to_dict(),

            # Chemistry info voor transparantie
            "chemistry_info": engine.degradation_model.get_chemistry_info(),
        }

    except Exception as e:
        logger.error(
            "Monte Carlo analysis failed",
            session_id=session_id,
            error=str(e),
            exc_info=True
        )
        return {
            "success": False,
            "session_id": session_id,
            "error": str(e)
        }


@router.post("/analyze/optimize-size")
async def optimize_battery_size(request: OptimizeSizeRequest):
    """
    Vind optimale batterijgrootte met Monte Carlo per grootte.

    Evalueert meerdere batterijgroottes en geeft de optimale
    grootte op basis van decision score.

    Returns:
        Optimale grootte met NPV, payback en decision score
        voor alle geëvalueerde groottes.
    """
    session_id = request.session_id

    if session_id not in SESSIONS:
        raise HTTPException(
            status_code=404,
            detail="Sessie niet gevonden. Upload eerst een bestand."
        )

    if 'normalized_df' not in SESSIONS[session_id]:
        raise HTTPException(
            status_code=400,
            detail="Profiel nog niet geanalyseerd. Roep eerst /analyze aan."
        )

    df = SESSIONS[session_id]['normalized_df']

    logger.info(
        "Starting battery size optimization",
        session_id=session_id,
        n_sizes=request.n_sizes
    )

    try:
        # Map chemistry
        chemistry_map = {
            "lfp": BatteryChemistry.LFP,
            "nmc": BatteryChemistry.NMC,
            "nca": BatteryChemistry.NCA,
            "lto": BatteryChemistry.LTO,
        }
        chemistry = chemistry_map.get(request.chemistry.lower(), BatteryChemistry.LFP)

        # Map strategy
        strategy_map = {
            "peak_shaving": DispatchStrategy.PEAK_SHAVING,
            "arbitrage": DispatchStrategy.ARBITRAGE,
            "self_consumption": DispatchStrategy.SELF_CONSUMPTION,
            "hybrid": DispatchStrategy.HYBRID,
        }
        strategy = strategy_map.get(request.strategy.lower(), DispatchStrategy.HYBRID)

        # Tariffs
        tariffs = TariffStructure(
            peak_rate=request.tariffs.peak_rate,
            off_peak_rate=request.tariffs.off_peak_rate,
            peak_hours_start=request.tariffs.peak_hours_start,
            peak_hours_end=request.tariffs.peak_hours_end,
            capacity_tariff=request.tariffs.capacity_tariff,
            feed_in_tariff=request.tariffs.feed_in_tariff
        )

        # Prepare profile
        profile_df = df.copy()
        profile_df['timestamp'] = pd.to_datetime(profile_df['timestamp'])
        profile_df['afname_kwh'] = pd.to_numeric(profile_df['afname_kwh'], errors='coerce').fillna(0)
        if 'teruglevering_kwh' in profile_df.columns:
            profile_df['teruglevering_kwh'] = pd.to_numeric(
                profile_df['teruglevering_kwh'],
                errors='coerce'
            ).fillna(0)
        else:
            profile_df['teruglevering_kwh'] = 0

        # Size range
        size_range = None
        if request.min_capacity_kwh and request.max_capacity_kwh:
            size_range = (request.min_capacity_kwh, request.max_capacity_kwh)

        # Run optimization
        engine = MonteCarloEngine(
            capacity_kwh=50,  # Dummy, will be overridden
            chemistry=chemistry,
            analysis_years=request.analysis_years,
            discount_rate=request.discount_rate
        )

        result = engine.optimize_size(
            profile_df=profile_df,
            tariffs=tariffs,
            strategy=strategy,
            size_range=size_range,
            n_sizes=request.n_sizes,
            mc_simulations_per_size=request.mc_simulations_per_size
        )

        logger.info(
            "Size optimization complete",
            session_id=session_id,
            optimal_size=result["optimal_size_kwh"],
            optimal_score=result["optimal_decision_score"]
        )

        return {
            "success": True,
            "session_id": session_id,
            **result
        }

    except Exception as e:
        logger.error(
            "Size optimization failed",
            session_id=session_id,
            error=str(e),
            exc_info=True
        )
        return {
            "success": False,
            "session_id": session_id,
            "error": str(e)
        }


@router.get("/analyze/{session_id}/timeseries")
async def get_simulation_timeseries(
    session_id: str,
    capacity_kwh: float = 100,
    strategy: str = "hybrid"
):
    """
    Haal simulatie tijdreeks data op voor visualisatie.

    Returns:
        Gesamplde tijdreeks data (elke 4 uur) voor:
        - SoC over tijd
        - Grid exchange over tijd
        - Besparingen over tijd
    """
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Sessie niet gevonden")

    if 'normalized_df' not in SESSIONS[session_id]:
        raise HTTPException(
            status_code=400,
            detail="Profiel nog niet geanalyseerd."
        )

    df = SESSIONS[session_id]['normalized_df']

    try:
        # Prepare profile
        profile_df = df.copy()
        profile_df['timestamp'] = pd.to_datetime(profile_df['timestamp'])
        profile_df['afname_kwh'] = pd.to_numeric(profile_df['afname_kwh'], errors='coerce').fillna(0)
        if 'teruglevering_kwh' in profile_df.columns:
            profile_df['teruglevering_kwh'] = pd.to_numeric(
                profile_df['teruglevering_kwh'],
                errors='coerce'
            ).fillna(0)
        else:
            profile_df['teruglevering_kwh'] = 0

        # Map strategy
        strategy_map = {
            "peak_shaving": DispatchStrategy.PEAK_SHAVING,
            "arbitrage": DispatchStrategy.ARBITRAGE,
            "self_consumption": DispatchStrategy.SELF_CONSUMPTION,
            "hybrid": DispatchStrategy.HYBRID,
        }
        dispatch_strategy = strategy_map.get(strategy.lower(), DispatchStrategy.HYBRID)

        # Run simulation
        simulator = BatteryDispatchSimulator(
            capacity_kwh=capacity_kwh,
            max_power_kw=capacity_kwh / 2
        )

        result = simulator.simulate(
            profile_df=profile_df,
            strategy=dispatch_strategy
        )

        # Sample data (elke 4 uur = elke 16 datapunten bij 15-min interval)
        sample_rate = 16
        timestamps = [r.timestamp.isoformat() for r in result.hourly_results[::sample_rate]]
        soc = result.soc_timeseries[::sample_rate]
        load = result.load_timeseries[::sample_rate]
        savings = result.savings_timeseries[::sample_rate]

        return {
            "timestamps": timestamps,
            "soc_percent": [round(s, 3) for s in soc],
            "grid_load_kwh": [round(l, 3) for l in load],
            "savings_eur": [round(s, 4) for s in savings],
            "sample_rate_hours": 4,
            "total_points": len(timestamps)
        }

    except Exception as e:
        logger.error(f"Timeseries fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
