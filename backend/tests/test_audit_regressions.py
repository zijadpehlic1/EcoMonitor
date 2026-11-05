import asyncio
from datetime import UTC, datetime, timedelta
from math import nan, inf
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from app.models import Location, SensorMeasurement, SensorStation, SensorImportState, SensorMeasurementMetadata, AirQualityReading
from app.core.config import Settings
from app.services import sensor_history, sensor_measurements
from app.services.datasets import pollution_rows, pm25_rows
from app.services.ml_forecast import _is_continuous_hourly, horizon_scores, generate_pm25_forecast
from app.services.weather_ml import _insufficient, _weather_values
from app.services.history import aggregate_history
from app.services.weather import LIVE_WEATHER_SOURCE, HISTORICAL_WEATHER_SOURCE
from app.services.fhmz_history import parse_fhmz_hour
from zoneinfo import ZoneInfo
from test_sensor_measurements import make_context
from test_history import pollution, weather

NOW = datetime(2026, 11, 5, 18, tzinfo=UTC)


def batch(stamp=NOW, measurements=None):
    return sensor_measurements.ProviderBatch("Test", "1", "Station", "https://example.test", "Test", True,
        None, None, measurements or [(stamp, 'pm2_5', 12.0, 'μg/m³')])


def test_station_cannot_move_between_cities_and_old_import_preserves_latest():
    db, city = make_context()
    sensor_measurements._persist_batch(db, city, batch())
    db.commit()
    sensor_measurements._persist_batch(db, city, batch(NOW - timedelta(days=30)))
    db.commit()
    station = db.scalar(select(SensorStation))
    assert station.last_measurement_at.replace(tzinfo=UTC) == NOW
    other = Location(slug='other', name='Other', country='BA', country_code='BA', latitude=0, longitude=0)
    db.add(other); db.commit()
    with pytest.raises(ValueError, match='another city'):
        sensor_measurements._persist_batch(db, other, batch())
    assert station.location_id == city.id


def test_payload_duplicates_are_idempotent_and_unchanged_values_preserve_ingestion():
    db, city = make_context()
    row = (NOW, 'pm2_5', 12.0, 'μg/m³')
    sensor_measurements._persist_batch(db, city, batch(measurements=[row, row]))
    db.commit()
    reading = db.scalar(select(SensorMeasurement))
    first_ingested = reading.ingested_at
    sensor_measurements._persist_batch(db, city, batch())
    db.commit()
    assert db.scalar(select(func.count(SensorMeasurement.id))) == 1
    assert reading.ingested_at == first_ingested


@pytest.mark.parametrize('value', [nan, inf, -1.0])
def test_invalid_physical_values_rejected(value):
    db, city = make_context()
    with pytest.raises(ValueError):
        sensor_measurements._persist_batch(db, city, batch(measurements=[(NOW, 'pm2_5', value, 'μg/m³')]))


def test_future_not_live_and_naive_provider_time_rejected(monkeypatch):
    monkeypatch.setattr(sensor_measurements, 'utc_now', lambda: NOW)
    assert not sensor_measurements._is_fresh(NOW + timedelta(hours=1), Settings())
    assert sensor_measurements._is_fresh(NOW, Settings())
    with pytest.raises(ValueError):
        sensor_measurements._parse_iso('2026-11-05T18:00:00')


def test_continuity_rejects_cancelling_duplicate_and_gap():
    stamps = [NOW, NOW, NOW + timedelta(hours=2), NOW + timedelta(hours=3)]
    assert not _is_continuous_hourly(stamps, 0, 3)
    assert _is_continuous_hourly([NOW + timedelta(hours=h) for h in range(25)], 0, 24)


def test_empty_hour_and_day_are_explicit_nulls():
    points = aggregate_history([pollution(NOW, pm2_5=10), pollution(NOW + timedelta(hours=2), pm2_5=20)], [],
        grouping='hourly', aggregation='average', timezone='Europe/Sarajevo')
    assert [p.pm2_5 for p in points] == [10, None, 20]
    assert points[1].sample_counts['pm2_5'] == 0


def test_daily_max_is_maximum_of_hourly_means_not_subhour_spike():
    points = aggregate_history([pollution(NOW, pm2_5=0), pollution(NOW + timedelta(minutes=30), pm2_5=100),
        pollution(NOW + timedelta(hours=1), pm2_5=60)], [], grouping='daily', aggregation='maximum', timezone='Europe/Sarajevo')
    assert points[0].pm2_5 == 60
    assert points[0].sample_counts['pm2_5'] == 2


def test_weather_missing_operational_value_uses_valid_historical_value():
    old = weather(NOW, 3); old.source_name = HISTORICAL_WEATHER_SOURCE
    points = aggregate_history([], [old, weather(NOW, None)], grouping='hourly', aggregation='average', timezone='Europe/Sarajevo')
    assert points[0].temperature_2m == 3


def test_dataset_isolation_and_quality_exclusion():
    db, city = make_context()
    sensor_measurements._persist_batch(db, city, batch())
    db.commit()
    station = db.scalar(select(SensorStation))
    db.add(AirQualityReading(location_id=city.id, measured_at=NOW, pm2_5=999,
        source_name='Other', source_type='modeled', source_url='https://example.test', ingested_at=NOW))
    db.commit()
    assert not pollution_rows(db, city, 'modeled')
    assert pm25_rows(db, city, 'sensor', station.id)[0].pm2_5 == 12
    result = generate_pm25_forecast(db, city, 24, 'sensor', station.id)
    assert result.source_type == 'sensor' and result.trained_samples == 1
    assert result.station_id == station.id and result.location == city.slug
    db.scalar(select(SensorMeasurement)).validation_status = 'provider_flagged'; db.commit()
    assert not pm25_rows(db, city, 'sensor', station.id)
    with pytest.raises(ValueError):
        pollution_rows(db, city, 'sensor', 999)


def hour(stamp, value=12, coverage=100, flagged=False):
    return {'value': value, 'parameter': {'name': 'pm25', 'units': 'µg/m³'},
        'period': {'datetimeFrom': {'utc': (stamp-timedelta(hours=1)).isoformat()}, 'datetimeTo': {'utc': stamp.isoformat()}},
        'coverage': {'percentCoverage': coverage}, 'flagInfo': {'hasFlags': flagged}}


def test_hour_parser_preserves_quality_and_interval():
    parsed = sensor_history.parse_hour(hour(NOW, coverage=50), {'name': 'pm25'}, NOW-timedelta(days=1), NOW)
    assert parsed[0][0] == NOW and parsed[1] == 'incomplete_hour'
    assert parsed[2]['timestamp_semantics'] == 'interval_end'
    assert sensor_history.parse_hour(hour(NOW, flagged=True), {'name': 'pm25'}, NOW-timedelta(days=1), NOW)[1] == 'provider_flagged'
    assert sensor_history.parse_hour(hour(NOW, value=-1), {'name': 'pm25'}, NOW-timedelta(days=1), NOW) is None


def test_paged_import_cache_metadata_and_rollback(monkeypatch):
    db, city = make_context('sarajevo')
    monkeypatch.setattr(sensor_history, 'utc_now', lambda: NOW)
    monkeypatch.setattr(sensor_history, 'PAGE_SIZE', 2)
    calls = []
    metadata = {'id': 9598, 'name': 'Sarajevo', 'isMonitor': True, 'isMobile': False, 'country': {'code': 'BA'},
        'coordinates': {'latitude': city.latitude, 'longitude': city.longitude}, 'provider': {'name': 'AirNow'},
        'licenses': [{'name': 'US Public Domain'}], 'sensors': [{'id': 10, 'parameter': {'name': 'pm25'}}]}
    async def fetch(url, **kwargs):
        calls.append(url)
        if '/locations/' in url:
            return {'results': [metadata]}
        return {'results': [hour(NOW-timedelta(hours=2)), hour(NOW-timedelta(hours=1))]
            if kwargs['params']['page'] == 1 else [hour(NOW)]}
    monkeypatch.setattr(sensor_history, '_get_json', fetch)
    settings = Settings(openaq_api_key=SecretStr('test'))
    result = asyncio.run(sensor_history.synchronize_sensor_history(db, city, settings=settings))
    assert result['stations'][0]['inserted'] == 3
    assert result['stations'][0]['provider_requests'] == 3
    assert db.scalar(select(func.count(SensorMeasurementMetadata.measurement_id))) == 3
    assert len(calls) == 3
    result = asyncio.run(sensor_history.synchronize_sensor_history(db, city, settings=settings))
    assert result['stations'][0]['status'] == 'cached' and len(calls) == 3
    result = asyncio.run(sensor_history.synchronize_sensor_history(db, city, settings=settings, force=True))
    assert result['stations'][0]['inserted'] == 0
    assert db.scalar(select(func.count(SensorMeasurement.id))) == 3


def test_horizon_metrics_and_insufficient_test_count():
    scores = horizon_scores([0.] * 48, model=list(range(24)) * 2)
    assert scores[1]['model_mae'] == 0
    assert scores[24]['model_rmse'] == 23
    assert _insufficient('missing', samples=100).test_samples == 0


@pytest.mark.parametrize('stamp', ['2026-10-25T02:00:00', '2026-03-29T02:00:00'])
def test_fhmz_skips_ambiguous_and_nonexistent_local_hours(stamp):
    assert parse_fhmz_hour([stamp, 12, 'Valid', None], 'pm2_5', ZoneInfo('Europe/Sarajevo'),
        datetime(2026, 1, 1, tzinfo=UTC), NOW) is None


def test_fhmz_source_valid_is_not_final_validation():
    row = parse_fhmz_hour(['2026-11-05T19:00:00', 12, 'Valid', None], 'pm2_5',
        ZoneInfo('Europe/Sarajevo'), NOW-timedelta(days=1), NOW)
    assert row[0][0] == NOW and row[1] == 'unvalidated'
    assert row[2]['provider_quality'] == 'Valid'


def test_interval_end_midnight_belongs_to_previous_calendar_day():
    points = aggregate_history([pollution(datetime(2026, 1, 1, 23, tzinfo=UTC), pm2_5=42)], [],
        grouping='daily', aggregation='maximum', timezone='Europe/Sarajevo', interval_end=True)
    assert points[0].local_date == '2026-01-01'
    assert points[0].peak_timestamps['pm2_5'] == datetime(2026, 1, 1, 23, tzinfo=UTC)


def test_failed_openaq_import_rolls_back_without_advancing_checkpoint(monkeypatch):
    db, city = make_context('sarajevo')
    monkeypatch.setattr(sensor_history, 'utc_now', lambda: NOW)
    metadata = {'id': 9598, 'name': 'Sarajevo', 'isMonitor': True, 'country': {'code': 'BA'},
        'coordinates': {'latitude': city.latitude, 'longitude': city.longitude}, 'provider': {'name': 'AirNow'},
        'licenses': [{'name': 'US Public Domain'}],
        'sensors': [{'id': 10, 'parameter': {'name': 'pm25'}}, {'id': 11, 'parameter': {'name': 'pm10'}}]}
    async def fetch(url, **kwargs):
        if '/locations/' in url:
            return {'results': [metadata]}
        if '/sensors/11/' in url:
            raise RuntimeError('Unavailable')
        return {'results': [hour(NOW)]}
    monkeypatch.setattr(sensor_history, '_get_json', fetch)
    result = asyncio.run(sensor_history.synchronize_sensor_history(db, city,
        settings=Settings(openaq_api_key=SecretStr('test'))))
    assert result['status'] == 'failed'
    assert db.scalar(select(func.count(SensorMeasurement.id))) == 0
    assert db.scalar(select(func.count(SensorImportState.station_id))) == 0


def test_fhmz_import_persists_flagged_rows_but_excludes_them_from_analysis(monkeypatch):
    from app.services import fhmz_history
    db, city = make_context()
    monkeypatch.setattr(fhmz_history, 'utc_now', lambda: NOW)
    monkeypatch.setattr(fhmz_history, 'FIELDS', {379: 'pm2_5'})
    requested_ranges = []
    async def fetch(url, **kwargs):
        if '/detail/' in url:
            return {'id': 6, 'name': 'Zenica Brist', 'mobile': False,
                'latitude': city.latitude, 'longitude': city.longitude}
        assert kwargs['params']['aqdata_type'] == 0
        requested_ranges.append(kwargs['params'])
        return [['2026-11-05T18:00:00', 10, 'Valid', None],
                ['2026-11-05T19:00:00', 900, 'Invalid', 7]]
    monkeypatch.setattr(fhmz_history, '_get_json', fetch)
    result = asyncio.run(fhmz_history.synchronize_fhmz_history(db, city, settings=Settings()))
    assert result['inserted'] == 2
    station = db.scalar(select(SensorStation))
    assert [r.pm2_5 for r in pm25_rows(db, city, 'sensor', station.id)] == [10]
    assert db.scalar(select(func.count(SensorMeasurementMetadata.measurement_id))) == 2
    assert asyncio.run(fhmz_history.synchronize_fhmz_history(db, city, settings=Settings()))['status'] == 'cached'
    result = asyncio.run(fhmz_history.synchronize_fhmz_history(db, city, settings=Settings(),
        end=NOW-timedelta(hours=1)))
    assert result['status'] == 'success' and result['provider_requests'] == 2
    assert len(requested_ranges) == 2
    assert requested_ranges[-1]['begin_date'] == (NOW-timedelta(days=92, hours=1)).strftime('%d.%m.%Y.')
