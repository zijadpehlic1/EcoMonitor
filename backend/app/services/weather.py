import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from math import isfinite

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import DailyWeatherSummary, Location, SyncRun, WeatherReading
from app.schemas import DailyWeatherOut, LocationOut, WeatherDashboardResponse, WeatherReadingOut
from app.services.air_quality import aware_utc, utc_now

logger = logging.getLogger(__name__)

LIVE_WEATHER_SOURCE = "Open-Meteo Weather Forecast"
HISTORICAL_WEATHER_SOURCE = "Open-Meteo Historical Weather"
ARCHIVED_WEATHER_SOURCE = "Open-Meteo Previous Runs (24h lead)"
WEATHER_SOURCE_URL = "https://open-meteo.com/en/docs"
HISTORICAL_WEATHER_SOURCE_URL = "https://open-meteo.com/en/docs/historical-weather-api"
PREVIOUS_RUNS_SOURCE_URL = "https://open-meteo.com/en/docs/previous-runs-api"
WEATHER_MODEL_NAME = "Open-Meteo Best Match weather models"
HOURLY_FIELDS = ("temperature_2m", "relative_humidity_2m", "wind_speed_10m", "precipitation")
DAILY_FIELDS = ("temperature_2m_min", "temperature_2m_max", "temperature_2m_mean")
ARCHIVE_FIELD_MAP = {field: f"{field}_previous_day1" for field in HOURLY_FIELDS}
WEATHER_UNITS = {
    "temperature_2m": "°C",
    "relative_humidity_2m": "%",
    "wind_speed_10m": "km/h",
    "precipitation": "mm",
    "temperature_min": "°C",
    "temperature_max": "°C",
    "temperature_mean": "°C",
}
_weather_sync_lock = asyncio.Lock()


@dataclass
class WeatherSyncResult:
    status: str
    live_status: str
    historical_status: str
    archive_status: str
    inserted: int = 0
    updated: int = 0
    message: str = ""


def _last_source_sync(db: Session, location_id: int, source_name: str) -> SyncRun | None:
    return db.scalar(
        select(SyncRun)
        .where(
            SyncRun.location_id == location_id,
            SyncRun.source_name == source_name,
            SyncRun.status == "success",
        )
        .order_by(SyncRun.completed_at.desc())
        .limit(1)
    )


def _source_cache_is_fresh(
    db: Session,
    location_id: int,
    source_name: str,
    max_age: timedelta,
) -> bool:
    last = _last_source_sync(db, location_id, source_name)
    return bool(last and last.completed_at and utc_now() - aware_utc(last.completed_at) < max_age)


async def _fetch_json(url: str, params: dict, settings: Settings) -> dict:
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(payload.get("reason", "Open-Meteo returned an unknown weather error"))
        return payload


async def fetch_live_weather(location: Location, settings: Settings) -> dict:
    return await _fetch_json(
        settings.open_meteo_weather_url,
        {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "hourly": ",".join(HOURLY_FIELDS),
            "daily": ",".join(DAILY_FIELDS),
            "past_days": 7,
            "forecast_days": 7,
            "timeformat": "unixtime",
            "timezone": location.timezone,
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
            "cell_selection": "land",
        },
        settings,
    )


async def fetch_archived_forecast_weather(location: Location, settings: Settings) -> dict:
    local_today = utc_now().astimezone(ZoneInfo(location.timezone)).date()
    history_days = min(max(settings.weather_history_days, 14), 92)
    return await _fetch_json(
        settings.open_meteo_previous_runs_url,
        {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "hourly": ",".join(ARCHIVE_FIELD_MAP.values()),
            "start_date": (local_today - timedelta(days=history_days)).isoformat(),
            "end_date": local_today.isoformat(),
            "timeformat": "unixtime",
            "timezone": "GMT",
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
            "cell_selection": "land",
        },
        settings,
    )


async def fetch_historical_weather(location: Location, settings: Settings) -> dict:
    local_today = utc_now().astimezone(ZoneInfo(location.timezone)).date()
    history_days = min(max(settings.weather_history_days, 14), 92)
    # The operational endpoint already supplies the latest seven days. Ending
    # six days ago avoids overlap and allows for reanalysis publication delay.
    return await _fetch_json(
        settings.open_meteo_historical_weather_url,
        {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "hourly": ",".join(HOURLY_FIELDS),
            "start_date": (local_today - timedelta(days=history_days)).isoformat(),
            "end_date": (local_today - timedelta(days=6)).isoformat(),
            "timeformat": "unixtime",
            "timezone": "GMT",
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
            "cell_selection": "land",
        },
        settings,
    )


def _optional_float(values: list | None, index: int) -> float | None:
    if not values or index >= len(values) or values[index] is None:
        return None
    value = float(values[index])
    return value if isfinite(value) else None


def _validate_units(payload: dict, field_map: dict[str, str]) -> None:
    units = payload.get("hourly_units") or {}
    expected = {
        "temperature_2m": "°C",
        "relative_humidity_2m": "%",
        "wind_speed_10m": "km/h",
        "precipitation": "mm",
    }
    for field, payload_field in field_map.items():
        unit = units.get(payload_field)
        if unit is not None and str(unit) != expected[field]:
            raise ValueError(f"Unexpected Open-Meteo weather unit for {payload_field}: {unit}")


def persist_hourly_weather(
    db: Session,
    location: Location,
    payload: dict,
    sync_run: SyncRun,
    *,
    source_name: str,
    source_url: str,
    field_map: dict[str, str],
    forecast_lead_hours: int,
    archived: bool,
    source_type_override: str | None = None,
) -> tuple[int, int]:
    _validate_units(payload, field_map)
    hourly = payload.get("hourly") or {}
    timestamps = hourly.get("time") or []
    sync_run.records_received = len(timestamps)
    sync_run.api_generation_ms = payload.get("generationtime_ms")
    if not timestamps:
        raise ValueError(f"{source_name} returned no hourly weather timestamps")

    measured_times = [datetime.fromtimestamp(int(value), tz=UTC) for value in timestamps]
    existing = {
        aware_utc(item.measured_at): item
        for item in db.scalars(
            select(WeatherReading).where(
                WeatherReading.location_id == location.id,
                WeatherReading.source_name == source_name,
                WeatherReading.forecast_lead_hours == forecast_lead_hours,
                WeatherReading.measured_at >= min(measured_times),
                WeatherReading.measured_at <= max(measured_times),
            )
        ).all()
    }
    now = utc_now()
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    inserted = 0
    updated = 0

    for index, measured_at in enumerate(measured_times):
        values = {
            field: _optional_float(hourly.get(payload_field), index)
            for field, payload_field in field_map.items()
        }
        if all(value is None for value in values.values()):
            continue
        reading = existing.get(measured_at)
        if reading is None:
            reading = WeatherReading(
                location_id=location.id,
                measured_at=measured_at,
                source_name=source_name,
                source_url=source_url,
                model_name=WEATHER_MODEL_NAME,
                forecast_lead_hours=forecast_lead_hours,
                ingested_at=now,
                source_type=source_type_override or ("archived_forecast" if archived else "modeled"),
            )
            db.add(reading)
            existing[measured_at] = reading
            inserted += 1
        else:
            updated += 1
        for field, value in values.items():
            setattr(reading, field, value)
        reading.is_forecast = measured_at > current_hour
        reading.source_type = source_type_override or (
            "archived_forecast" if archived else ("forecast" if reading.is_forecast else "modeled")
        )
        reading.ingested_at = now

    sync_run.records_inserted = inserted
    sync_run.records_updated = updated
    return inserted, updated


def persist_daily_weather(
    db: Session,
    location: Location,
    payload: dict,
) -> tuple[int, int]:
    daily = payload.get("daily") or {}
    timestamps = daily.get("time") or []
    if not timestamps:
        return 0, 0
    zone = ZoneInfo(location.timezone)
    dates = [datetime.fromtimestamp(int(value), tz=UTC).astimezone(zone).date() for value in timestamps]
    existing = {
        item.date: item
        for item in db.scalars(
            select(DailyWeatherSummary).where(
                DailyWeatherSummary.location_id == location.id,
                DailyWeatherSummary.source_name == LIVE_WEATHER_SOURCE,
                DailyWeatherSummary.date >= min(dates),
                DailyWeatherSummary.date <= max(dates),
            )
        ).all()
    }
    today = utc_now().astimezone(zone).date()
    now = utc_now()
    inserted = 0
    updated = 0
    for index, summary_date in enumerate(dates):
        values = {
            "temperature_min": _optional_float(daily.get("temperature_2m_min"), index),
            "temperature_max": _optional_float(daily.get("temperature_2m_max"), index),
            "temperature_mean": _optional_float(daily.get("temperature_2m_mean"), index),
        }
        if all(value is None for value in values.values()):
            continue
        summary = existing.get(summary_date)
        if summary is None:
            summary = DailyWeatherSummary(
                location_id=location.id,
                date=summary_date,
                source_name=LIVE_WEATHER_SOURCE,
                source_url=WEATHER_SOURCE_URL,
                source_type="forecast" if summary_date >= today else "modeled",
                is_forecast=summary_date >= today,
                ingested_at=now,
            )
            db.add(summary)
            existing[summary_date] = summary
            inserted += 1
        else:
            updated += 1
        for field, value in values.items():
            setattr(summary, field, value)
        summary.is_forecast = summary_date >= today
        summary.source_type = "forecast" if summary.is_forecast else "modeled"
        summary.ingested_at = now
    return inserted, updated


def _start_sync_run(db: Session, location: Location, source_name: str) -> SyncRun:
    run = SyncRun(
        source_name=source_name,
        location_id=location.id,
        started_at=utc_now(),
        status="running",
    )
    db.add(run)
    db.commit()
    return run


def _finish_success(db: Session, run: SyncRun) -> None:
    run.status = "success"
    run.completed_at = utc_now()
    db.commit()


def _finish_failure(db: Session, run_id: int, exc: Exception) -> None:
    db.rollback()
    run = db.get(SyncRun, run_id)
    if run:
        run.status = "failed"
        run.completed_at = utc_now()
        run.error_message = str(exc)[:1000]
        db.commit()


async def synchronize_weather(
    db: Session,
    location: Location,
    *,
    force: bool = False,
    settings: Settings | None = None,
) -> WeatherSyncResult:
    from app.services.incremental import sync_dataset
    settings = settings or get_settings()
    today = utc_now().date()
    first = today-timedelta(days=min(settings.weather_history_days, 90))
    results = []
    async with _weather_sync_lock:
        for source, begin, end, live in (
            (LIVE_WEATHER_SOURCE, today-timedelta(days=6), today+timedelta(days=6), True),
            (HISTORICAL_WEATHER_SOURCE, first, today-timedelta(days=7), False),
            (ARCHIVED_WEATHER_SOURCE, first, today, False)):
            try:
                results.append(await sync_dataset(db, location, source, begin, end, settings, live=live))
            except Exception:
                results.append({'status': 'failed', 'inserted': 0, 'updated': 0})
    statuses = [r['status'] for r in results]
    return WeatherSyncResult(status='partial' if 'failed' in statuses else ('cached' if set(statuses)=={'cached'} else 'success'),
        live_status=statuses[0], historical_status=statuses[1], archive_status=statuses[2],
        inserted=sum(r['inserted'] for r in results), updated=sum(r['updated'] for r in results),
        message='Inkrementalna provjera meteoroloških podataka završena.')


def _weather_out(reading: WeatherReading, now: datetime) -> WeatherReadingOut:
    measured_at = aware_utc(reading.measured_at)
    return WeatherReadingOut(
        measured_at=measured_at,
        temperature_2m=reading.temperature_2m,
        relative_humidity_2m=reading.relative_humidity_2m,
        wind_speed_10m=reading.wind_speed_10m,
        precipitation=reading.precipitation,
        source_name=reading.source_name,
        source_type="forecast" if measured_at > now else "modeled",
        is_forecast=measured_at > now,
    )


def build_weather_dashboard(db: Session, location: Location) -> WeatherDashboardResponse:
    now = utc_now()
    latest = db.scalar(
        select(WeatherReading)
        .where(
            WeatherReading.location_id == location.id,
            WeatherReading.source_name == LIVE_WEATHER_SOURCE,
            WeatherReading.forecast_lead_hours == 0,
            WeatherReading.measured_at <= now,
        )
        .order_by(WeatherReading.measured_at.desc())
        .limit(1)
    )
    forecast = db.scalars(
        select(WeatherReading)
        .where(
            WeatherReading.location_id == location.id,
            WeatherReading.source_name == LIVE_WEATHER_SOURCE,
            WeatherReading.forecast_lead_hours == 0,
            WeatherReading.measured_at > now,
        )
        .order_by(WeatherReading.measured_at.asc())
        .limit(24)
    ).all()
    local_today = now.astimezone(ZoneInfo(location.timezone)).date()
    daily = db.scalar(
        select(DailyWeatherSummary).where(
            DailyWeatherSummary.location_id == location.id,
            DailyWeatherSummary.source_name == LIVE_WEATHER_SOURCE,
            DailyWeatherSummary.date == local_today,
        )
    )
    last_sync = _last_source_sync(db, location.id, LIVE_WEATHER_SOURCE)
    return WeatherDashboardResponse(
        location=LocationOut.model_validate(location),
        latest=_weather_out(latest, now) if latest else None,
        daily=DailyWeatherOut(
            date=daily.date.isoformat(),
            temperature_min=daily.temperature_min,
            temperature_max=daily.temperature_max,
            temperature_mean=daily.temperature_mean,
            source_type=daily.source_type,
            is_forecast=daily.is_forecast,
        ) if daily else None,
        forecast=[_weather_out(item, now) for item in forecast],
        units=WEATHER_UNITS,
        source={
            "name": LIVE_WEATHER_SOURCE,
            "type": "modeled_and_forecast",
            "url": WEATHER_SOURCE_URL,
            "disclaimer": (
                f"Weather values are model output from Open-Meteo, not measurements from a local {location.name} station."
            ),
        },
        last_successful_sync=aware_utc(last_sync.completed_at)
        if last_sync and last_sync.completed_at
        else None,
    )

