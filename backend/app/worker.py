"""One elected sync worker and one elected ML worker, isolated from API CPU/GIL."""
import asyncio
import json
import os
import signal
import sys
from time import perf_counter
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, update
from app.core.database import SessionLocal
from app.models import BackgroundJob, Location, SensorStation, ModelResult, WeatherReading
from app.services.air_quality import utc_now, aware_utc
from app.services.jobs import enqueue, claim, renew, finish, seed_sync, model_key, CITIES


def calculate(args):
    started = perf_counter()
    # sklearn imports, training and inference stay in this separate process.
    from app.services import ml_forecast, weather_ml, model_store
    from app.services.datasets import pm25_rows
    from app.services.weather import ARCHIVED_WEATHER_SOURCE, LIVE_WEATHER_SOURCE
    from app.core.config import get_settings
    with SessionLocal() as db:
        city = db.scalar(select(Location).where(Location.slug == args['city']))
        rows = pm25_rows(db, city, args['source'], args['station_id'])
        stamps = [aware_utc(r.measured_at) for r in rows]
        data = [(t.isoformat(), r.pm2_5) for t, r in zip(stamps, rows)]
        weather = []
        if args['model'] == 'weather':
            weather_rows = db.scalars(select(WeatherReading).where(WeatherReading.location_id == city.id,
                WeatherReading.source_name.in_([ARCHIVED_WEATHER_SOURCE, LIVE_WEATHER_SOURCE]))
                .order_by(WeatherReading.source_name, WeatherReading.measured_at)).all()
            weather = [(r.source_name, aware_utc(r.measured_at).isoformat(), weather_ml._weather_values(r),
                utc_now()-aware_utc(r.ingested_at) <= timedelta(hours=3) if r.source_name == LIVE_WEATHER_SOURCE else None)
                for r in weather_rows if r.source_name == ARCHIVED_WEATHER_SOURCE or (stamps and stamps[-1] < aware_utc(r.measured_at) <= stamps[-1]+timedelta(hours=args['horizon']))]
        version = model_store.digest([model_store.VERSION, data, weather,
            bool(stamps and utc_now()-stamps[-1] <= timedelta(hours=3)),
            int(utc_now().timestamp() // (max(1, get_settings().ml_retrain_hours)*3600))])
        key = model_key(city.slug, args['source'], args['station_id'], args['model'], args['horizon'])
        prior = db.get(ModelResult, key)
        if prior and prior.input_version == version and not args.get('retrain'):
            return {'status': 'cached', 'trained': False, 'forecast_recomputed': False}
        module = ml_forecast if args['model'] == 'base' else weather_ml
        module._cache.clear()  # Persistence/version policy is authoritative, not process lifetime.
        generator = module.generate_pm25_forecast if args['model'] == 'base' else module.generate_weather_model_comparison
        from app.models import ModelArtifact
        artifact_key = model_store.artifact_key(city, args['source'], args['station_id'], args['model'])
        before = db.get(ModelArtifact, artifact_key)
        before_time = before.trained_at if before else None
        if before and args.get('retrain'):
            before.version = 'explicit-retrain-requested'
            db.commit()
        response = generator(db, city, args['horizon'], args['source'], args['station_id'])
        db.merge(ModelResult(key=key, input_version=version, response_json=response.model_dump_json(), computed_at=utc_now()))
        db.commit()
        after = db.get(ModelArtifact, artifact_key)
        trained = bool(after and after.trained_at != before_time)
        from app.models import ModelExecution
        db.add(ModelExecution(id=str(uuid4()), model_key=key, completed_at=utc_now(),
            elapsed_ms=(perf_counter()-started)*1000, trained=trained, evaluated=trained, forecast_recomputed=True))
        db.commit()
        return {'status': response.status, 'trained': trained, 'forecast_recomputed': True}


def queue_models(db, city):
    stations = db.scalars(select(SensorStation).where(SensorStation.location_id == city.id)).all()
    for source, station_id in [('modeled', None), *[('sensor', s.id) for s in stations]]:
        for model in ('base', 'weather'):
            enqueue(db, model_key(city.slug, source, station_id, model, 24), 'ml',
                dict(city=city.slug, source=source, station_id=station_id, model=model, horizon=24),
                priority=100+CITIES.index(city.slug)*10, cooldown=300)


async def run(kind):
    owner = str(uuid4())
    stop = asyncio.Event()
    async def shutdown_input():
        await asyncio.to_thread(sys.stdin.readline)
        stop.set()
    if os.environ.get('ECOMONITOR_MANAGED_WORKER') == '1':
        asyncio.create_task(shutdown_input())
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: stop.set())
        except ValueError:
            pass
    leader_key = f'leader:{kind}'
    active_key = None

    async def heartbeat():
        while not stop.is_set():
            with SessionLocal() as db:
                if not renew(db, leader_key, owner):
                    stop.set(); return
                if active_key:
                    renew(db, active_key, owner)
            try:
                await asyncio.wait_for(stop.wait(), timeout=15)
            except TimeoutError:
                pass

    # A database lease prevents duplicated worker/reloader startup execution.
    with SessionLocal() as db:
        enqueue(db, leader_key, f'leader-{kind}', {}, -100)
    while not stop.is_set():
        with SessionLocal() as db:
            leader = claim(db, f'leader-{kind}', owner)
        if leader:
            break
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass
    if stop.is_set():
        return
    pulse = asyncio.create_task(heartbeat())
    try:
        while not stop.is_set():
            with SessionLocal() as db:
                if kind == 'sync':
                    seed_sync(db)
                job = claim(db, kind, owner)
                if job:
                    key, args = job.key, json.loads(job.arguments)
                else:
                    key = None
            if not key:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except TimeoutError:
                    pass
                continue
            active_key = key
            try:
                if kind == 'ml':
                    result = await asyncio.to_thread(calculate, args)
                else:
                    from app.services.incremental import sync_city_stage, sync_physical
                    # Sync has its own process; synchronous SQL never blocks the API.
                    with SessionLocal() as db:
                        city = db.scalar(select(Location).where(Location.slug == args['city']))
                        if args.get('physical_only'):
                            from app.core.config import get_settings
                            result = await sync_physical(db, city, args['days'], get_settings())
                        else:
                            result = await sync_city_stage(db, city, args['days'])
                        queue_models(db, city)
                with SessionLocal() as db:
                    finish(db, key, owner, result)
            except Exception as exc:
                with SessionLocal() as db:
                    finish(db, key, owner, {'error': type(exc).__name__}, failed=True)
            finally:
                active_key = None
    finally:
        pulse.cancel()
        with SessionLocal() as db:
            db.execute(update(BackgroundJob).where(BackgroundJob.owner == owner, BackgroundJob.status == 'running')
                .values(status='queued', lease_until=None, available_at=utc_now()))
            db.commit()


if __name__ == '__main__':
    if sys.argv[1] == 'ml':
        # On Windows/Python 3.14 initialize NumPy's native runtime on the main
        # thread, before any executor threads. Importing it lazily in to_thread
        # can hang in DLL initialization. This is still outside the API process.
        os.environ['OPENBLAS_NUM_THREADS'] = '1'
        os.environ['OMP_NUM_THREADS'] = '1'
        os.environ['MKL_NUM_THREADS'] = '1'
        from app.services import ml_forecast, weather_ml, model_store
    asyncio.run(run(sys.argv[1]))
