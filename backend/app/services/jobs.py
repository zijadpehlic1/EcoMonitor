"""Database-backed deduplicated work. API handlers enqueue; worker processes execute."""
import json
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, update, or_
from sqlalchemy.exc import IntegrityError
from app.models import BackgroundJob, ModelResult
from app.services.air_quality import utc_now, aware_utc, SUPPORTED_LOCATIONS

STAGES = (1, 7, 30, 90)
CITIES = tuple(SUPPORTED_LOCATIONS)


def enqueue(db, key, kind, arguments, priority=100, cooldown=0):
    now = utc_now()
    job = db.get(BackgroundJob, key)
    if job:
        if job.status in ('queued', 'running'):
            if priority < job.priority:
                db.execute(update(BackgroundJob).where(BackgroundJob.key == key).values(priority=priority))
                db.commit()
            return False
        if job.available_at and aware_utc(job.available_at) > now:
            return False
        if job.completed_at and now - aware_utc(job.completed_at) < timedelta(seconds=cooldown):
            return False
        changed = db.execute(update(BackgroundJob).where(BackgroundJob.key == key,
            BackgroundJob.status == job.status).values(status='queued', arguments=json.dumps(arguments),
            priority=priority, available_at=now, attempts=0)).rowcount
        db.commit()
        return bool(changed)
    try:
        db.add(BackgroundJob(key=key, kind=kind, arguments=json.dumps(arguments), priority=priority,
            available_at=now, status='queued', attempts=0))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def seed_sync(db):
    for index, city in enumerate(CITIES):
        job = db.get(BackgroundJob, f'sync:{city}')
        enqueue(db, f'sync:{city}', 'sync', {'city': city, 'days': 90 if job and job.completed_at else 1}, index * 10)


def claim(db, kind, owner):
    now = utc_now()
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.kind == kind,
        BackgroundJob.available_at <= now,
        or_(BackgroundJob.status == 'queued',
            (BackgroundJob.status == 'running') & (BackgroundJob.lease_until < now)))
        .order_by(BackgroundJob.priority, BackgroundJob.key).limit(1))
    if not job:
        return None
    changed = db.execute(update(BackgroundJob).execution_options(synchronize_session=False).where(BackgroundJob.key == job.key,
        or_(BackgroundJob.status == 'queued', BackgroundJob.lease_until < now))
        .values(status='running', owner=owner, lease_until=now + timedelta(seconds=90),
                attempts=BackgroundJob.attempts + 1)).rowcount
    db.commit()
    if changed:
        db.refresh(job)
        return job


def renew(db, key, owner):
    changed = db.execute(update(BackgroundJob).where(BackgroundJob.key == key, BackgroundJob.owner == owner,
        BackgroundJob.status == 'running').values(lease_until=utc_now() + timedelta(seconds=90))).rowcount
    db.commit()
    return bool(changed)


def finish(db, key, owner, result, *, failed=False):
    job = db.get(BackgroundJob, key)
    if not job or job.owner != owner:
        return
    now = utc_now()
    args = json.loads(job.arguments)
    if failed:
        job.status = 'queued'
        job.available_at = now + timedelta(seconds=min(3600, 30 * 2 ** min(job.attempts, 7)))
    elif job.kind == 'sync' and not args.get('physical_only') and args['days'] in STAGES and args['days'] < 90:
        args['days'] = STAGES[STAGES.index(args['days']) + 1]
        job.arguments = json.dumps(args)
        job.status = 'queued'
        job.available_at = now
    else:
        job.status = 'done'
        job.completed_at = now
        # Both manual and scheduled refreshes respect provider update frequency.
        from app.core.config import get_settings
        job.available_at = now + timedelta(minutes=get_settings().sync_interval_minutes if job.kind == 'sync' else 5)
    job.result = json.dumps(result)
    job.lease_until = None
    db.commit()


def model_key(city, source, station_id, kind, horizon):
    return f'ml:{city}:{source}:{station_id or 0}:{kind}:{horizon}'


def cached_model_response(db, location, horizon, source, station_id, kind):
    from app.schemas import MLForecastResponse, WeatherModelComparisonResponse
    from app.services.datasets import provenance
    key = model_key(location.slug, source, station_id, kind, horizon)
    enqueue(db, key, 'ml', dict(city=location.slug, source=source, station_id=station_id,
        horizon=horizon, model=kind), 100, cooldown=300)
    row = db.get(ModelResult, key)
    cls = MLForecastResponse if kind == 'base' else WeatherModelComparisonResponse
    if row:
        response = cls.model_validate_json(row.response_json)
    else:
        response = cls(status='pending', message='Izračun je u redu čekanja; postojeći podaci ostaju dostupni.',
                       generated_at=utc_now())
    job = db.get(BackgroundJob, key)
    response.computation_status = job.status if job else 'pending'
    if job and job.status == 'running' and job.lease_until and aware_utc(job.lease_until) < utc_now():
        response.computation_status = 'queued'
    response.location, response.source_type, response.station_id = location.slug, source, station_id
    response.provenance = provenance(db, location, source, station_id)
    response.forecast = [point for point in response.forecast if point.timestamp > utc_now()]
    if row and (getattr(response, 'metrics', None) or getattr(response, 'pollution_only', None)):
        response.status = 'ready' if response.forecast else 'comparison_ready_forecast_unavailable'
    return response
