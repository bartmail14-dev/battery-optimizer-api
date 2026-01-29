"""
===============================================================================
BATTERY OPTIMIZER API - Hoofdapplicatie
===============================================================================

Dit is het startpunt van de Battery Optimizer API. Deze API biedt:
- CSV upload en parsing van energieprofielen (kwartierwaarden)
- Analyse van verbruikspatronen en piekvermogen
- Batterij-optimalisatie met MILP (Mixed Integer Linear Programming)
- Data verrijking met externe bronnen (netbeheerder, tarieven, subsidies)
- Export naar CSV/Excel

NOTITIE VOOR BART:
- De API draait op Railway (https://comcalculator-production.up.railway.app)
- Documentatie beschikbaar op /docs (Swagger UI)
- Health check op /health (gebruikt door Railway voor deployment)

Technische stack:
- FastAPI: Modern Python web framework (async support)
- Pydantic: Data validatie en serialisatie
- structlog: Gestructureerde logging in JSON formaat
===============================================================================
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import structlog

from app.config import get_settings
from app.api.routes import upload, analyze, optimize, export, enrich
from app.services.enrichment import close_service

# =============================================================================
# LOGGING CONFIGURATIE
# =============================================================================
# We gebruiken structlog voor gestructureerde logging in JSON formaat.
# Dit maakt het makkelijker om logs te doorzoeken in productie (Railway).
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),  # ISO timestamp toevoegen
        structlog.processors.add_log_level,            # Log level (INFO, ERROR, etc.)
        structlog.processors.JSONRenderer()            # Output als JSON
    ]
)
logger = structlog.get_logger()


# =============================================================================
# APPLICATIE LIFECYCLE
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Beheert de levenscyclus van de applicatie.

    NOTITIE VOOR BART:
    - Dit wordt uitgevoerd bij opstarten en afsluiten van de API
    - Bij opstarten: logging dat de API start
    - Bij afsluiten: cleanup van externe API connecties (ENTSO-E, TenneT, etc.)

    De 'yield' splitst startup (ervoor) en shutdown (erna).
    """
    settings = get_settings()

    # === STARTUP ===
    logger.info(
        "Starting Battery Optimizer API",
        version=settings.version,
        debug=settings.debug
    )

    yield  # Hier draait de applicatie

    # === SHUTDOWN ===
    # Sluit alle externe API clients netjes af
    await close_service()
    logger.info("Shutting down Battery Optimizer API")


# =============================================================================
# APPLICATIE FACTORY
# =============================================================================
def create_app() -> FastAPI:
    """
    Creëert en configureert de FastAPI applicatie.

    NOTITIE VOOR BART:
    Deze functie maakt de FastAPI app aan met alle configuratie:
    - Titel en versie voor de docs
    - CORS middleware (zodat de frontend erbij kan)
    - Alle API routes (upload, analyze, optimize, export, enrich)

    Returns:
        FastAPI: Geconfigureerde applicatie instance
    """
    settings = get_settings()

    # Maak de FastAPI applicatie
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="API voor batterij-optimalisatie en energieprofiel analyse",
        lifespan=lifespan,
        docs_url="/docs",      # Swagger UI documentatie
        redoc_url="/redoc" if settings.debug else None,  # ReDoc alleen in debug
    )

    # -------------------------------------------------------------------------
    # CORS MIDDLEWARE
    # -------------------------------------------------------------------------
    # CORS (Cross-Origin Resource Sharing) is nodig zodat de frontend
    # (battery-optimizer.vercel.app) requests kan doen naar deze API.
    # Zonder CORS blokkeert de browser de requests.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,  # Toegestane origins (frontend URLs)
        allow_credentials=True,
        allow_methods=["*"],   # Alle HTTP methods (GET, POST, etc.)
        allow_headers=["*"],   # Alle headers
    )

    # -------------------------------------------------------------------------
    # API ROUTES
    # -------------------------------------------------------------------------
    # Elke router handelt een specifiek deel van de functionaliteit af.
    # Alle routes krijgen prefix /api/v1 voor versioning.

    # Upload: CSV bestanden uploaden en parsen
    app.include_router(upload.router, prefix="/api/v1", tags=["Upload"])

    # Analyze: Energieprofiel analyseren (piek, dal, baseload, etc.)
    app.include_router(analyze.router, prefix="/api/v1", tags=["Analysis"])

    # Optimize: Batterij-optimalisatie berekeningen
    app.include_router(optimize.router, prefix="/api/v1", tags=["Optimization"])

    # Export: Resultaten exporteren naar CSV/Excel
    app.include_router(export.router, prefix="/api/v1", tags=["Export"])

    # Enrich: Data verrijking (netbeheerder, tarieven, subsidies, congestie)
    app.include_router(enrich.router, prefix="/api/v1", tags=["Enrichment"])

    # -------------------------------------------------------------------------
    # BASIS ENDPOINTS
    # -------------------------------------------------------------------------
    @app.get("/")
    async def root():
        """
        Root endpoint - geeft basis API informatie.

        NOTITIE VOOR BART:
        Dit is handig om snel te checken of de API draait.
        Bezoek gewoon de root URL om te zien of alles werkt.
        """
        return {
            "name": settings.app_name,
            "version": settings.version,
            "docs": "/docs"
        }

    @app.get("/health")
    async def health_check():
        """
        Health check endpoint voor Railway deployment.

        NOTITIE VOOR BART:
        Railway checkt dit endpoint om te zien of de container gezond is.
        Als dit endpoint niet 200 OK teruggeeft, herstart Railway de container.

        In railway.toml staat: healthcheckPath = "/health"
        """
        return {
            "status": "healthy",
            "version": settings.version
        }

    return app


# =============================================================================
# APPLICATIE INSTANTIE
# =============================================================================
# Dit is de daadwerkelijke app die door uvicorn wordt gedraaid.
# Uvicorn wordt gestart met: uvicorn app.main:app --host 0.0.0.0 --port $PORT
app = create_app()
