from datetime import UTC, datetime, timedelta
from math import pi, sin, sqrt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import AirQualityReading, Location
from app.services.ml_forecast import _error_metrics, _feature_row, generate_pm25_forecast


def test_ml_uses_chronological_holdout_and_returns_metrics() -> None:
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
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=24 * 20 - 1)
    for hour in range(24 * 20):
        value = 24 + 8 * sin(2 * pi * (hour % 24) / 24) + (hour % 7) * 0.2
        db.add(
            AirQualityReading(
                location_id=location.id,
                measured_at=start + timedelta(hours=hour),
                pm2_5=value,
                source_name="Open-Meteo / CAMS",
                source_url="https://open-meteo.com",
                source_type="modeled",
                model_name="CAMS",
                is_forecast=False,
                ingested_at=datetime.now(UTC),
            )
        )
    db.commit()

    result = generate_pm25_forecast(db, location, 24)
    assert result.status == "ready"
    assert len(result.forecast) == 24
    assert result.metrics is not None
    assert result.metrics.train_end < result.metrics.test_start
    assert result.metrics.evaluation_horizon_hours == 24
    assert result.metrics.evaluation_origins > 0
    assert result.metrics.test_samples == result.metrics.evaluation_origins * 24
    assert result.metrics.mae >= 0


def test_error_metrics_are_calculated_from_matching_pairs() -> None:
    mae, rmse = _error_metrics([1.0, 3.0], [2.0, 1.0])
    assert mae == pytest.approx(1.5)
    assert rmse == pytest.approx(sqrt(2.5))


def test_feature_row_uses_only_prior_history() -> None:
    history = [float(value) for value in range(1, 25)]
    target_time = datetime(2026, 1, 2, tzinfo=UTC)
    features = _feature_row(history, target_time)
    assert features[0] == 24.0
    assert features[3] == 1.0
    assert features[4] == pytest.approx(sum(history) / 24)

