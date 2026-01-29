"""Battery optimization endpoints."""

from fastapi import APIRouter, HTTPException
import structlog

from app.models.schemas import OptimizationRequest, OptimizationResult
from app.core.optimizer import BatteryOptimizer
from app.api.routes.upload import SESSIONS

router = APIRouter()
logger = structlog.get_logger()


@router.post("/optimize", response_model=OptimizationResult)
async def optimize_battery(request: OptimizationRequest):
    """
    Run battery optimization for the uploaded profile.

    Requires:
    - Valid session_id from upload
    - Profile must be analyzed first (/analyze endpoint)
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
        "Starting battery optimization",
        session_id=session_id,
        strategy=request.strategy.value,
        analysis_years=request.analysis_years
    )

    try:
        optimizer = BatteryOptimizer(
            profile_df=df,
            tariffs=request.tariffs,
            constraints=request.constraints,
            strategy=request.strategy,
            analysis_years=request.analysis_years,
            discount_rate=request.discount_rate
        )

        result = optimizer.optimize()

        if result.success and result.optimal:
            logger.info(
                "Optimization complete",
                session_id=session_id,
                optimal_size=result.optimal.capacity_kwh,
                npv=result.optimal.financials.npv,
                computation_time=result.computation_time_seconds
            )

            # Store result in session
            SESSIONS[session_id]['optimization_result'] = result
        else:
            logger.warning(
                "Optimization completed with issues",
                session_id=session_id,
                error=result.error
            )

        return result

    except Exception as e:
        logger.error("Optimization failed", session_id=session_id, error=str(e))
        return OptimizationResult(
            success=False,
            optimal=None,
            alternatives=[],
            sensitivity_analysis=[],
            computation_time_seconds=0,
            methodology_notes="",
            error=str(e)
        )


@router.get("/optimize/{session_id}/result")
async def get_optimization_result(session_id: str):
    """Get cached optimization result."""
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Sessie niet gevonden")

    if 'optimization_result' not in SESSIONS[session_id]:
        raise HTTPException(
            status_code=400,
            detail="Geen optimalisatie resultaat beschikbaar. Roep eerst /optimize aan."
        )

    return SESSIONS[session_id]['optimization_result']


@router.get("/optimize/{session_id}/sensitivity")
async def get_sensitivity_analysis(session_id: str):
    """Get sensitivity analysis data."""
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Sessie niet gevonden")

    if 'optimization_result' not in SESSIONS[session_id]:
        raise HTTPException(
            status_code=400,
            detail="Geen optimalisatie resultaat beschikbaar."
        )

    result = SESSIONS[session_id]['optimization_result']
    return {
        "sensitivity_analysis": [s.model_dump() for s in result.sensitivity_analysis]
    }
