from datetime import UTC, datetime, timedelta
from math import pi, sin

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import AirQualityReading, Location, WeatherReading
from app.services import weather_ml
from app.services.weather import ARCHIVED_WEATHER_SOURCE, LIVE_WEATHER_SOURCE
from app.services.weather_ml import generate_weather_model_comparison


def make_history(include_archived_weather: bool = True) -> tuple[Session, Location]:
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
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=24 * 20 - 1)
    ingested = datetime.now(UTC)
    for hour in range(24 * 20):
        timestamp = start + timedelta(hours=hour)
        temperature = 8 + 7 * sin(2 * pi * (hour % 24) / 24)
        wind = 5 + (hour % 8) * 0.4
        humidity = 75 - temperature
        pm25 = 24 + 6 * sin(2 * pi * (hour % 24) / 24) - wind * 0.25
        db.add(
            AirQualityReading(
                location_id=location.id,
                measured_at=timestamp,
                pm2_5=pm25,
                source_name="Open-Meteo / CAMS",
                source_url="https://open-meteo.com",
                source_type="modeled",
                model_name="CAMS",
                is_forecast=False,
                ingested_at=ingested,
            )
        )
        if include_archived_weather:
            db.add(
                WeatherReading(
                    location_id=location.id,
                    measured_at=timestamp,
                    temperature_2m=temperature,
                    relative_humidity_2m=humidity,
                    wind_speed_10m=wind,
                    precipitation=0.1 if hour % 17 == 0 else 0.0,
                    source_name=ARCHIVED_WEATHER_SOURCE,
                    source_url="https://open-meteo.com/en/docs/previous-runs-api",
                    source_type="archived_forecast",
                    model_name="Open-Meteo",
                    forecast_lead_hours=24,
                    is_forecast=False,
                    ingested_at=ingested,
                )
            )
    for step in range(1, 25):
        db.add(
            WeatherReading(
                location_id=location.id,
                measured_at=end + timedelta(hours=step),
                temperature_2m=10.0,
                relative_humidity_2m=70.0,
                wind_speed_10m=6.0,
                precipitation=0.0,
                source_name=LIVE_WEATHER_SOURCE,
                source_url="https://open-meteo.com/en/docs",
                source_type="forecast",
                model_name="Open-Meteo",
                forecast_lead_hours=0,
                is_forecast=True,
                ingested_at=ingested,
            )
        )
    db.commit()
    return db, location


def test_weather_model_uses_identical_24_step_evaluation_periods(monkeypatch) -> None:
    monkeypatch.setattr(weather_ml, "MODEL_ESTIMATORS", 12)
    db, location = make_history()
    result = generate_weather_model_comparison(db, location, 24)

    assert result.status == "ready"
    assert result.comparison_is_fair
    assert result.evaluation_horizon_hours == 24
    assert result.evaluation_origins > 0
    assert result.test_samples == result.evaluation_origins * 24
    assert result.training_samples == int(result.aligned_samples * 0.8)
    assert result.train_end is not None and result.test_start is not None
    assert result.train_end < result.test_start
    assert result.pollution_only is not None
    assert result.weather_aware is not None
    assert result.persistence is not None
    assert len(result.forecast) == 24
    assert "previous_day1" in result.limitation


def test_weather_model_refuses_unfair_observation_fallback(monkeypatch) -> None:
    monkeypatch.setattr(weather_ml, "MODEL_ESTIMATORS", 12)
    db, location = make_history(include_archived_weather=False)
    result = generate_weather_model_comparison(db, location, 24)
    assert result.status == "insufficient_data"
    assert not result.comparison_is_fair
    assert result.pollution_only is None
    assert result.weather_aware is None
