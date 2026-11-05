from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    country: str
    country_code: str
    latitude: float
    longitude: float
    timezone: str


class ReadingOut(BaseModel):
    measured_at: datetime
    pm2_5: float | None = None
    pm10: float | None = None
    nitrogen_dioxide: float | None = None
    sulphur_dioxide: float | None = None
    carbon_monoxide: float | None = None
    ozone: float | None = None
    european_aqi: float | None = None
    source_name: str
    source_type: str
    model_name: str | None = None
    is_forecast: bool


class SyncInfo(BaseModel):
    status: str
    last_successful_sync: datetime | None = None
    records_stored: int
    cache_age_minutes: float | None = None


class DashboardResponse(BaseModel):
    location: LocationOut
    latest: ReadingOut | None
    history: list[ReadingOut]
    units: dict[str, str]
    source: dict[str, str]
    sync: SyncInfo
    requested_hours: int
    generated_at: datetime


class HistoricalPointOut(BaseModel):
    timestamp: datetime
    local_date: str
    pm2_5: float | None = None
    pm10: float | None = None
    nitrogen_dioxide: float | None = None
    sulphur_dioxide: float | None = None
    carbon_monoxide: float | None = None
    ozone: float | None = None
    temperature_2m: float | None = None
    sample_counts: dict[str, int]
    peak_timestamps: dict[str, datetime | None]
    expected_samples: int


class HistoricalSeriesResponse(BaseModel):
    location: LocationOut
    grouping: str
    aggregation: str
    requested_hours: int
    points: list[HistoricalPointOut]
    units: dict[str, str]
    pollution_source: dict[str, str]
    weather_sources: list[dict[str, str]]
    timezone: str
    generated_at: datetime
    completeness_note: str


class ForecastPoint(BaseModel):
    timestamp: datetime
    predicted_pm2_5: float = Field(ge=0)


class EvaluationMetrics(BaseModel):
    by_horizon: dict[int, dict[str, float]] = Field(default_factory=dict)
    test_samples: int
    evaluation_horizon_hours: int
    evaluation_origins: int
    mae: float
    rmse: float
    baseline_mae: float
    baseline_rmse: float
    improvement_over_baseline_percent: float
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


class MLForecastResponse(BaseModel):
    location: str = ""
    source_type: str = "modeled"
    station_id: int | None = None
    status: str
    message: str
    model: str | None = None
    trained_samples: int = 0
    metrics: EvaluationMetrics | None = None
    forecast: list[ForecastPoint] = []
    generated_at: datetime
    target: str = "PM2.5"
    target_unit: str = "μg/m³"
    provenance: str = "Prediction derived from historical modeled CAMS/Open-Meteo data; not a sensor measurement."


class RefreshResponse(BaseModel):
    status: str
    received: int
    inserted: int
    updated: int
    message: str


class WeatherReadingOut(BaseModel):
    measured_at: datetime
    temperature_2m: float | None = None
    relative_humidity_2m: float | None = None
    wind_speed_10m: float | None = None
    precipitation: float | None = None
    source_name: str
    source_type: str
    is_forecast: bool


class DailyWeatherOut(BaseModel):
    date: str
    temperature_min: float | None = None
    temperature_max: float | None = None
    temperature_mean: float | None = None
    source_type: str
    is_forecast: bool


class WeatherDashboardResponse(BaseModel):
    location: LocationOut
    latest: WeatherReadingOut | None
    daily: DailyWeatherOut | None
    forecast: list[WeatherReadingOut]
    units: dict[str, str]
    source: dict[str, str]
    last_successful_sync: datetime | None = None


class WeatherRefreshResponse(BaseModel):
    status: str
    live_status: str
    historical_status: str
    archive_status: str
    inserted: int
    updated: int
    message: str


class ComparisonScore(BaseModel):
    mae: float
    rmse: float


class WeatherAwareForecastPoint(BaseModel):
    timestamp: datetime
    predicted_pm2_5: float = Field(ge=0)


class WeatherModelComparisonResponse(BaseModel):
    location: str = ""
    source_type: str = "modeled"
    station_id: int | None = None
    provenance: str = ""
    by_horizon: dict[int, dict[str, float]] = Field(default_factory=dict)
    status: str
    message: str
    comparison_is_fair: bool
    limitation: str
    evaluation_horizon_hours: int = 24
    aligned_samples: int = 0
    training_samples: int = 0
    evaluation_origins: int = 0
    test_samples: int = 0
    train_start: datetime | None = None
    train_end: datetime | None = None
    test_start: datetime | None = None
    test_end: datetime | None = None
    pollution_only: ComparisonScore | None = None
    weather_aware: ComparisonScore | None = None
    persistence: ComparisonScore | None = None
    weather_mae_change_percent: float | None = None
    features: list[str] = []
    forecast: list[WeatherAwareForecastPoint] = []
    generated_at: datetime


class SensorMeasurementOut(BaseModel):
    pollutant: str
    value: float
    unit: str
    measured_at: datetime


class SensorCurrentResponse(BaseModel):
    status: str
    is_live: bool
    location: LocationOut
    station_name: str | None = None
    provider: str | None = None
    source_url: str | None = None
    measurements: list[SensorMeasurementOut] = []
    latest_measurement_at: datetime | None = None
    freshness_minutes: float | None = None
    validation_status: str | None = None
    message: str
    disclaimer: str


class SensorCoverageOut(BaseModel):
    location: str
    city: str
    status: str
    provider: str | None = None
    station_name: str | None = None
    last_measurement_at: datetime | None = None
    is_live: bool = False


class SensorRefreshResponse(BaseModel):
    status: str
    provider: str | None = None
    station_name: str | None = None
    received: int = 0
    inserted: int = 0
    updated: int = 0
    message: str

