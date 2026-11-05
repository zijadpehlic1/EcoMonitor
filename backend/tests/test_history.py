from datetime import UTC, datetime

import pytest

from app.models import AirQualityReading, WeatherReading
from app.services.history import aggregate_history
from app.services.weather import LIVE_WEATHER_SOURCE


def pollution(stamp: datetime, **values: float | None) -> AirQualityReading:
    return AirQualityReading(
        measured_at=stamp,
        pm2_5=values.get("pm2_5"),
        pm10=values.get("pm10"),
        nitrogen_dioxide=values.get("nitrogen_dioxide"),
        sulphur_dioxide=values.get("sulphur_dioxide"),
        carbon_monoxide=values.get("carbon_monoxide"),
        ozone=values.get("ozone"),
    )


def weather(stamp: datetime, temperature: float | None) -> WeatherReading:
    return WeatherReading(
        measured_at=stamp,
        temperature_2m=temperature,
        source_name=LIVE_WEATHER_SOURCE,
        forecast_lead_hours=0,
    )


def test_daily_maximum_is_independent_for_every_series_and_reports_peak_time() -> None:
    stamps = [
        datetime(2026, 1, 15, hour, tzinfo=UTC)
        for hour in (8, 9, 10)
    ]
    points = aggregate_history(
        [
            pollution(stamps[0], pm2_5=10, pm10=40),
            pollution(stamps[1], pm2_5=30, pm10=20),
            pollution(stamps[2], pm2_5=20, pm10=10),
        ],
        [weather(stamps[0], 1), weather(stamps[1], 3), weather(stamps[2], 8)],
        grouping="daily",
        aggregation="maximum",
        timezone="Europe/Sarajevo",
    )

    assert len(points) == 1
    assert points[0].pm2_5 == 30
    assert points[0].pm10 == 40
    assert points[0].temperature_2m == 8
    assert points[0].peak_timestamps["pm2_5"] == stamps[1]
    assert points[0].peak_timestamps["pm10"] == stamps[0]
    assert points[0].peak_timestamps["temperature_2m"] == stamps[2]


def test_daily_average_uses_only_available_values_and_exposes_missing_samples() -> None:
    first = datetime(2026, 2, 2, 8, tzinfo=UTC)
    second = datetime(2026, 2, 2, 9, tzinfo=UTC)
    points = aggregate_history(
        [pollution(first, pm2_5=10, pm10=None), pollution(second, pm2_5=20, pm10=12)],
        [weather(first, 2), weather(second, None)],
        grouping="daily",
        aggregation="average",
        timezone="Europe/Sarajevo",
    )

    assert points[0].pm2_5 == 15
    assert points[0].pm10 == 12
    assert points[0].temperature_2m == 2
    assert points[0].sample_counts["pm2_5"] == 2
    assert points[0].sample_counts["pm10"] == 1
    assert points[0].sample_counts["temperature_2m"] == 1
    assert points[0].expected_samples == 24
    assert points[0].peak_timestamps["pm2_5"] is None


def test_hourly_grouping_keeps_hours_separate_and_aggregates_duplicate_samples() -> None:
    points = aggregate_history(
        [
            pollution(datetime(2026, 3, 4, 10, 5, tzinfo=UTC), pm2_5=8),
            pollution(datetime(2026, 3, 4, 10, 50, tzinfo=UTC), pm2_5=12),
            pollution(datetime(2026, 3, 4, 11, 0, tzinfo=UTC), pm2_5=20),
        ],
        [],
        grouping="hourly",
        aggregation="average",
        timezone="Europe/Sarajevo",
    )

    assert [point.pm2_5 for point in points] == [10, 20]
    assert [point.sample_counts["pm2_5"] for point in points] == [2, 1]
    assert all(point.expected_samples == 1 for point in points)


def test_sarajevo_calendar_boundary_uses_local_date_not_utc_date() -> None:
    points = aggregate_history(
        [
            pollution(datetime(2026, 1, 1, 22, 30, tzinfo=UTC), pm2_5=5),
            pollution(datetime(2026, 1, 1, 23, 30, tzinfo=UTC), pm2_5=15),
        ],
        [],
        grouping="daily",
        aggregation="average",
        timezone="Europe/Sarajevo",
    )

    assert [point.local_date for point in points] == ["2026-01-01", "2026-01-02"]
    assert [point.pm2_5 for point in points] == [5, 15]


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        (datetime(2026, 3, 29, 12, tzinfo=UTC), 23),
        (datetime(2026, 10, 25, 12, tzinfo=UTC), 25),
    ],
)
def test_expected_daily_sample_count_handles_sarajevo_dst(stamp: datetime, expected: int) -> None:
    points = aggregate_history(
        [pollution(stamp, pm2_5=10)],
        [],
        grouping="daily",
        aggregation="average",
        timezone="Europe/Sarajevo",
    )

    assert points[0].expected_samples == expected
