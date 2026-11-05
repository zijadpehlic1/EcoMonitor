from datetime import UTC, datetime, timedelta
from math import sqrt
from threading import Lock
from zoneinfo import ZoneInfo
from hashlib import sha256

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AirQualityReading, Location
from app.schemas import EvaluationMetrics, ForecastPoint, MLForecastResponse
from app.services.air_quality import aware_utc
from app.services.datasets import pm25_rows, provenance

MINIMUM_RAW_SAMPLES = 24 * 14
LAG_HOURS = 24
EVALUATION_HORIZON_HOURS = 24
_cache: dict[tuple[int, int, datetime, datetime, int], MLForecastResponse] = {}
_cache_lock = Lock()


def _time_features(timestamp: datetime) -> list[float]:
    timestamp = timestamp.astimezone(ZoneInfo("Europe/Sarajevo"))
    hour_angle = 2 * np.pi * timestamp.hour / 24
    weekday_angle = 2 * np.pi * timestamp.weekday() / 7
    return [
        float(np.sin(hour_angle)),
        float(np.cos(hour_angle)),
        float(np.sin(weekday_angle)),
        float(np.cos(weekday_angle)),
    ]


def _feature_row(history: list[float], timestamp: datetime) -> list[float]:
    return [
        history[-1],
        float(np.mean(history[-3:])),
        float(np.mean(history[-6:])),
        history[-24],
        float(np.mean(history[-24:])),
        *_time_features(timestamp),
    ]


def _error_metrics(actual: list[float], predicted: list[float]) -> tuple[float, float]:
    mae = float(mean_absolute_error(actual, predicted))
    rmse = sqrt(float(mean_squared_error(actual, predicted)))
    return mae, rmse


def _is_continuous_hourly(timestamps: list[datetime], start: int, end: int) -> bool:
    if start < 0 or end >= len(timestamps) or end <= start:
        return False
    return all(timestamps[index] - timestamps[index - 1] == timedelta(hours=1)
               for index in range(start + 1, end + 1))


def horizon_scores(actual, **predictions):
    result = {}
    for step in range(24):
        scores = {}
        for name, values in predictions.items():
            mae, rmse = _error_metrics(actual[step::24], values[step::24])
            scores[f"{name}_mae"] = round(mae, 3)
            scores[f"{name}_rmse"] = round(rmse, 3)
        result[step + 1] = scores
    return result


def _recursive_forecast(
    model: RandomForestRegressor,
    history: list[float],
    origin: datetime,
    horizon: int,
) -> list[float]:
    recursive_history = history.copy()
    predictions: list[float] = []
    for step in range(1, horizon + 1):
        timestamp = origin + timedelta(hours=step)
        predicted = max(0.0, float(model.predict([_feature_row(recursive_history, timestamp)])[0]))
        recursive_history.append(predicted)
        predictions.append(predicted)
    return predictions


def _insufficient(count: int, message: str) -> MLForecastResponse:
    return MLForecastResponse(
        status="insufficient_data",
        message=message,
        trained_samples=count,
        generated_at=datetime.now(UTC),
    )


def generate_pm25_forecast(db: Session, location: Location, horizon: int, source="modeled", station_id=None) -> MLForecastResponse:
    result = _generate(db, location, horizon, source, station_id).model_copy(deep=True)
    result.location = location.slug
    result.source_type = source
    result.station_id = station_id
    result.provenance = provenance(db, location, source, station_id)
    # A cached model must never turn yesterday's forecast into a current one.
    result.forecast = [p for p in result.forecast if p.timestamp > datetime.now(UTC)]
    if result.metrics and not result.forecast:
        result.status = "comparison_ready_forecast_unavailable"
    return result


def _generate(db, location, horizon, source, station_id):
    rows = pm25_rows(db, location, source, station_id)

    if len(rows) < MINIMUM_RAW_SAMPLES:
        return _insufficient(
            len(rows),
            f"At least {MINIMUM_RAW_SAMPLES} hourly PM2.5 values are required; {len(rows)} are available.",
        )

    timestamps = [aware_utc(row.measured_at) for row in rows]
    values = [float(row.pm2_5) for row in rows]
    latest_window_continuous = _is_continuous_hourly(timestamps, len(timestamps) - LAG_HOURS, len(timestamps) - 1)
    latest_stamp = timestamps[-1]
    latest_ingestion = max(aware_utc(row.ingested_at) for row in rows)
    fingerprint = sha256(repr([(t, v) for t, v in zip(timestamps, values)]).encode()).hexdigest()
    cache_key = (location.id, source, station_id, horizon, latest_stamp, latest_ingestion, fingerprint)
    with _cache_lock:
        if cache_key in _cache:
            return _cache[cache_key]

    features: list[list[float]] = []
    targets: list[float] = []
    target_times: list[datetime] = []
    feature_indices: list[int] = []
    for index in range(LAG_HOURS, len(values)):
        if not _is_continuous_hourly(timestamps, index - LAG_HOURS, index):
            continue
        features.append(_feature_row(values[:index], timestamps[index]))
        targets.append(values[index])
        target_times.append(timestamps[index])
        feature_indices.append(index)

    if len(targets) < 200:
        return _insufficient(
            len(targets),
            "The stored series does not contain enough continuous hourly history for leakage-safe training.",
        )

    x = np.asarray(features, dtype=float)
    y = np.asarray(targets, dtype=float)
    split = int(len(y) * 0.8)
    if len(y) - split < 24:
        return _insufficient(len(y), "At least 24 chronological hold-out samples are required.")

    model = RandomForestRegressor(
        n_estimators=180,
        max_depth=12,
        min_samples_leaf=3,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(x[:split], y[:split])
    # Recursive evaluation performs many small predictions; one worker avoids
    # parallel scheduling overhead and warning amplification for each step.
    model.n_jobs = 1

    first_test_index = feature_indices[split]
    candidate_origin = first_test_index - 1
    evaluated_actuals: list[float] = []
    evaluated_predictions: list[float] = []
    evaluated_baseline: list[float] = []
    evaluated_times: list[datetime] = []
    evaluation_origins = 0

    while candidate_origin + EVALUATION_HORIZON_HOURS < len(values):
        history_start = candidate_origin - (LAG_HOURS - 1)
        forecast_end = candidate_origin + EVALUATION_HORIZON_HOURS
        if _is_continuous_hourly(timestamps, history_start, forecast_end):
            origin_value = values[candidate_origin]
            predictions = _recursive_forecast(
                model,
                values[: candidate_origin + 1],
                timestamps[candidate_origin],
                EVALUATION_HORIZON_HOURS,
            )
            actuals = values[candidate_origin + 1 : forecast_end + 1]
            evaluated_actuals.extend(actuals)
            evaluated_predictions.extend(predictions)
            evaluated_baseline.extend([origin_value] * EVALUATION_HORIZON_HOURS)
            evaluated_times.extend(timestamps[candidate_origin + 1 : forecast_end + 1])
            evaluation_origins += 1
            candidate_origin += EVALUATION_HORIZON_HOURS
        else:
            candidate_origin += 1

    if not evaluated_actuals:
        return _insufficient(
            len(y),
            "The chronological hold-out does not contain one continuous 24-hour forecast window.",
        )

    mae, rmse = _error_metrics(evaluated_actuals, evaluated_predictions)
    baseline_mae, baseline_rmse = _error_metrics(evaluated_actuals, evaluated_baseline)
    improvement = ((baseline_mae - mae) / baseline_mae * 100) if baseline_mae else 0.0

    model.n_jobs = -1
    model.fit(x, y)
    model.n_jobs = 1
    final_predictions = (_recursive_forecast(model, values, latest_stamp, horizon)
        if latest_window_continuous and datetime.now(UTC) - latest_stamp <= timedelta(hours=3) else [])
    forecast_points: list[ForecastPoint] = []
    for step, predicted in enumerate(final_predictions, start=1):
        forecast_points.append(
            ForecastPoint(
                timestamp=latest_stamp + timedelta(hours=step),
                predicted_pm2_5=round(predicted, 2),
            )
        )

    response = MLForecastResponse(
        status="ready" if forecast_points else "comparison_ready_forecast_unavailable",
        message=(
            "The initial 80% of the series trains the evaluation model. Metrics use non-overlapping, "
            "24-step recursive forecasts in the final 20% with no evaluation-time model refitting."
        ),
        model="Random forest autoregression with 1h/3h/6h/24h lags and cyclical time features",
        trained_samples=len(y),
        metrics=EvaluationMetrics(
            by_horizon=horizon_scores(evaluated_actuals, model=evaluated_predictions, persistence=evaluated_baseline),
            test_samples=len(evaluated_actuals),
            evaluation_horizon_hours=EVALUATION_HORIZON_HOURS,
            evaluation_origins=evaluation_origins,
            mae=round(mae, 3),
            rmse=round(rmse, 3),
            baseline_mae=round(baseline_mae, 3),
            baseline_rmse=round(baseline_rmse, 3),
            improvement_over_baseline_percent=round(improvement, 1),
            train_start=target_times[0],
            train_end=target_times[split - 1],
            test_start=evaluated_times[0],
            test_end=evaluated_times[-1],
        ),
        forecast=forecast_points,
        generated_at=datetime.now(UTC),
    )
    with _cache_lock:
        if len(_cache) >= 16:
            _cache.pop(next(iter(_cache)))
        _cache[cache_key] = response
    return response

