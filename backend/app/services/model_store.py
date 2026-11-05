"""Versioned JSON-only regression forests: no pickle or executable deserialization."""
import json
from hashlib import sha256
from datetime import timedelta
import numpy as np
import sklearn
from app.models import ModelArtifact
from app.services.air_quality import utc_now, aware_utc
from app.core.config import get_settings

VERSION = f'rf180-depth12-leaf3-seed42-lags24-sarajevo-walk24-v1:sklearn-{sklearn.__version__}'


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def snapshot(timestamps, values, weather=None):
    return [[t.isoformat(), value, (weather or {}).get(t)] for t, value in zip(timestamps, values)]


class JsonForest:
    def __init__(self, trees):
        self.trees = trees

    def predict(self, features):
        # sklearn trees use float32 inputs; retaining that convention matters at thresholds.
        x = np.asarray(features, dtype=np.float32)
        result = []
        for row in x:
            total = 0.0
            for tree in self.trees:
                node = 0
                while tree['left'][node] != -1:
                    node = tree['left'][node] if row[tree['feature'][node]] <= tree['threshold'][node] else tree['right'][node]
                total += tree['value'][node]
            result.append(total / len(self.trees))
        return np.asarray(result)


def encode_forest(model):
    return [{'left': e.tree_.children_left.tolist(), 'right': e.tree_.children_right.tolist(),
        'feature': e.tree_.feature.tolist(), 'threshold': e.tree_.threshold.tolist(),
        'value': e.tree_.value[:, 0, 0].tolist()} for e in model.estimators_]


def artifact_key(location, source, station_id, kind):
    return f'{location.slug}:{source}:{station_id or 0}:{kind}'


def reusable(db, key, data, response_cls):
    artifact = db.get(ModelArtifact, key)
    if not artifact or artifact.version != VERSION:
        return None
    meta = json.loads(artifact.metadata_json)
    previous_count = meta['samples']
    # Any correction/removal in the previously trained/evaluated prefix invalidates both.
    if len(data) < previous_count or digest(data[:previous_count]) != meta['data_version']:
        return None
    config = get_settings()
    new_count = len(data) - previous_count
    if new_count >= config.ml_min_new_samples and utc_now()-aware_utc(artifact.trained_at) >= timedelta(hours=config.ml_retrain_hours):
        return None
    trees = json.loads(artifact.forest_json)
    if digest(trees) != meta['forest_checksum']:
        return None
    return JsonForest(trees), response_cls.model_validate_json(artifact.evaluation_json)


def save(db, key, data, model, response):
    trees = encode_forest(model)
    db.merge(ModelArtifact(key=key, version=VERSION,
        metadata_json=json.dumps({'samples': len(data), 'data_version': digest(data), 'forest_checksum': digest(trees)}),
        forest_json=json.dumps(trees, separators=(',', ':')), evaluation_json=response.model_dump_json(), trained_at=utc_now()))
    db.commit()


def base_prediction(model, response, values, stamps, horizon):
    from app.services.ml_forecast import _recursive_forecast, _is_continuous_hourly
    from app.schemas import ForecastPoint
    result = response.model_copy(deep=True)
    valid = _is_continuous_hourly(stamps, len(stamps)-24, len(stamps)-1) and utc_now()-stamps[-1] <= timedelta(hours=3)
    predictions = _recursive_forecast(model, values, stamps[-1], horizon) if valid else []
    result.forecast = [ForecastPoint(timestamp=stamps[-1]+timedelta(hours=i), predicted_pm2_5=round(value,2))
        for i, value in enumerate(predictions, 1)]
    result.status = 'ready' if result.forecast else 'comparison_ready_forecast_unavailable'
    result.generated_at = utc_now()
    return result


def weather_prediction(model, response, values, stamps, future_rows, horizon):
    from app.services.weather_ml import _weather_values, _weather_feature_row
    from app.services.ml_forecast import _is_continuous_hourly
    from app.schemas import WeatherAwareForecastPoint
    future = {aware_utc(r.measured_at): _weather_values(r) for r in future_rows}
    valid = (_is_continuous_hourly(stamps, len(stamps)-24, len(stamps)-1)
        and utc_now()-stamps[-1] <= timedelta(hours=3)
        and all(utc_now()-aware_utc(r.ingested_at) <= timedelta(hours=3) for r in future_rows)
        and all(future.get(stamps[-1]+timedelta(hours=i)) is not None for i in range(1,horizon+1)))
    result = response.model_copy(deep=True)
    result.forecast = []
    history = values.copy()
    if valid:
        for step in range(1, horizon+1):
            stamp = stamps[-1]+timedelta(hours=step)
            value = max(0., float(model.predict([_weather_feature_row(history, stamp, future[stamp])])[0]))
            history.append(value)
            result.forecast.append(WeatherAwareForecastPoint(timestamp=stamp, predicted_pm2_5=round(value,2)))
    result.status = 'ready' if result.forecast else 'comparison_ready_forecast_unavailable'
    result.generated_at = utc_now()
    return result
