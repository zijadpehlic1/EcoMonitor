import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import AirQualityReading, Location, SyncRun

logger = logging.getLogger(__name__)

SOURCE_NAME = "Open-Meteo / CAMS"
SOURCE_URL = "https://open-meteo.com/en/docs/air-quality-api"
MODEL_NAME = "CAMS European ensemble (via Open-Meteo)"
POLLUTANTS = (
    "pm2_5",
    "pm10",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "carbon_monoxide",
    "ozone",
    "european_aqi",
)
CONCENTRATION_FIELDS = POLLUTANTS[:-1]
_sync_lock = asyncio.Lock()
SUPPORTED_LOCATIONS = {
    "zenica": ("Zenica", 44.2034, 17.9077),
    "sarajevo": ("Sarajevo", 43.8563, 18.4131),
    "mostar": ("Mostar", 43.3438, 17.8078),
    "banja-luka": ("Banja Luka", 44.7722, 17.1910),
}


@dataclass
class SyncResult:
    status: str
    received: int = 0
    inserted: int = 0
    updated: int = 0
    message: str = ""


def utc_now() -> datetime:
    return datetime.now(UTC)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def ensure_default_location(db: Session) -> Location:
    locations = ensure_supported_locations(db)
    return locations["zenica"]


def ensure_supported_locations(db: Session) -> dict[str, Location]:
    existing = {
        location.slug: location
        for location in db.scalars(select(Location).where(Location.slug.in_(SUPPORTED_LOCATIONS))).all()
    }
    changed = False
    for slug, (name, latitude, longitude) in SUPPORTED_LOCATIONS.items():
        if slug in existing:
            continue
        location = Location(
            slug=slug,
            name=name,
            country="Bosnia and Herzegovina",
            country_code="BA",
            latitude=latitude,
            longitude=longitude,
            timezone="Europe/Sarajevo",
            active=True,
        )
        db.add(location)
        existing[slug] = location
        changed = True
    if changed:
        db.commit()
        for location in existing.values():
            db.refresh(location)
    return existing


def get_last_successful_sync(db: Session, location_id: int) -> SyncRun | None:
    return db.scalar(
        select(SyncRun)
        .where(
            SyncRun.location_id == location_id,
            SyncRun.source_name == SOURCE_NAME,
            SyncRun.status == "success",
        )
        .order_by(SyncRun.completed_at.desc())
        .limit(1)
    )


def cache_is_fresh(db: Session, location_id: int, max_age_minutes: int) -> bool:
    last = get_last_successful_sync(db, location_id)
    if not last or not last.completed_at:
        return False
    return utc_now() - aware_utc(last.completed_at) < timedelta(minutes=max_age_minutes)


async def fetch_open_meteo(location: Location, settings: Settings) -> dict:
    params = {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "hourly": ",".join(POLLUTANTS),
        "past_days": min(max(settings.initial_history_days, 1), 92),
        "forecast_days": 7,
        "timeformat": "unixtime",
        "timezone": "GMT",
        "domains": "cams_europe",
        "cell_selection": "land",
    }
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(settings.open_meteo_base_url, params=params)
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(payload.get("reason", "Open-Meteo returned an unknown error"))
        return payload


def _optional_float(values: list | None, index: int) -> float | None:
    if not values or index >= len(values) or values[index] is None:
        return None
    value = float(values[index])
    return value if isfinite(value) and value >= 0 else None


def _validate_provider_units(payload: dict) -> None:
    units = payload.get("hourly_units") or {}
    for field in CONCENTRATION_FIELDS:
        unit = units.get(field)
        if unit is None:
            continue
        normalized = str(unit).replace("µ", "μ")
        if normalized != "μg/m³":
            raise ValueError(f"Unexpected Open-Meteo unit for {field}: {unit}")


def persist_payload(db: Session, location: Location, payload: dict, sync_run: SyncRun) -> SyncResult:
    _validate_provider_units(payload)
    hourly = payload.get("hourly") or {}
    timestamps = hourly.get("time") or []
    sync_run.records_received = len(timestamps)
    sync_run.api_generation_ms = payload.get("generationtime_ms")

    if not timestamps:
        raise ValueError("Open-Meteo response contained no hourly timestamps")

    measured_times = [datetime.fromtimestamp(int(value), tz=UTC) for value in timestamps]
    start, end = min(measured_times), max(measured_times)
    existing = {
        aware_utc(item.measured_at): item
        for item in db.scalars(
            select(AirQualityReading).where(
                AirQualityReading.location_id == location.id,
                AirQualityReading.source_name == SOURCE_NAME,
                AirQualityReading.measured_at >= start,
                AirQualityReading.measured_at <= end,
            )
        ).all()
    }

    inserted = 0
    updated = 0
    now = utc_now()
    current_hour = now.replace(minute=0, second=0, microsecond=0)

    for index, measured_at in enumerate(measured_times):
        values = {name: _optional_float(hourly.get(name), index) for name in POLLUTANTS}
        if all(value is None for value in values.values()):
            continue

        reading = existing.get(measured_at)
        if reading is None:
            reading = AirQualityReading(
                location_id=location.id,
                measured_at=measured_at,
                source_name=SOURCE_NAME,
                source_url=SOURCE_URL,
                source_type="modeled",
                model_name=MODEL_NAME,
                ingested_at=now,
            )
            db.add(reading)
            existing[measured_at] = reading
            inserted += 1
        else:
            updated += 1

        changed = any(getattr(reading, name) != value for name, value in values.items())
        for name, value in values.items():
            setattr(reading, name, value)
        reading.is_forecast = measured_at > current_hour
        if changed:
            reading.ingested_at = now

    sync_run.status = "success"
    sync_run.completed_at = utc_now()
    sync_run.records_inserted = inserted
    sync_run.records_updated = updated
    db.commit()
    return SyncResult(
        status="success",
        received=len(timestamps),
        inserted=inserted,
        updated=updated,
        message="Modeled CAMS air-quality data synchronized successfully.",
    )


async def synchronize_location(
    db: Session,
    location: Location,
    *,
    force: bool = False,
    settings: Settings | None = None,
) -> SyncResult:
    async with _sync_lock:
        settings = settings or get_settings()
        if not force and cache_is_fresh(db, location.id, settings.sync_interval_minutes):
            return SyncResult(status="cached", message="Cached data is still fresh; external request skipped.")

        sync_run = SyncRun(
            source_name=SOURCE_NAME,
            location_id=location.id,
            started_at=utc_now(),
            status="running",
        )
        db.add(sync_run)
        db.commit()

        try:
            payload = await fetch_open_meteo(location, settings)
            return persist_payload(db, location, payload, sync_run)
        except Exception as exc:
            db.rollback()
            failed_run = db.get(SyncRun, sync_run.id)
            if failed_run:
                failed_run.status = "failed"
                failed_run.completed_at = utc_now()
                failed_run.error_message = str(exc)[:1000]
                db.commit()
            logger.exception("Air-quality synchronization failed for %s", location.slug)
            return SyncResult(status="failed", message=f"Data provider unavailable: {exc}")


def stored_reading_count(db: Session, location_id: int) -> int:
    return int(
        db.scalar(
            select(func.count(AirQualityReading.id)).where(AirQualityReading.location_id == location_id)
        )
        or 0
    )

