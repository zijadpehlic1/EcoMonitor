from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Location, SyncRun, WeatherReading
from app.services import weather
from app.services.weather import (
    ARCHIVE_FIELD_MAP,
    ARCHIVED_WEATHER_SOURCE,
    LIVE_WEATHER_SOURCE,
    persist_hourly_weather,
)


def make_context() -> tuple[Session, Location]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    location = Location(
        slug="zenica",
        name="Zenica",
        country="Bosnia and Herzegovina",
        country_code="BA",
        latitude=44.2034,
        longitude=17.9077,
        timezone="Europe/Sarajevo",
    )
    db.add(location)
    db.commit()
    return db, location


def sync_run(db: Session, location: Location, source: str) -> SyncRun:
    run = SyncRun(
        source_name=source,
        location_id=location.id,
        started_at=datetime.now(UTC),
        status="running",
    )
    db.add(run)
    db.commit()
    return run


def test_weather_ingestion_is_utc_aligned_idempotent_and_handles_missing_values(monkeypatch) -> None:
    db, location = make_context()
    now = datetime(2026, 10, 29, 12, 35, tzinfo=UTC)
    monkeypatch.setattr(weather, "utc_now", lambda: now)
    times = [now.replace(minute=0), now.replace(minute=0) + timedelta(hours=1)]
    payload = {
        "hourly_units": {
            "temperature_2m": "°C",
            "relative_humidity_2m": "%",
            "wind_speed_10m": "km/h",
            "precipitation": "mm",
        },
        "hourly": {
            "time": [int(item.timestamp()) for item in times],
            "temperature_2m": [11.0, None],
            "relative_humidity_2m": [73.0, 75.0],
            "wind_speed_10m": [8.5, 9.0],
            "precipitation": [0.0, None],
        },
    }

    first = sync_run(db, location, LIVE_WEATHER_SOURCE)
    assert persist_hourly_weather(
        db,
        location,
        payload,
        first,
        source_name=LIVE_WEATHER_SOURCE,
        source_url="https://open-meteo.com/en/docs",
        field_map={field: field for field in weather.HOURLY_FIELDS},
        forecast_lead_hours=0,
        archived=False,
    ) == (2, 0)
    db.commit()

    second = sync_run(db, location, LIVE_WEATHER_SOURCE)
    assert persist_hourly_weather(
        db,
        location,
        payload,
        second,
        source_name=LIVE_WEATHER_SOURCE,
        source_url="https://open-meteo.com/en/docs",
        field_map={field: field for field in weather.HOURLY_FIELDS},
        forecast_lead_hours=0,
        archived=False,
    ) == (0, 2)
    db.commit()

    rows = list(db.scalars(select(WeatherReading).order_by(WeatherReading.measured_at)))
    assert db.scalar(select(func.count(WeatherReading.id))) == 2
    assert [weather.aware_utc(row.measured_at) for row in rows] == times
    assert rows[0].source_type == "modeled"
    assert rows[1].source_type == "forecast"
    assert rows[1].temperature_2m is None
    assert rows[1].relative_humidity_2m == 75.0


def test_archived_weather_has_explicit_24_hour_provenance() -> None:
    db, location = make_context()
    timestamp = datetime(2026, 10, 20, 6, tzinfo=UTC)
    payload_fields = list(ARCHIVE_FIELD_MAP.values())
    payload = {
        "hourly_units": {
            payload_fields[0]: "°C",
            payload_fields[1]: "%",
            payload_fields[2]: "km/h",
            payload_fields[3]: "mm",
        },
        "hourly": {
            "time": [int(timestamp.timestamp())],
            payload_fields[0]: [9.0],
            payload_fields[1]: [80.0],
            payload_fields[2]: [5.0],
            payload_fields[3]: [0.2],
        },
    }
    run = sync_run(db, location, ARCHIVED_WEATHER_SOURCE)
    persist_hourly_weather(
        db,
        location,
        payload,
        run,
        source_name=ARCHIVED_WEATHER_SOURCE,
        source_url="https://open-meteo.com/en/docs/previous-runs-api",
        field_map=ARCHIVE_FIELD_MAP,
        forecast_lead_hours=24,
        archived=True,
    )
    db.commit()
    row = db.scalar(select(WeatherReading))
    assert row is not None
    assert row.forecast_lead_hours == 24
    assert row.source_type == "archived_forecast"


def test_weather_ingestion_rejects_unexpected_units() -> None:
    db, location = make_context()
    now = datetime.now(UTC)
    payload = {
        "hourly_units": {"temperature_2m": "°F"},
        "hourly": {"time": [int(now.timestamp())], "temperature_2m": [50.0]},
    }
    with pytest.raises(ValueError, match="Unexpected Open-Meteo weather unit"):
        persist_hourly_weather(
            db,
            location,
            payload,
            sync_run(db, location, LIVE_WEATHER_SOURCE),
            source_name=LIVE_WEATHER_SOURCE,
            source_url="https://open-meteo.com/en/docs",
            field_map={"temperature_2m": "temperature_2m"},
            forecast_lead_hours=0,
            archived=False,
        )
