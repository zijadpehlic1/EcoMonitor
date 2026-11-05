from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from statistics import fmean
from math import isfinite
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AirQualityReading, Location, WeatherReading
from app.schemas import HistoricalPointOut, HistoricalSeriesResponse, LocationOut
from app.services.air_quality import MODEL_NAME, SOURCE_NAME, SOURCE_URL, aware_utc, utc_now
from app.services.datasets import pollution_rows, resolve_station
from app.services.weather import (
    HISTORICAL_WEATHER_SOURCE,
    HISTORICAL_WEATHER_SOURCE_URL,
    LIVE_WEATHER_SOURCE,
    WEATHER_SOURCE_URL,
)

SERIES_FIELDS = (
    "pm2_5",
    "pm10",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "carbon_monoxide",
    "ozone",
    "temperature_2m",
)
POLLUTION_FIELDS = SERIES_FIELDS[:-1]
UNITS = {field: "μg/m³" for field in POLLUTION_FIELDS} | {"temperature_2m": "°C"}


def _bucket_start(timestamp: datetime, grouping: str, zone: ZoneInfo) -> tuple[datetime, str]:
    timestamp = aware_utc(timestamp)
    local = timestamp.astimezone(zone)
    if grouping == "hourly":
        # UTC keeps both occurrences of a repeated local hour distinct during the
        # autumn DST transition.
        return timestamp.replace(minute=0, second=0, microsecond=0), local.date().isoformat()
    local_midnight = datetime.combine(local.date(), time.min, tzinfo=zone)
    return local_midnight.astimezone(UTC), local.date().isoformat()


def _expected_samples(local_date: str, grouping: str, zone: ZoneInfo) -> int:
    if grouping == "hourly":
        return 1
    day = date.fromisoformat(local_date)
    start = datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    return int((end - start).total_seconds() // 3600)


def aggregate_history(
    pollution: list[AirQualityReading],
    weather: list[WeatherReading],
    *,
    grouping: str,
    aggregation: str,
    timezone: str,
    start: datetime | None = None,
    end: datetime | None = None,
    interval_end: bool = False,
) -> list[HistoricalPointOut]:
    """Aggregate one pollution source and modeled weather by Sarajevo calendar time."""
    zone = ZoneInfo(timezone)
    buckets: dict[datetime, dict[str, list[tuple[datetime, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    local_dates: dict[datetime, str] = {}

    for row in pollution:
        stamp = aware_utc(row.measured_at)
        bucket, local_date = _bucket_start(stamp - timedelta(microseconds=1) if interval_end and grouping == 'daily' else stamp, grouping, zone)
        local_dates[bucket] = local_date
        for field in POLLUTION_FIELDS:
            value = getattr(row, field)
            if value is not None and isfinite(value) and value >= 0:
                buckets[bucket][field].append((stamp, float(value)))

    # Prefer operational weather values for overlapping recent hours; use the
    # historical reanalysis for the older portion of 30/90-day ranges.
    chosen_weather: dict[datetime, WeatherReading] = {}
    priority = {HISTORICAL_WEATHER_SOURCE: 1, LIVE_WEATHER_SOURCE: 2}
    for row in weather:
        if row.temperature_2m is None or not isfinite(row.temperature_2m):
            continue
        stamp = aware_utc(row.measured_at)
        current = chosen_weather.get(stamp)
        if current is None or priority.get(row.source_name, 0) > priority.get(current.source_name, 0):
            chosen_weather[stamp] = row
    for stamp, row in chosen_weather.items():
        if row.temperature_2m is None:
            continue
        bucket, local_date = _bucket_start(stamp, grouping, zone)
        local_dates[bucket] = local_date
        buckets[bucket]["temperature_2m"].append((stamp, float(row.temperature_2m)))

    # Missing buckets must exist as nulls, otherwise Recharts bridges the gap.
    if local_dates or (start is not None and end is not None):
        cursor = _bucket_start(start or min(local_dates), grouping, zone)[0]
        last = _bucket_start(end or max(local_dates), grouping, zone)[0]
        while cursor <= last:
            bucket, local_date = _bucket_start(cursor, grouping, zone)
            local_dates[bucket] = local_date
            buckets[bucket]
            cursor += timedelta(hours=1 if grouping == "hourly" else _expected_samples(local_date, grouping, zone))
    result: list[HistoricalPointOut] = []
    for bucket in sorted(buckets):
        samples = buckets[bucket]
        values: dict[str, float | None] = {}
        counts: dict[str, int] = {}
        peaks: dict[str, datetime | None] = {}
        for field in SERIES_FIELDS:
            field_samples = samples.get(field, [])
            if grouping == "daily":
                # Each hour has equal weight even when a provider has subhourly samples.
                hourly = defaultdict(list)
                for stamp, value in field_samples:
                    hourly[stamp.replace(minute=0, second=0, microsecond=0)].append(value)
                field_samples = [(stamp, fmean(values)) for stamp, values in sorted(hourly.items())]
            counts[field] = len(field_samples)
            if not field_samples:
                values[field] = None
                peaks[field] = None
            elif aggregation == "maximum":
                peak_stamp, peak_value = max(field_samples, key=lambda item: item[1])
                values[field] = peak_value
                peaks[field] = peak_stamp
            else:
                values[field] = fmean(value for _, value in field_samples)
                peaks[field] = None
        local_date = local_dates[bucket]
        result.append(
            HistoricalPointOut(
                timestamp=bucket,
                local_date=local_date,
                sample_counts=counts,
                peak_timestamps=peaks,
                expected_samples=_expected_samples(local_date, grouping, zone),
                **values,
            )
        )
    return result


def build_historical_series(
    db: Session,
    location: Location,
    *,
    hours: int,
    grouping: str,
    aggregation: str,
    source: str = "modeled",
    station_id: int | None = None,
) -> HistoricalSeriesResponse:
    now = utc_now()
    start = now - timedelta(hours=hours)
    pollution = pollution_rows(db, location, source, station_id, start=start, end=now)
    source_info = {"name": SOURCE_NAME, "model": MODEL_NAME, "type": "modeled", "url": SOURCE_URL}
    if source == "sensor":
        station = resolve_station(db, location, station_id)
        source_info = {"name": station.provider, "station": station.name, "station_id": str(station.id),
            "type": "sensor", "url": station.source_url, "attribution": station.attribution,
            "validation_status": "unvalidated", "timestamp_semantics": "provider_hour_label / OpenAQ interval_end"}
    weather = list(
        db.scalars(
            select(WeatherReading)
            .where(
                WeatherReading.location_id == location.id,
                WeatherReading.measured_at >= start,
                WeatherReading.measured_at <= now,
                WeatherReading.forecast_lead_hours == 0,
                WeatherReading.source_name.in_([LIVE_WEATHER_SOURCE, HISTORICAL_WEATHER_SOURCE]),
            )
            .order_by(WeatherReading.measured_at.asc())
        ).all()
    )
    weather_names = {row.source_name for row in weather}
    weather_sources = []
    if LIVE_WEATHER_SOURCE in weather_names:
        weather_sources.append(
            {"name": LIVE_WEATHER_SOURCE, "type": "modeled", "url": WEATHER_SOURCE_URL}
        )
    if HISTORICAL_WEATHER_SOURCE in weather_names:
        weather_sources.append(
            {
                "name": HISTORICAL_WEATHER_SOURCE,
                "type": "historical_modeled_reanalysis",
                "url": HISTORICAL_WEATHER_SOURCE_URL,
            }
        )
    return HistoricalSeriesResponse(
        location=LocationOut.model_validate(location),
        grouping=grouping,
        aggregation=aggregation,
        requested_hours=hours,
        points=aggregate_history(
            pollution,
            weather,
            grouping=grouping,
            aggregation=aggregation,
            timezone=location.timezone,
            start=start,
            end=now,
            interval_end=source == 'sensor',
        ),
        units=UNITS,
        pollution_source=source_info,
        weather_sources=weather_sources,
        timezone=location.timezone,
        generated_at=now,
        completeness_note=(
            "Sample counts are reported separately for every series. A local calendar day may contain "
            "23, 24, or 25 expected hourly samples because of daylight-saving time; missing samples are "
            "not imputed. A single selected source/station is used; flagged/incomplete sensor hours are excluded."
        ),
    )
