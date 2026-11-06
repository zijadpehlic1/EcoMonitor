from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.station_aqi import classify, freshness
from app.services.sensor_measurements import ProviderBatch, _persist_batch, build_sensor_current
from tests.test_weather import make_context


def row(pollutant, value, unit='μg/m³', validation_status='unvalidated'):
    return SimpleNamespace(pollutant=pollutant, value=value, unit=unit, validation_status=validation_status)


def test_official_hourly_limits_and_worst_pollutant():
    base = [row('pm2_5', 5), row('pm10', 15), row('nitrogen_dioxide', 10), row('ozone', 60), row('sulphur_dioxide', 20)]
    assert classify(base, 'Pozadinska').level == 1
    assert classify(base[:-1]+[row('sulphur_dioxide', 21)], 'Pozadinska').level == 2
    assert classify(base[:-1]+[row('sulphur_dioxide', 276)], 'Pozadinska').level == 6
    assert classify(base[:-1]+[row('sulphur_dioxide', 276)], 'Pozadinska').limiting_pollutant == 'sulphur_dioxide'
    assert classify(base[:-1]+[row('sulphur_dioxide', 999, unit='mg/m³')], 'Pozadinska').level == 1


def test_station_type_and_incomplete_data_rules():
    minimal = [row('pm2_5', 20), row('nitrogen_dioxide', 12)]
    assert classify(minimal, 'Saobraćajna').level == 3
    assert classify(minimal, 'Pozadinska').level is None
    assert classify(minimal, None).level is None
    assert classify(minimal+[row('ozone', 70)], None).complete
    severe = classify([row('pm2_5', 95)], 'Pozadinska')
    assert severe.level == 5 and not severe.complete
    assert classify([row('pm2_5', 15, validation_status='provider_flagged')], 'Saobraćajna').level is None


def test_latest_single_hour_historical_fallback_and_no_future(monkeypatch):
    from app.services import sensor_measurements as sm
    now = datetime(2026, 11, 6, 12, 30, tzinfo=UTC)
    monkeypatch.setattr(sm, 'utc_now', lambda: now)
    db, city = make_context()
    old = now-timedelta(hours=5)
    current = now-timedelta(minutes=30)
    future = now+timedelta(hours=1)
    _persist_batch(db, city, ProviderBatch('FHMZ','6','Brist','https://example.org','FHMZ',True,44,17,
        [(old,'pm2_5',95.,'μg/m³'),(old,'nitrogen_dioxide',2.,'μg/m³'),
         (current,'pm2_5',30.,'μg/m³'),(current,'nitrogen_dioxide',12.,'μg/m³'),
         (current,'ozone',75.,'μg/m³'),(future,'pm2_5',200.,'μg/m³')]))
    db.commit()
    station_id = build_sensor_current(db, city).station_id
    result = build_sensor_current(db, city, station_id=station_id)
    assert result.latest_measurement_at == current
    assert result.aqi_category == 3 and result.aqi_complete
    assert result.aqi_freshness == 'current'
    assert all(m.measured_at == current for m in result.measurements)
    assert result.health_general and result.health_sensitive
    # Invalidate this hour: the last valid historical snapshot is returned,
    # with its exact time and no current health reassurance.
    for m in db.query(sm.SensorMeasurement).filter(sm.SensorMeasurement.measured_at == current):
        m.validation_status = 'provider_flagged'
        if m.pollutant == 'nitrogen_dioxide':
            m.validation_status = 'unvalidated'  # latest hour is incomplete and low
    db.commit()
    fallback = build_sensor_current(db, city, station_id=station_id)
    assert fallback.latest_measurement_at == old
    assert fallback.aqi_category == 5 and fallback.aqi_freshness == 'stale'
    assert fallback.health_general is None
    db.close()


def test_yesterday_is_stale_even_when_less_than_three_hours_old():
    now = datetime(2026, 11, 6, 0, 30, tzinfo=UTC)
    from zoneinfo import ZoneInfo
    local_now = now.astimezone(ZoneInfo('Europe/Sarajevo'))
    old = datetime(2026, 11, 5, 22, 0, tzinfo=UTC)
    assert freshness(old, now, local_now) == ('stale', 150)
