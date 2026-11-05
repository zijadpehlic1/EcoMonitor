from datetime import UTC, datetime, timedelta
from threading import Lock
from hashlib import sha256

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AirQualityReading, Location, WeatherReading
from app.schemas import (
    ComparisonScore,
    WeatherAwareForecastPoint,
    WeatherModelComparisonResponse,
)
from app.services.air_quality import aware_utc
from app.services.datasets import pm25_rows, provenance
from app.services.ml_forecast import (
    EVALUATION_HORIZON_HOURS,
    LAG_HOURS,
    _error_metrics,
    _feature_row,
    _is_continuous_hourly,
    horizon_scores,
)
from app.services.weather import ARCHIVED_WEATHER_SOURCE, LIVE_WEATHER_SOURCE

MINIMUM_ALIGNED_SAMPLES = 200
MODEL_ESTIMATORS = 180
WEATHER_FEATURE_NAMES = [
    "temperature_2m",
    "wind_speed_10m",
    "relative_humidity_2m",
    "precipitation",
    "day_of_year_sin",
    "day_of_year_cos",
]
LIMITATION = (
    "Historical evaluation uses Open-Meteo Previous Runs values tagged previous_day1. "
    "Each meteorological value was issued 24 hours before its valid timestamp and was therefore "
    "available by the PM2.5 prediction origin. The 1–24 hour weather inputs do not represent one "
    "single archived model run issued at that origin, so the comparison is leakage-safe but remains "
    "an approximation of an operational forecast workflow."
)
_cache: dict[tuple, WeatherModelComparisonResponse] = {}
_cache_lock = Lock()


def _model() -> RandomForestRegressor:
    return RandomForestRegressor(
        n_estimators=MODEL_ESTIMATORS,
        max_depth=12,
        min_samples_leaf=3,
        random_state=42,
        n_jobs=1,
    )


def _weather_values(reading: WeatherReading) -> list[float] | None:
    values = (
        reading.temperature_2m,
        reading.wind_speed_10m,
        reading.relative_humidity_2m,
        reading.precipitation,
    )
    if any(value is None or not np.isfinite(value) for value in values):
        return None
    return [float(value) for value in values]


def _season_features(timestamp: datetime) -> list[float]:
    angle = 2 * np.pi * (timestamp.timetuple().tm_yday - 1) / 365.25
    return [float(np.sin(angle)), float(np.cos(angle))]


def _weather_feature_row(
    history: list[float],
    timestamp: datetime,
    weather: list[float],
) -> list[float]:
    return [*_feature_row(history, timestamp), *weather, *_season_features(timestamp)]


def _insufficient(message: str, *, samples: int = 0) -> WeatherModelComparisonResponse:
    return WeatherModelComparisonResponse(
        status="insufficient_data",
        message=message,
        comparison_is_fair=False,
        limitation=LIMITATION,
        aligned_samples=samples,
        test_samples=0,
        features=WEATHER_FEATURE_NAMES,
        generated_at=datetime.now(UTC),
    )


def generate_weather_model_comparison(
    db: Session,
    location: Location,
    horizon: int,
    source="modeled",
    station_id=None,
) -> WeatherModelComparisonResponse:
    result = _generate(db, location, horizon, source, station_id).model_copy(deep=True)
    result.location = location.slug
    result.source_type = source
    result.station_id = station_id
    result.provenance = provenance(db, location, source, station_id)
    result.forecast = [p for p in result.forecast if p.timestamp > datetime.now(UTC)]
    if result.pollution_only and not result.forecast:
        result.status = "comparison_ready_forecast_unavailable"
    return result


def _generate(db, location, horizon, source, station_id):
    air_rows = pm25_rows(db, location, source, station_id)
    if len(air_rows) < LAG_HOURS + MINIMUM_ALIGNED_SAMPLES:
        return _insufficient(
            "Not enough PM2.5 history is available for an aligned weather-aware evaluation."
        )

    timestamps = [aware_utc(row.measured_at) for row in air_rows]
    values = [float(row.pm2_5) for row in air_rows]
    latest_stamp = timestamps[-1]
    latest_window_continuous = _is_continuous_hourly(timestamps, len(timestamps) - LAG_HOURS, len(timestamps) - 1)

    archived_rows = db.scalars(
        select(WeatherReading).where(
            WeatherReading.location_id == location.id,
            WeatherReading.source_name == ARCHIVED_WEATHER_SOURCE,
            WeatherReading.forecast_lead_hours == 24,
            WeatherReading.measured_at >= timestamps[0],
            WeatherReading.measured_at <= timestamps[-1],
        )
    ).all()
    archived_weather = {
        aware_utc(row.measured_at): weather
        for row in archived_rows
        if (weather := _weather_values(row)) is not None
    }
    if not archived_weather:
        return _insufficient(
            "Archived meteorological forecasts are unavailable. EcoMonitor will not substitute "
            "future observations or reanalysis data because that would make the comparison unfair."
        )

    future_rows = db.scalars(
        select(WeatherReading)
        .where(
            WeatherReading.location_id == location.id,
            WeatherReading.source_name == LIVE_WEATHER_SOURCE,
            WeatherReading.forecast_lead_hours == 0,
            WeatherReading.measured_at > latest_stamp,
            WeatherReading.measured_at <= latest_stamp + timedelta(hours=horizon),
        )
        .order_by(WeatherReading.measured_at.asc())
    ).all()
    future_weather = {
        aware_utc(row.measured_at): weather
        for row in future_rows
        if (weather := _weather_values(row)) is not None
    }
    latest_air_ingestion = max(aware_utc(row.ingested_at) for row in air_rows)
    latest_weather_ingestion = max(
        (aware_utc(row.ingested_at) for row in [*archived_rows, *future_rows]),
        default=datetime.min.replace(tzinfo=UTC),
    )
    cache_key = (
        location.id,
        source, station_id,
        sha256(repr([(t, v) for t, v in zip(timestamps, values)]).encode()).hexdigest(),
        horizon,
        latest_stamp,
        latest_air_ingestion,
        latest_weather_ingestion,
        len(air_rows),
        len(archived_rows),
        len(future_rows),
    )
    with _cache_lock:
        cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    from app.services import model_store
    artifact_key = model_store.artifact_key(location, source, station_id, 'weather')
    training_data = model_store.snapshot(timestamps, values, archived_weather)
    saved = model_store.reusable(db, artifact_key, training_data, WeatherModelComparisonResponse)
    if saved:
        return model_store.weather_prediction(*saved, values, timestamps, future_rows, horizon)

    base_features: list[list[float]] = []
    weather_features: list[list[float]] = []
    targets: list[float] = []
    target_times: list[datetime] = []
    raw_indices: list[int] = []
    for index in range(LAG_HOURS, len(values)):
        timestamp = timestamps[index]
        weather = archived_weather.get(timestamp)
        if weather is None or not _is_continuous_hourly(timestamps, index - LAG_HOURS, index):
            continue
        base = _feature_row(values[:index], timestamp)
        base_features.append(base)
        weather_features.append([*base, *weather, *_season_features(timestamp)])
        targets.append(values[index])
        target_times.append(timestamp)
        raw_indices.append(index)

    if len(targets) < MINIMUM_ALIGNED_SAMPLES:
        return _insufficient(
            f"At least {MINIMUM_ALIGNED_SAMPLES} timestamp-aligned PM2.5 and archived weather "
            f"samples are required; {len(targets)} are available.",
            samples=len(targets),
        )

    x_base = np.asarray(base_features, dtype=float)
    x_weather = np.asarray(weather_features, dtype=float)
    y = np.asarray(targets, dtype=float)
    split = int(len(y) * 0.8)
    if len(y) - split < EVALUATION_HORIZON_HOURS:
        return _insufficient("At least 24 chronological hold-out samples are required.")

    base_model = _model()
    weather_model = _model()
    base_model.fit(x_base[:split], y[:split])
    weather_model.fit(x_weather[:split], y[:split])
    base_model.n_jobs = 1
    weather_model.n_jobs = 1

    candidate_origin = raw_indices[split] - 1
    actuals_all: list[float] = []
    base_all: list[float] = []
    weather_all: list[float] = []
    persistence_all: list[float] = []
    evaluated_times: list[datetime] = []
    origins = 0

    while candidate_origin + EVALUATION_HORIZON_HOURS < len(values):
        end = candidate_origin + EVALUATION_HORIZON_HOURS
        target_range = range(candidate_origin + 1, end + 1)
        target_weather = [archived_weather.get(timestamps[index]) for index in target_range]
        continuous = _is_continuous_hourly(
            timestamps,
            candidate_origin - (LAG_HOURS - 1),
            end,
        )
        if continuous and all(item is not None for item in target_weather):
            base_history = values[: candidate_origin + 1]
            weather_history = base_history.copy()
            base_predictions: list[float] = []
            weather_predictions: list[float] = []
            origin = timestamps[candidate_origin]
            for step, weather in enumerate(target_weather, start=1):
                timestamp = origin + timedelta(hours=step)
                base_pred = max(
                    0.0,
                    float(base_model.predict([_feature_row(base_history, timestamp)])[0]),
                )
                weather_pred = max(
                    0.0,
                    float(
                        weather_model.predict(
                            [_weather_feature_row(weather_history, timestamp, weather)]
                        )[0]
                    ),
                )
                base_history.append(base_pred)
                weather_history.append(weather_pred)
                base_predictions.append(base_pred)
                weather_predictions.append(weather_pred)

            actuals = values[candidate_origin + 1 : end + 1]
            actuals_all.extend(actuals)
            base_all.extend(base_predictions)
            weather_all.extend(weather_predictions)
            persistence_all.extend([values[candidate_origin]] * EVALUATION_HORIZON_HOURS)
            evaluated_times.extend(timestamps[candidate_origin + 1 : end + 1])
            origins += 1
            candidate_origin += EVALUATION_HORIZON_HOURS
        else:
            candidate_origin += 1

    if not actuals_all:
        return _insufficient(
            "The common chronological hold-out contains no complete 24-hour window with archived "
            "meteorological forecasts available at every target hour."
        )

    base_mae, base_rmse = _error_metrics(actuals_all, base_all)
    weather_mae, weather_rmse = _error_metrics(actuals_all, weather_all)
    persistence_mae, persistence_rmse = _error_metrics(actuals_all, persistence_all)
    change = ((base_mae - weather_mae) / base_mae * 100) if base_mae else 0.0

    weather_model.n_jobs = 1
    weather_model.fit(x_weather, y)
    weather_model.n_jobs = 1
    recursive_history = values.copy()
    forecast: list[WeatherAwareForecastPoint] = []
    complete_future_weather = all(
        latest_stamp + timedelta(hours=step) in future_weather
        for step in range(1, horizon + 1)
    ) and latest_window_continuous and datetime.now(UTC) - latest_stamp <= timedelta(hours=3) and all(
        datetime.now(UTC) - aware_utc(row.ingested_at) <= timedelta(hours=3) for row in future_rows)
    if complete_future_weather:
        for step in range(1, horizon + 1):
            timestamp = latest_stamp + timedelta(hours=step)
            predicted = max(
                0.0,
                float(
                    weather_model.predict(
                        [
                            _weather_feature_row(
                                recursive_history,
                                timestamp,
                                future_weather[timestamp],
                            )
                        ]
                    )[0]
                ),
            )
            recursive_history.append(predicted)
            forecast.append(
                WeatherAwareForecastPoint(
                    timestamp=timestamp,
                    predicted_pm2_5=round(predicted, 2),
                )
            )

    forecast_note = (
        " The operational forecast uses current Open-Meteo weather forecast variables."
        if complete_future_weather
        else " Comparative metrics are available, but a new forecast is withheld because the "
        "complete future weather horizon is unavailable."
    )
    response = WeatherModelComparisonResponse(
        status="ready" if complete_future_weather else "comparison_ready_forecast_unavailable",
        message=(
            "Both Random Forest models use the same chronological training period, identical "
            "non-overlapping 24-step recursive hold-out origins and the same PM2.5 targets."
            + forecast_note
        ),
        comparison_is_fair=True,
        by_horizon=horizon_scores(actuals_all, pollution_only=base_all, weather_aware=weather_all, persistence=persistence_all),
        limitation=LIMITATION,
        aligned_samples=len(y),
        training_samples=split,
        evaluation_origins=origins,
        test_samples=len(actuals_all),
        train_start=target_times[0],
        train_end=target_times[split - 1],
        test_start=evaluated_times[0],
        test_end=evaluated_times[-1],
        pollution_only=ComparisonScore(mae=round(base_mae, 3), rmse=round(base_rmse, 3)),
        weather_aware=ComparisonScore(mae=round(weather_mae, 3), rmse=round(weather_rmse, 3)),
        persistence=ComparisonScore(
            mae=round(persistence_mae, 3),
            rmse=round(persistence_rmse, 3),
        ),
        weather_mae_change_percent=round(change, 1),
        features=WEATHER_FEATURE_NAMES,
        forecast=forecast,
        generated_at=datetime.now(UTC),
    )
    model_store.save(db, artifact_key, training_data, weather_model, response)
    with _cache_lock:
        if len(_cache) >= 16:
            _cache.pop(next(iter(_cache)))
        _cache[cache_key] = response
    return response
