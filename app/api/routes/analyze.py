"""Profile analysis endpoints."""

from fastapi import APIRouter, HTTPException
import structlog
import pandas as pd
from io import BytesIO

from app.models.schemas import AnalyzeRequest, AnalysisResult, ColumnMapping
from app.core.parser import normalize_dataframe
from app.core.analyzer import analyze_profile
from app.api.routes.upload import SESSIONS

router = APIRouter()
logger = structlog.get_logger()


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
