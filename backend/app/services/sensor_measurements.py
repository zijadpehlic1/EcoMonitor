import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from math import isfinite

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import Location, SensorMeasurement, SensorStation, SensorImportState, SyncRun
from app.schemas import (
    LocationOut,
    SensorCoverageOut,
    SensorCurrentResponse,
    SensorMeasurementOut,
)
from app.services.air_quality import aware_utc, utc_now

SENSOR_SYNC_SOURCE = "Physical sensor priority pipeline"
FHMZ_PROVIDER = "Federalni hidrometeorološki zavod BiH (FHMZ)"
FHMZ_SOURCE_URL = "https://zrak.fhmzbih.gov.ba/"
OPENAQ_SOURCE_URL = "https://openaq.org/"
FHMZ_PRIMARY_STATIONS = {
    "zenica": (6, "Zenica Brist"),
    "sarajevo": (3, "Sarajevo Bjelave"),
    "mostar": (30, "Mostar"),
}
FHMZ_POLLUTANTS = {
    "Suspendovane čestice < 2.5 µm": "pm2_5",
    "Suspendovane čestice < 10 µm": "pm10",
    "Azot dioksid": "nitrogen_dioxide",
    "Sumpor dioksid": "sulphur_dioxide",
    "Ozon": "ozone",
}
OPENAQ_POLLUTANTS = {
    "co": "carbon_monoxide",
    "pm25": "pm2_5",
    "pm2.5": "pm2_5",
    "pm10": "pm10",
    "no2": "nitrogen_dioxide",
    "so2": "sulphur_dioxide",
    "o3": "ozone",
}
UNIT = "μg/m³"
# Verified station identities, not arbitrary neighbours within a search radius.
OPENAQ_STATIONS = {"zenica": (2656051,), "sarajevo": (9598,), "mostar": (), "banja-luka": (6482140,)}
_sync_lock = asyncio.Lock()


@dataclass
class SensorSyncResult:
    status: str
    provider: str | None = None
    station_name: str | None = None
    received: int = 0
    inserted: int = 0
    updated: int = 0
    message: str = ""


@dataclass
class ProviderBatch:
    provider: str
    external_id: str
    station_name: str
    source_url: str
    attribution: str
    is_reference: bool
    latitude: float | None
    longitude: float | None
    measurements: list[tuple[datetime, str, float, str]]


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Provider timestamp must contain an offset")
    return parsed.astimezone(UTC)


def _parse_decimal(value: object) -> float:
    text = str(value).strip().replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return float(text)


def _is_fresh(timestamp: datetime, settings: Settings) -> bool:
    age = utc_now() - aware_utc(timestamp)
    return timedelta(0) <= age <= timedelta(hours=settings.sensor_freshness_hours)


async def _get_json(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    settings: Settings,
) -> dict | list:
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()


async def fetch_openaq(location: Location, settings: Settings) -> ProviderBatch | None:
    if settings.openaq_api_key is None:
        return None
    api_key = settings.openaq_api_key.get_secret_value()
    if not api_key:
        return None
    headers = {"X-API-Key": api_key}
    payload = await _get_json(
        f"{settings.openaq_base_url.rstrip('/')}/locations",
        params={
            "coordinates": f"{location.latitude:.4f},{location.longitude:.4f}",
            "radius": 25000,
            "limit": 100,
        },
        headers=headers,
        settings=settings,
    )
    candidates = []
    for item in payload.get("results", []):
        if item.get("id") not in OPENAQ_STATIONS.get(location.slug, ()) or item.get("isMobile"):
            continue
        last = item.get("datetimeLast") or {}
        if not item.get("isMonitor") or not last.get("utc"):
            continue
        last_at = _parse_iso(last["utc"])
        if not _is_fresh(last_at, settings):
            continue
        sensor_map = {
            int(sensor["id"]): sensor
            for sensor in item.get("sensors", [])
            if (sensor.get("parameter") or {}).get("name", "").lower() in OPENAQ_POLLUTANTS
        }
        if sensor_map:
            candidates.append((float(item.get("distance", 999999)), item, sensor_map))
    if not candidates:
        return None

    _, station, sensor_map = min(candidates, key=lambda value: value[0])
    latest = await _get_json(
        f"{settings.openaq_base_url.rstrip('/')}/locations/{station['id']}/latest",
        headers=headers,
        settings=settings,
    )
    measurements: list[tuple[datetime, str, float, str]] = []
    for item in latest.get("results", []):
        sensor = sensor_map.get(int(item.get("sensorsId", -1)))
        if not sensor:
            continue
        parameter = sensor.get("parameter") or {}
        pollutant = OPENAQ_POLLUTANTS.get(str(parameter.get("name", "")).lower())
        unit = str(parameter.get("units", "")).replace("µ", "μ")
        measured_at = _parse_iso(item["datetime"]["utc"])
        if pollutant and unit == UNIT and _is_fresh(measured_at, settings) and item.get("value") is not None and isfinite(float(item["value"])) and float(item["value"]) >= 0:
            measurements.append((measured_at, pollutant, float(item["value"]), unit))
    if not measurements:
        return None
    coordinates = station.get("coordinates") or {}
    provider = (station.get("provider") or {}).get("name") or "OpenAQ"
    return ProviderBatch(
        provider=f"OpenAQ / {provider}",
        external_id=str(station["id"]),
        station_name=station["name"],
        source_url=f"https://explore.openaq.org/locations/{station['id']}",
        attribution=f"OpenAQ / {provider}; " + "; ".join(
            f"{lic.get('name', '')}: {(lic.get('attribution') or {}).get('name', '')}"
            for lic in station.get("licenses") or []),
        is_reference=True,
        latitude=coordinates.get("latitude"),
        longitude=coordinates.get("longitude"),
        measurements=measurements,
    )


async def fetch_fhmz(location: Location, settings: Settings) -> ProviderBatch | None:
    configured = FHMZ_PRIMARY_STATIONS.get(location.slug)
    if not configured:
        return None
    station_id, station_name = configured
    payload = await _get_json(
        f"{settings.fhmz_air_quality_url.rstrip('/')}/rest/aqdata/one/{station_id}",
        settings=settings,
    )
    zone = ZoneInfo(location.timezone)
    measurements: list[tuple[datetime, str, float, str]] = []
    for row in payload.get("data", []):
        if len(row) < 5 or row[2] != "Satni izvorni podaci":
            continue
        pollutant = FHMZ_POLLUTANTS.get(row[0])
        if not pollutant:
            continue
        naive = datetime.strptime(row[1], "%d.%m.%Y. %H:%M")
        # Offset-free provider times cannot identify the repeated autumn hour.
        # Skip ambiguous/nonexistent times instead of silently choosing a fold.
        if naive.replace(tzinfo=zone, fold=0).utcoffset() != naive.replace(tzinfo=zone, fold=1).utcoffset():
            continue
        measured_local = naive.replace(tzinfo=zone)
        measured_at = measured_local.astimezone(UTC)
        try:
            value = _parse_decimal(row[4])
        except (TypeError, ValueError):
            continue
        if isfinite(value) and value >= 0 and measured_at <= utc_now():
            measurements.append((measured_at, pollutant, value, UNIT))
    if not measurements or not any(_is_fresh(item[0], settings) for item in measurements):
        return None
    return ProviderBatch(
        provider=FHMZ_PROVIDER,
        external_id=str(station_id),
        station_name=station_name,
        source_url=FHMZ_SOURCE_URL,
        attribution="Federalni hidrometeorološki zavod Bosne i Hercegovine",
        is_reference=True,
        latitude=None,
        longitude=None,
        measurements=measurements,
    )


def _last_sync(db: Session, location_id: int) -> SyncRun | None:
    return db.scalar(
        select(SyncRun)
        .where(
            SyncRun.location_id == location_id,
            SyncRun.source_name == SENSOR_SYNC_SOURCE,
            SyncRun.status.in_(("success", "unavailable")),
        )
        .order_by(SyncRun.completed_at.desc())
        .limit(1)
    )


def _persist_batch(db: Session, location: Location, batch: ProviderBatch) -> tuple[int, int]:
    if not batch.measurements:
        return 0, 0
    if any(not isfinite(v) or v < 0 or u != UNIT or t.tzinfo is None for t, _, v, u in batch.measurements):
        raise ValueError("Invalid physical measurement")
    now = utc_now()
    station = db.scalar(
        select(SensorStation).where(
            SensorStation.provider == batch.provider,
            SensorStation.external_id == batch.external_id,
        )
    )
    if station is None:
        station = SensorStation(
            location_id=location.id,
            provider=batch.provider,
            external_id=batch.external_id,
            name=batch.station_name,
            source_url=batch.source_url,
            attribution=batch.attribution,
            is_reference=batch.is_reference,
            active=True,
            verified_at=now,
        )
        db.add(station)
        db.flush()
    if station.location_id != location.id:
        raise ValueError("Station already belongs to another city")
    station.name = batch.station_name
    if batch.latitude is not None:
        station.latitude = batch.latitude
    if batch.longitude is not None:
        station.longitude = batch.longitude
    station.source_url = batch.source_url
    station.attribution = batch.attribution
    station.is_reference = batch.is_reference
    station.active = True
    station.verified_at = now
    station.last_measurement_at = max(
        [item[0] for item in batch.measurements]
        + ([aware_utc(station.last_measurement_at)] if station.last_measurement_at else [])
    )

    times = [item[0] for item in batch.measurements]
    existing = {
        (aware_utc(item.measured_at), item.pollutant): item
        for item in db.scalars(
            select(SensorMeasurement).where(
                SensorMeasurement.station_id == station.id,
                SensorMeasurement.measured_at >= min(times),
                SensorMeasurement.measured_at <= max(times),
            )
        ).all()
    }
    inserted = 0
    updated = 0
    for measured_at, pollutant, value, unit in batch.measurements:
        measurement = existing.get((measured_at, pollutant))
        if measurement is None:
            measurement = SensorMeasurement(
                station_id=station.id,
                measured_at=measured_at,
                pollutant=pollutant,
                value=value,
                unit=unit,
                validation_status="unvalidated",
                ingested_at=now,
            )
            db.add(measurement)
            existing[(measured_at, pollutant)] = measurement
            inserted += 1
        else:
            changed = measurement.value != value or measurement.unit != unit
            measurement.value = value
            measurement.unit = unit
            if changed:
                measurement.ingested_at = now
            updated += 1
    return inserted, updated


async def synchronize_sensor_location(
    db: Session,
    location: Location,
    *,
    force: bool = False,
    settings: Settings | None = None,
) -> SensorSyncResult:
    settings = settings or get_settings()
    async with _sync_lock:
        last = _last_sync(db, location.id)
        if (
            not force
            and last
            and last.completed_at
            and utc_now() - aware_utc(last.completed_at)
            < timedelta(minutes=settings.sensor_cache_minutes)
        ):
            return SensorSyncResult(status="cached", message="Sensor cache is still fresh.")

        run = SyncRun(
            source_name=SENSOR_SYNC_SOURCE,
            location_id=location.id,
            started_at=utc_now(),
            status="running",
        )
        db.add(run)
        db.commit()
        provider_errors: list[str] = []
        batch = None
        if settings.openaq_api_key is not None and settings.openaq_api_key.get_secret_value():
            try:
                batch = await fetch_openaq(location, settings)
            except Exception as exc:
                provider_errors.append(f"OpenAQ unavailable: {type(exc).__name__}")
        if batch is None:
            try:
                batch = await fetch_fhmz(location, settings)
            except Exception as exc:
                provider_errors.append(f"FHMZ unavailable: {type(exc).__name__}")

        if batch is None:
            run.status = "unavailable"
            run.completed_at = utc_now()
            run.error_message = "; ".join(provider_errors)[:1000] or "No verified fresh sensor source."
            db.commit()
            return SensorSyncResult(
                status="unavailable",
                message="No verified fresh physical-station measurements are available for this city.",
            )

        try:
            inserted, updated = _persist_batch(db, location, batch)
            run.status = "success"
            run.completed_at = utc_now()
            run.records_received = len(batch.measurements)
            run.records_inserted = inserted
            run.records_updated = updated
            db.commit()
            return SensorSyncResult(
                status="success",
                provider=batch.provider,
                station_name=batch.station_name,
                received=len(batch.measurements),
                inserted=inserted,
                updated=updated,
                message="Verified timestamped physical-station measurements synchronized.",
            )
        except Exception:
            db.rollback()
            failed = db.get(SyncRun, run.id)
            if failed:
                failed.status = "failed"
                failed.completed_at = utc_now()
                failed.error_message = "Sensor persistence failed."
                db.commit()
            raise


def build_sensor_current(
    db: Session,
    location: Location,
    settings: Settings | None = None,
    station_id: int | None = None,
) -> SensorCurrentResponse:
    settings = settings or get_settings()
    if station_id is not None:
        from app.services.datasets import resolve_station
        resolve_station(db, location, station_id)
    station = db.scalar(
        select(SensorStation)
        .where(SensorStation.location_id == location.id, SensorStation.active.is_(True),
               *((SensorStation.id == station_id,) if station_id is not None else ()))
        .order_by(SensorStation.last_measurement_at.desc())
        .limit(1)
    )
    disclaimer = (
        "Automatska satna mjerenja nisu konačno validirana i mogu biti naknadno izmijenjena. "
        "Prikazuju se odvojeno od modeliranih CAMS podataka."
    )
    if station is None or station.last_measurement_at is None:
        return SensorCurrentResponse(
            status="unavailable",
            is_live=False,
            location=LocationOut.model_validate(location),
            message="Nema lokalno potvrđenog izvora svježih senzorskih mjerenja.",
            disclaimer=disclaimer,
        )

    from app.services.station_aqi import LIMITS, GENERAL, SENSITIVE, classify, freshness
    now = utc_now()
    state = db.get(SensorImportState, station.id)
    metadata = json.loads(state.metadata_json) if state else {}
    station_type = metadata.get('stationClassification') or metadata.get('station_type')
    # Review recent distinct valid hours in one indexed database query. Prefer
    # the newest reportable category; a later incomplete low hour must not be
    # silently combined with earlier pollutants to make a reassuring index.
    candidates = db.scalars(select(SensorMeasurement).where(
        SensorMeasurement.station_id == station.id,
        SensorMeasurement.measured_at <= now,
        SensorMeasurement.pollutant.in_(LIMITS), SensorMeasurement.unit == UNIT,
        SensorMeasurement.validation_status.in_(('unvalidated', 'validated')))
        .order_by(SensorMeasurement.measured_at.desc()).limit(2000)).all()
    by_hour = {}
    for row in candidates:
        if isfinite(row.value) and row.value >= 0:
            by_hour.setdefault(aware_utc(row.measured_at), []).append(row)
    latest_at = next(iter(by_hour), None)
    for stamp, hour_rows in by_hour.items():
        if classify(hour_rows, station_type).level is not None:
            latest_at = stamp
            break
    valid_rows = by_hour.get(latest_at, [])
    category = classify(valid_rows, station_type)
    freshness_state, age_minutes = freshness(latest_at, now, now.astimezone(ZoneInfo('Europe/Sarajevo')))
    is_live = station.is_reference and bool(valid_rows) and freshness_state in ('current', 'recent')
    guidance_allowed = is_live and category.level is not None and category.complete
    return SensorCurrentResponse(
        status="live" if is_live else "stale",
        is_live=is_live,
        location=LocationOut.model_validate(location),
        station_id=station.id,
        station_name=station.name,
        provider=station.provider,
        source_url=station.source_url,
        measurements=[
            SensorMeasurementOut(
                pollutant=row.pollutant,
                value=row.value,
                unit=row.unit,
                measured_at=aware_utc(row.measured_at),
            )
            for row in valid_rows
        ],
        latest_measurement_at=latest_at,
        freshness_minutes=age_minutes,
        validation_status="unvalidated" if any(r.validation_status == 'unvalidated' for r in valid_rows) else 'validated' if valid_rows else None,
        message=(
            "Dostupna su svježa fizička mjerenja."
            if is_live
            else "Pohranjena mjerenja postoje, ali njihova svježina nije potvrđena."
        ),
        disclaimer=disclaimer,
        aqi_category=category.level,
        aqi_label=category.label,
        aqi_complete=category.complete,
        aqi_limiting_pollutant=category.limiting_pollutant,
        aqi_station_type=station_type,
        aqi_freshness=freshness_state,
        aqi_age_minutes=age_minutes,
        health_general=GENERAL[category.level-1] if guidance_allowed else None,
        health_sensitive=SENSITIVE[category.level-1] if guidance_allowed else None,
        aqi_methodology='FHMZ/EEA, satni pragovi; izvedeno iz pohranjenih mjerenja' if category.level else None,
    )


def build_sensor_coverage(db: Session, locations: list[Location]) -> list[SensorCoverageOut]:
    results = []
    for location in locations:
        current = build_sensor_current(db, location)
        results.append(
            SensorCoverageOut(
                location=location.slug,
                city=location.name,
                status=current.status,
                provider=current.provider,
                station_name=current.station_name,
                last_measurement_at=current.latest_measurement_at,
                is_live=current.is_live,
            )
        )
    return results
