import asyncio
from datetime import UTC, datetime, timedelta

from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.models import Location, SensorMeasurement
from app.services import sensor_measurements
from app.services.sensor_measurements import (
    _persist_batch,
    build_sensor_current,
    fetch_fhmz,
    fetch_openaq,
)


def make_context(slug: str = "zenica") -> tuple[Session, Location]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    location = Location(
        slug=slug,
        name=slug.title(),
        country="Bosnia and Herzegovina",
        country_code="BA",
        latitude=44.2034,
        longitude=17.9077,
        timezone="Europe/Sarajevo",
    )
    db.add(location)
    db.commit()
    return db, location


def test_fhmz_parser_persists_unvalidated_physical_measurements(monkeypatch) -> None:
    db, location = make_context()
    now = datetime(2026, 10, 29, 13, 15, tzinfo=UTC)
    monkeypatch.setattr(sensor_measurements, "utc_now", lambda: now)

    async def fake_get_json(*args, **kwargs):
        return {
            "data": [
                ["Suspendovane čestice < 2.5 µm", "29.10.2026. 14:00", "Satni izvorni podaci", "1 sat", "11,15"],
                ["Suspendovane čestice < 10 µm", "29.10.2026. 14:00", "Satni izvorni podaci", "1 sat", "19,84"],
                ["Ugljen monoksid", "29.10.2026. 14:00", "Satni izvorni podaci", "1 sat", "0,28"],
                ["Ozon", "28.10.2026. 00:00", "Dnevni izvorni podaci", "24 sata", "20,0"],
            ]
        }

    monkeypatch.setattr(sensor_measurements, "_get_json", fake_get_json)
    settings = Settings(openaq_api_key=None, sensor_freshness_hours=3)
    batch = asyncio.run(fetch_fhmz(location, settings))
    assert batch is not None
    assert {item[1] for item in batch.measurements} == {"pm2_5", "pm10"}

    assert _persist_batch(db, location, batch) == (2, 0)
    db.commit()
    assert _persist_batch(db, location, batch) == (0, 2)
    db.commit()
    assert db.scalar(select(func.count(SensorMeasurement.id))) == 2

    current = build_sensor_current(db, location, settings)
    assert current.status == "live"
    assert current.is_live
    assert current.station_name == "Zenica Brist"
    assert current.validation_status == "unvalidated"
    assert {item.pollutant: item.value for item in current.measurements} == {
        "pm10": 19.84,
        "pm2_5": 11.15,
    }


def test_stale_sensor_data_is_never_marked_live(monkeypatch) -> None:
    db, location = make_context()
    now = datetime(2026, 10, 29, 13, 0, tzinfo=UTC)
    monkeypatch.setattr(sensor_measurements, "utc_now", lambda: now)
    batch = sensor_measurements.ProviderBatch(
        provider="Test provider",
        external_id="1",
        station_name="Test station",
        source_url="https://example.test",
        attribution="Test",
        is_reference=True,
        latitude=None,
        longitude=None,
        measurements=[(now - timedelta(hours=5), "pm2_5", 12.0, "μg/m³")],
    )
    _persist_batch(db, location, batch)
    db.commit()
    current = build_sensor_current(db, location, Settings(sensor_freshness_hours=3))
    assert current.status == "stale"
    assert not current.is_live


def test_openaq_adapter_requires_fresh_reference_measurements(monkeypatch) -> None:
    _, location = make_context("banja-luka")
    now = datetime(2026, 10, 29, 13, 0, tzinfo=UTC)
    monkeypatch.setattr(sensor_measurements, "utc_now", lambda: now)

    async def fake_get_json(url, **kwargs):
        if url.endswith("/locations"):
            return {
                "results": [
                    {
                        "id": 6482140,
                        "name": "BANJA LUKA - LAZAREVO",
                        "isMonitor": True,
                        "distance": 1000,
                        "datetimeLast": {"utc": "2026-10-29T12:00:00Z"},
                        "coordinates": {"latitude": 44.8, "longitude": 17.2},
                        "provider": {"name": "EEA"},
                        "sensors": [
                            {"id": 10, "parameter": {"name": "pm25", "units": "µg/m³"}}
                        ],
                    }
                ]
            }
        return {
            "results": [
                {
                    "sensorsId": 10,
                    "datetime": {"utc": "2026-10-29T12:00:00Z"},
                    "value": 21.5,
                }
            ]
        }

    monkeypatch.setattr(sensor_measurements, "_get_json", fake_get_json)
    settings = Settings(openaq_api_key=SecretStr("not-printed"), sensor_freshness_hours=3)
    batch = asyncio.run(fetch_openaq(location, settings))
    assert batch is not None
    assert batch.station_name == "BANJA LUKA - LAZAREVO"
    assert batch.measurements[0][1:] == ("pm2_5", 21.5, "μg/m³")
