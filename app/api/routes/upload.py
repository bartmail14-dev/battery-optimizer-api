"""File upload endpoints."""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
import uuid
import structlog
from io import BytesIO

from app.config import get_settings, Settings
from app.core.parser import parse_file
from app.models.schemas import ParseResult

router = APIRouter()
logger = structlog.get_logger()

# In-memory storage (use Redis in production)
SESSIONS: dict = {}


def get_session_storage():
    """Get session storage (could be replaced with Redis)."""
    return SESSIONS


@router.post("/upload", response_model=ParseResult)
async def upload_file(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings)
):
    """
    Upload and parse energy profile CSV/Excel file.

    Returns column mapping suggestions and data preview.
    """
    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="Geen bestandsnaam opgegeven")

    # Validate file size
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)

    if size_mb > settings.max_file_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"Bestand te groot. Maximum: {settings.max_file_size_mb} MB"
        )

    # Validate extension
    ext = file.filename.split('.')[-1].lower() if file.filename else ''
    if f'.{ext}' not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Ongeldig bestandstype. Toegestaan: {', '.join(settings.allowed_extensions)}"
        )

    # Generate session ID
    session_id = str(uuid.uuid4())

    logger.info(
        "Processing file upload",
        filename=file.filename,
        size_mb=round(size_mb, 2),
        session_id=session_id
    )

    # Parse file
    result = await parse_file(
        file=BytesIO(contents),
        filename=file.filename,
        session_id=session_id
    )

    if result.success:
        # Store raw data for later use
        SESSIONS[session_id] = {
            'contents': contents,
            'filename': file.filename,
            'result': result
        }
        logger.info("File parsed successfully", session_id=session_id, rows=result.row_count)
    else:
        logger.warning("File parsing failed", session_id=session_id, error=result.error)

    return result


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    """Get session status and metadata."""
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Sessie niet gevonden")

    session = SESSIONS[session_id]
    return {
        "session_id": session_id,
        "status": "active",
        "filename": session.get('filename'),
        "row_count": session.get('result', {}).row_count if hasattr(session.get('result'), 'row_count') else 0
    }


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Delete session data."""
    if session_id in SESSIONS:
        del SESSIONS[session_id]
        logger.info("Session deleted", session_id=session_id)
    return {"status": "deleted", "session_id": session_id}


@router.get("/sessions")
async def list_sessions():
    """List all active sessions (admin endpoint)."""
    return {
        "count": len(SESSIONS),
        "sessions": [
            {
                "session_id": sid,
                "filename": data.get('filename')
            }
            for sid, data in SESSIONS.items()
        ]
    }
