from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(120))
    country_code: Mapped[str] = mapped_column(String(2))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    timezone: Mapped[str] = mapped_column(String(80), default="Europe/Sarajevo")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    readings: Mapped[list["AirQualityReading"]] = relationship(back_populates="location")


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    key: Mapped[str] = mapped_column(String(240), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    arguments: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DataCoverage(Base):
    """Attempted UTC date ranges, distinct from actual measurement completeness."""
    __tablename__ = "data_coverage"
    key: Mapped[str] = mapped_column(String(240), primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    dataset: Mapped[str] = mapped_column(String(160), index=True)
    day: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelArtifact(Base):
    __tablename__ = "model_artifacts"
    key: Mapped[str] = mapped_column(String(240), primary_key=True)
    version: Mapped[str] = mapped_column(String(120))
    metadata_json: Mapped[str] = mapped_column(Text)
    forest_json: Mapped[str] = mapped_column(Text)
    evaluation_json: Mapped[str] = mapped_column(Text)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModelResult(Base):
    __tablename__ = "model_results"
    key: Mapped[str] = mapped_column(String(240), primary_key=True)
    input_version: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModelExecution(Base):
    __tablename__ = 'model_executions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    model_key: Mapped[str] = mapped_column(String(240), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    elapsed_ms: Mapped[float] = mapped_column(Float)
    trained: Mapped[bool] = mapped_column(Boolean)
    evaluated: Mapped[bool] = mapped_column(Boolean)
    forecast_recomputed: Mapped[bool] = mapped_column(Boolean)


class SourceMetadata(Base):
    __tablename__ = 'source_metadata'
    key: Mapped[str] = mapped_column(String(240), primary_key=True)
    metadata_json: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AirQualityReading(Base):
    __tablename__ = "air_quality_readings"
    __table_args__ = (
        UniqueConstraint("location_id", "measured_at", "source_name", name="uq_reading_identity"),
        Index("ix_readings_location_time", "location_id", "measured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"))
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    pm2_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    pm10: Mapped[float | None] = mapped_column(Float, nullable=True)
    nitrogen_dioxide: Mapped[float | None] = mapped_column(Float, nullable=True)
    sulphur_dioxide: Mapped[float | None] = mapped_column(Float, nullable=True)
    carbon_monoxide: Mapped[float | None] = mapped_column(Float, nullable=True)
    ozone: Mapped[float | None] = mapped_column(Float, nullable=True)
    european_aqi: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_name: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(32), default="modeled")
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_forecast: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    location: Mapped[Location] = relationship(back_populates="readings")


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(120), index=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    records_received: Mapped[int] = mapped_column(Integer, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    api_generation_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class WeatherReading(Base):
    __tablename__ = "weather_readings"
    __table_args__ = (
        UniqueConstraint(
            "location_id",
            "measured_at",
            "source_name",
            "forecast_lead_hours",
            name="uq_weather_reading_identity",
        ),
        Index("ix_weather_location_time", "location_id", "measured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"))
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    temperature_2m: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_humidity_2m: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed_10m: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_name: Mapped[str] = mapped_column(String(160))
    source_url: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(40))
    model_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    forecast_lead_hours: Mapped[int] = mapped_column(Integer, default=0)
    is_forecast: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DailyWeatherSummary(Base):
    __tablename__ = "daily_weather_summaries"
    __table_args__ = (
        UniqueConstraint("location_id", "date", "source_name", name="uq_daily_weather_identity"),
        Index("ix_daily_weather_location_date", "location_id", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date, index=True)
    temperature_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_name: Mapped[str] = mapped_column(String(160))
    source_url: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(40))
    is_forecast: Mapped[bool] = mapped_column(Boolean, default=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SensorStation(Base):
    __tablename__ = "sensor_stations"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_sensor_station_provider_id"),
        Index("ix_sensor_station_location", "location_id", "active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(80))
    external_id: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(160))
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    attribution: Mapped[str] = mapped_column(Text)
    is_reference: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_measurement_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SensorMeasurement(Base):
    __tablename__ = "sensor_measurements"
    __table_args__ = (
        UniqueConstraint("station_id", "measured_at", "pollutant", name="uq_sensor_measurement_identity"),
        Index("ix_sensor_measurement_station_time", "station_id", "measured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("sensor_stations.id", ondelete="CASCADE"))
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    pollutant: Mapped[str] = mapped_column(String(40))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(24))
    validation_status: Mapped[str] = mapped_column(String(40), default="unvalidated")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SensorImportState(Base):
    """Additive table: no destructive migration of existing observations."""
    __tablename__ = "sensor_import_states"
    station_id: Mapped[int] = mapped_column(ForeignKey("sensor_stations.id"), primary_key=True)
    metadata_json: Mapped[str] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SensorMeasurementMetadata(Base):
    __tablename__ = "sensor_measurement_metadata"
    measurement_id: Mapped[int] = mapped_column(ForeignKey("sensor_measurements.id"), primary_key=True)
    provider_sensor_id: Mapped[str] = mapped_column(String(120))
    metadata_json: Mapped[str] = mapped_column(Text)

