import asyncio
import json
from datetime import timedelta
from unittest.mock import Mock
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models import BackgroundJob, DataCoverage, ModelArtifact, ModelResult, AirQualityReading
from app.services import jobs, incremental, model_store
from app.services.air_quality import utc_now, SOURCE_NAME
from app.schemas import MLForecastResponse
from tests.test_weather import make_context


def test_city_order_stages_single_flight_and_resume():
    db, city = make_context()
    jobs.seed_sync(db)
    expected = ['zenica', 'sarajevo', 'mostar', 'banja-luka']
    seen = []
    for city_name in expected:
        for days in jobs.STAGES:
            job = jobs.claim(db, 'sync', 'worker')
            assert json.loads(job.arguments) == {'city': city_name, 'days': days}
            # Existing queued/running identity is never reset by duplicate startup.
            jobs.seed_sync(db)
            assert db.get(BackgroundJob, job.key).status == 'running'
            jobs.finish(db, job.key, 'worker', {'days_checked': days})
            seen.append((city_name, days))
    assert len(seen) == 16
    assert jobs.claim(db, 'sync', 'worker') is None
    db.close()
    with Session(db.bind) as restarted:
        jobs.seed_sync(restarted)
        assert jobs.claim(restarted, 'sync', 'other') is None


def test_claim_lease_and_failed_job_backoff(monkeypatch):
    db, _ = make_context()
    now = utc_now()
    monkeypatch.setattr(jobs, 'utc_now', lambda: now)
    assert jobs.enqueue(db, 'one', 'ml', {})
    assert not jobs.enqueue(db, 'one', 'ml', {})
    assert jobs.claim(db, 'ml', 'a').key == 'one'
    assert jobs.claim(db, 'ml', 'b') is None
    now += timedelta(seconds=91)
    assert jobs.claim(db, 'ml', 'b').key == 'one'
    jobs.finish(db, 'one', 'a', {})  # expired owner's completion is ignored
    assert db.get(BackgroundJob, 'one').owner == 'b'
    jobs.finish(db, 'one', 'b', {'error': 'Timeout'}, failed=True)
    assert jobs.claim(db, 'ml', 'b') is None


def test_incremental_extensions_and_restart_do_not_redownload():
    db, city = make_context()
    today = utc_now().date() - timedelta(days=10)
    previous = set()
    for days in jobs.STAGES:
        ranges = incremental.missing_ranges(db, city, SOURCE_NAME, today-timedelta(days=days), today)
        requested = {d for first,last in ranges for d in incremental.days_between(first,last)}
        assert not requested & previous
        for first,last in ranges:
            incremental.mark(db, city, SOURCE_NAME, first,last)
        previous |= requested
        assert len(previous) == days+1
    city_id = city.id
    db.close()
    with Session(db.bind) as restarted:
        from app.models import Location
        assert incremental.missing_ranges(restarted, restarted.get(Location, city_id), SOURCE_NAME, today-timedelta(days=90), today) == []


def test_missing_gap_and_provider_unavailable_are_distinct(monkeypatch):
    db, city = make_context()
    day = utc_now().date()-timedelta(days=20)
    incremental.mark(db, city, SOURCE_NAME, day,day)
    incremental.mark(db, city, SOURCE_NAME, day+timedelta(days=2),day+timedelta(days=2))
    assert incremental.missing_ranges(db,city,SOURCE_NAME,day,day+timedelta(days=2)) == [(day+timedelta(days=1),day+timedelta(days=1))]
    incremental.mark(db,city,SOURCE_NAME,day+timedelta(days=1),day+timedelta(days=1), 'unavailable', utc_now()+timedelta(days=7))
    assert not incremental.missing_ranges(db,city,SOURCE_NAME,day,day+timedelta(days=2))
    # Another provider is never considered covered by these records.
    assert incremental.missing_ranges(db,city,'other',day,day)


def test_live_overlap_respects_ttl(monkeypatch):
    db, city = make_context()
    now = utc_now()
    monkeypatch.setattr(incremental.aq,'utc_now',lambda:now)
    day = now.date()
    incremental.mark(db,city,SOURCE_NAME,day,day)
    assert not incremental.missing_ranges(db,city,SOURCE_NAME,day,day,recent_hours=48)
    now += timedelta(minutes=31)
    assert incremental.missing_ranges(db,city,SOURCE_NAME,day,day,recent_hours=48) == [(day,day)]


def test_incremental_payload_persistence_and_empty_data_backoff(monkeypatch):
    from app.core.config import Settings
    db, city = make_context()
    day = utc_now().date()-timedelta(days=20)
    calls = []
    async def fetch(url, params, settings):
        calls.append(params)
        stamp = __import__('datetime').datetime.combine(day, __import__('datetime').time(), __import__('datetime').UTC)
        return {'hourly': {'time': [int(stamp.timestamp())], 'pm2_5': [12.]}}
    monkeypatch.setattr(incremental.wx, '_fetch_json',fetch)
    first = asyncio.run(incremental.sync_dataset(db,city,SOURCE_NAME,day,day,Settings()))
    second = asyncio.run(incremental.sync_dataset(db,city,SOURCE_NAME,day,day,Settings()))
    assert first['inserted']==1 and second['requests']==0 and len(calls)==1
    assert calls[0]['start_date']==day.isoformat() and 'past_days' not in calls[0]
    assert db.scalar(select(func.count(AirQualityReading.id))) == 1
    assert db.scalar(select(DataCoverage)).status == 'provider_partial'


def test_json_forest_matches_sklearn_and_reuses_after_restart(monkeypatch):
    db, city = make_context()
    model = RandomForestRegressor(n_estimators=5,random_state=42).fit([[0.],[1.],[2.],[3.]],[0.,2.,1.,5.])
    data = [[str(i),i] for i in range(30)]
    response = MLForecastResponse(status='ready',message='test',generated_at=utc_now())
    key = model_store.artifact_key(city,'sensor',7,'base')
    model_store.save(db,key,data,model,response)
    db.close()
    with Session(db.bind) as restored:
        forest, result = model_store.reusable(restored,key,data,MLForecastResponse)
        np.testing.assert_allclose(forest.predict([[.5],[1.1],[2.9]]),model.predict([[.5],[1.1],[2.9]]),rtol=0,atol=1e-12)
        assert result.status=='ready'
        assert model_store.reusable(restored,key,data+[['new',31]],MLForecastResponse)
        assert model_store.reusable(restored,key,[[str(0),999]]+data[1:],MLForecastResponse) is None
        assert model_store.reusable(restored,key[:-1]+'x',data,MLForecastResponse) is None


def test_retraining_schedule_and_artifact_integrity(monkeypatch):
    db, city = make_context()
    model = RandomForestRegressor(n_estimators=2,random_state=42).fit([[0],[1]],[0,1])
    data = [[i,i] for i in range(30)]
    model_store.save(db,'key',data,model,MLForecastResponse(status='ready',message='test',generated_at=utc_now()))
    artifact=db.get(ModelArtifact,'key')
    artifact.trained_at=utc_now()-timedelta(days=2);db.commit()
    assert model_store.reusable(db,'key',data+[[i,i] for i in range(30,55)],MLForecastResponse) is None
    artifact.forest_json='[]';db.commit()
    assert model_store.reusable(db,'key',data,MLForecastResponse) is None


def test_ml_get_only_enqueues_and_retains_cached_result(monkeypatch):
    db, city = make_context()
    response=jobs.cached_model_response(db,city,24,'modeled',None,'base')
    assert response.status=='pending'
    key=jobs.model_key(city.slug,'modeled',None,'base',24)
    db.add(ModelResult(key=key,input_version='v',response_json=response.model_dump_json(),computed_at=utc_now()));db.commit()
    response=jobs.cached_model_response(db,city,24,'modeled',None,'base')
    assert response.location==city.slug
    assert db.scalar(select(func.count(BackgroundJob.key)))==1


def test_manual_refresh_deduplicates_and_does_no_provider_io(monkeypatch):
    from app.api.routes import refresh
    import httpx
    get = Mock(side_effect=AssertionError('No HTTP in refresh route'))
    monkeypatch.setattr(httpx.AsyncClient,'get',get)
    db, city=make_context()
    assert asyncio.run(refresh(city.slug,True,db)).status=='queued'
    assert asyncio.run(refresh(city.slug,True,db)).status=='cached'
    assert not get.called
    assert db.scalar(select(func.count(BackgroundJob.key)))==1


def test_worker_skips_unchanged_input_and_regenerates_after_revision(monkeypatch):
    from app import worker
    from app.services import ml_forecast
    from sqlalchemy.orm import sessionmaker
    db,city=make_context()
    monkeypatch.setattr(worker,'SessionLocal',sessionmaker(bind=db.bind,expire_on_commit=False))
    generator=Mock(return_value=MLForecastResponse(status='insufficient_data',message='fixture',generated_at=utc_now()))
    monkeypatch.setattr(ml_forecast,'generate_pm25_forecast',generator)
    args=dict(city=city.slug,source='modeled',station_id=None,model='base',horizon=24)
    assert worker.calculate(args)['forecast_recomputed'] is True
    assert worker.calculate(args)['forecast_recomputed'] is False
    assert generator.call_count==1
    db.add(AirQualityReading(location_id=city.id,measured_at=utc_now()-timedelta(hours=1),pm2_5=12,
        source_name=SOURCE_NAME,source_type='modeled',source_url='https://open-meteo.com',ingested_at=utc_now()))
    db.commit()
    assert worker.calculate(args)['forecast_recomputed'] is True
    row=db.scalar(select(AirQualityReading));row.pm2_5=15;db.commit()
    assert worker.calculate(args)['forecast_recomputed'] is True
    assert generator.call_count==3


def test_station_catalog_counts_and_quality_are_station_specific():
    from app.api.routes import sensor_stations
    from app.services.sensor_measurements import ProviderBatch,_persist_batch
    db,city=make_context()
    _persist_batch(db,city,ProviderBatch('FHMZ','6','Brist','https://example.org','FHMZ',True,44,17,
        [(utc_now()-timedelta(hours=1),'pm2_5',12.,'μg/m³')]))
    _persist_batch(db,city,ProviderBatch('Other','7','Other station','https://example.org','Other',True,44,17,
        [(utc_now()-timedelta(hours=2),'pm2_5',22.,'μg/m³'),(utc_now()-timedelta(hours=1),'pm2_5',23.,'μg/m³')]))
    db.commit()
    result=sensor_stations(city.slug,db)
    assert {r['name']:r['measurement_count'] for r in result}=={'Brist':1,'Other station':2}
    assert all(r['location']==city.slug and r['validation_counts']['unvalidated']==r['measurement_count'] for r in result)
    from app.services.sensor_measurements import build_sensor_current
    stations = {r['name']:r['id'] for r in result}
    selected = build_sensor_current(db,city,station_id=stations['Brist'])
    assert selected.station_id == stations['Brist'] and selected.station_name == 'Brist'
    assert selected.measurements[0].value == 12.
    other = build_sensor_current(db,city,station_id=stations['Other station'])
    assert other.station_id == stations['Other station'] and other.measurements[0].value == 23.


def test_reused_evaluation_forecast_status_tracks_current_inputs():
    from types import SimpleNamespace
    from app.schemas import WeatherModelComparisonResponse
    now = utc_now().replace(minute=0, second=0, microsecond=0)
    stamps = [now-timedelta(hours=23-i) for i in range(24)]
    model = Mock()
    model.predict.return_value = np.array([10.])
    base = MLForecastResponse(status='comparison_ready_forecast_unavailable', message='test', generated_at=now)
    result = model_store.base_prediction(model,base,[10.]*24,stamps,24)
    assert result.status == 'ready' and len(result.forecast) == 24
    old = [t-timedelta(days=1) for t in stamps]
    assert model_store.base_prediction(model,result,[10.]*24,old,24).status == 'comparison_ready_forecast_unavailable'
    weather = WeatherModelComparisonResponse(status='comparison_ready_forecast_unavailable',message='test',generated_at=now)
    rows = [SimpleNamespace(measured_at=now+timedelta(hours=i), ingested_at=now,
        temperature_2m=10., wind_speed_10m=2., relative_humidity_2m=50., precipitation=0.) for i in range(1,25)]
    result = model_store.weather_prediction(model,weather,[10.]*24,stamps,rows,24)
    assert result.status == 'ready' and len(result.forecast) == 24
    assert model_store.weather_prediction(model,result,[10.]*24,stamps,[],24).status == 'comparison_ready_forecast_unavailable'
