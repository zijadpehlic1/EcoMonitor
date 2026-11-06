from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import AirQualityReading, Location, SyncRun
from app.services import air_quality
from app.services.air_quality import cache_is_fresh, persist_payload


def make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_ingestion_is_idempotent_and_marks_provenance() -> None:
    db = make_db()
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
    timestamp = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp())
    payload = {
        "generationtime_ms": 3.5,
        "hourly": {
            "time": [timestamp],
            "pm2_5": [18.4],
            "pm10": [31.2],
            "nitrogen_dioxide": [12.0],
            "sulphur_dioxide": [4.1],
            "carbon_monoxide": [190.0],
            "ozone": [44.0],
            "european_aqi": [45.0],
        },
    }

    first = SyncRun(source_name="Open-Meteo / CAMS", location_id=location.id, started_at=datetime.now(UTC), status="running")
    db.add(first)
    db.commit()
    result = persist_payload(db, location, payload, first)
    assert result.inserted == 1

    second = SyncRun(source_name="Open-Meteo / CAMS", location_id=location.id, started_at=datetime.now(UTC), status="running")
    db.add(second)
    db.commit()
    result = persist_payload(db, location, payload, second)
    assert result.inserted == 0
    assert result.updated == 1
    assert db.scalar(select(func.count(AirQualityReading.id))) == 1
    reading = db.scalar(select(AirQualityReading))
    assert reading is not None
    assert reading.source_type == "modeled"
    assert "CAMS" in (reading.model_name or "")


def test_ingestion_normalizes_utc_and_separates_forecast_by_valid_time(monkeypatch) -> None:
    db = make_db()
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
    now = datetime(2026, 10, 29, 12, 35, tzinfo=UTC)
    monkeypatch.setattr(air_quality, "utc_now", lambda: now)
    times = [
        datetime(2026, 10, 29, 11, tzinfo=UTC),
        datetime(2026, 10, 29, 12, tzinfo=UTC),
        datetime(2026, 10, 29, 13, tzinfo=UTC),
    ]
    payload = {
        "hourly_units": {"pm2_5": "μg/m³", "pm10": "μg/m³"},
        "hourly": {
            "time": [int(item.timestamp()) for item in times],
            "pm2_5": [10.0, 11.0, 12.0],
            "pm10": [20.0, 21.0, 22.0],
        },
    }
    sync = SyncRun(source_name="Open-Meteo / CAMS", location_id=location.id, started_at=now, status="running")
    db.add(sync)
    db.commit()

    persist_payload(db, location, payload, sync)
    readings = list(db.scalars(select(AirQualityReading).order_by(AirQualityReading.measured_at)))

    assert [item.is_forecast for item in readings] == [False, False, True]
    assert [air_quality.aware_utc(item.measured_at) for item in readings] == times
    assert all(item.source_type == "modeled" for item in readings)

    from app.services import dashboard as dashboard_service
    monkeypatch.setattr(dashboard_service, 'utc_now', lambda: now)
    current = dashboard_service.build_dashboard(db, location, 24)
    assert current.latest.measured_at == times[1]
    assert all(item.measured_at <= now for item in current.history)


def test_ingestion_rejects_unexpected_concentration_units() -> None:
    db = make_db()
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
    now = datetime.now(UTC)
    sync = SyncRun(source_name="Open-Meteo / CAMS", location_id=location.id, started_at=now, status="running")
    db.add(sync)
    db.commit()
    payload = {
        "hourly_units": {"pm2_5": "mg/m³"},
        "hourly": {"time": [int(now.timestamp())], "pm2_5": [10.0]},
    }

    with pytest.raises(ValueError, match="Unexpected Open-Meteo unit"):
        persist_payload(db, location, payload, sync)


def test_cache_freshness_uses_last_successful_completion(monkeypatch) -> None:
    db = make_db()
    now = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(air_quality, "utc_now", lambda: now)
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
    db.add(
        SyncRun(
            source_name="Open-Meteo / CAMS",
            location_id=location.id,
            started_at=now - timedelta(minutes=11),
            completed_at=now - timedelta(minutes=10),
            status="success",
        )
    )
    db.commit()

    assert cache_is_fresh(db, location.id, 30)
    assert not cache_is_fresh(db, location.id, 5)

