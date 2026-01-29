from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import structlog

from app.config import get_settings
from app.api.routes import upload, analyze, optimize, export

# Structured logging setup
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    settings = get_settings()
    logger.info(
        "Starting Battery Optimizer API",
        version=settings.version,
        debug=settings.debug
    )
    yield
    logger.info("Shutting down Battery Optimizer API")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="API voor batterij-optimalisatie en energieprofiel analyse",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else "/docs",
        redoc_url="/redoc" if settings.debug else None,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(upload.router, prefix="/api/v1", tags=["Upload"])
    app.include_router(analyze.router, prefix="/api/v1", tags=["Analysis"])
    app.include_router(optimize.router, prefix="/api/v1", tags=["Optimization"])
    app.include_router(export.router, prefix="/api/v1", tags=["Export"])

    @app.get("/")
    async def root():
        """Root endpoint with API info."""
        return {
            "name": settings.app_name,
            "version": settings.version,
            "docs": "/docs"
        }

    @app.get("/health")
    async def health_check():
        """Health check endpoint for Railway/container orchestration."""
        return {
            "status": "healthy",
            "version": settings.version
        }

    return app


app = create_app()
