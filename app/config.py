from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    # App settings
    app_name: str = "Battery Optimizer API"
    version: str = "1.0.2"
    debug: bool = False

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS - Production and development origins
    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://battery-optimizer.vercel.app",
        "https://battery-optimizer-*.vercel.app",  # Preview deployments
    ]

    # File upload
    max_file_size_mb: int = 50
    allowed_extensions: list[str] = [".csv", ".xlsx", ".xls"]

    # Optimization settings
    default_discount_rate: float = 0.05
    default_analysis_years: int = 10
    default_battery_price_per_kwh: float = 450.0

    # Rate limiting
    rate_limit_per_minute: int = 30

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
