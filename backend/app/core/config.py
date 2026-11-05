from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "EcoMonitor API"
    app_version: str = "1.0.0"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./ecomonitor.db"
    frontend_origins: list[str] | str = [
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]
    open_meteo_base_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality"
    open_meteo_weather_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_historical_weather_url: str = "https://archive-api.open-meteo.com/v1/archive"
    open_meteo_previous_runs_url: str = "https://previous-runs-api.open-meteo.com/v1/forecast"
    openaq_base_url: str = "https://api.openaq.org/v3"
    openaq_api_key: SecretStr | None = None
    fhmz_air_quality_url: str = "https://zrak.fhmzbih.gov.ba"
    sensor_cache_minutes: int = 30
    sensor_freshness_hours: int = 3
    sync_interval_minutes: int = 30
    initial_history_days: int = 92
    weather_history_days: int = 92
    weather_history_sync_hours: int = 24
    enable_background_sync: bool = True
    ml_retrain_hours: int = 24
    ml_min_new_samples: int = 24
    sync_revision_hours: int = 48
    unavailable_retry_days: int = 7
    request_timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("frontend_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def normalize_postgres_scheme(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://") and "+" not in value.split("://", 1)[0]:
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

