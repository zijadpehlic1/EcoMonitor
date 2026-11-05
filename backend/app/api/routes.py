from fastapi import APIRouter, Depends, HTTPException, Query
import json
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import get_settings
from app.models import AirQualityReading, Location, SensorMeasurement, SensorStation, SensorImportState, SyncRun, WeatherReading
from app.schemas import (
    DashboardResponse,
    HistoricalSeriesResponse,
    LocationOut,
    MLForecastResponse,
    RefreshResponse,
    SensorCoverageOut,
    SensorCurrentResponse,
    SensorRefreshResponse,
    WeatherDashboardResponse,
    WeatherModelComparisonResponse,
    WeatherRefreshResponse,
)
from app.services.air_quality import ensure_supported_locations, synchronize_location
from app.services.dashboard import build_dashboard
from app.services.history import build_historical_series
from app.services.jobs import cached_model_response, enqueue
from app.services.datasets import resolve_station
from app.services.sensor_history import synchronize_sensor_history
from app.services.air_quality import aware_utc
from app.services.weather import build_weather_dashboard, synchronize_weather
from app.models import BackgroundJob, DataCoverage
from app.services.sensor_measurements import (
    build_sensor_coverage,
    build_sensor_current,
    synchronize_sensor_location,
)

router = APIRouter()
CLIENT_POLLING_MINUTES = 15


def resolve_location(db: Session, slug: str) -> Location:
    location = db.scalar(select(Location).where(Location.slug == slug, Location.active.is_(True)))
    if not location:
        raise HTTPException(status_code=404, detail=f"Unknown location: {slug}")
    return location


def validate_dataset(db, location, source, station_id):
    if source == "sensor":
        try:
            resolve_station(db, location, station_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    elif station_id is not None:
        raise HTTPException(status_code=422, detail="Stanica je dozvoljena samo uz senzorski izvor.")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy", "service": "EcoMonitor API"}


@router.get("/locations", response_model=list[LocationOut])
def locations(db: Session = Depends(get_db)) -> list[Location]:
    ensure_supported_locations(db)
    return list(db.scalars(select(Location).where(Location.active.is_(True)).order_by(Location.name)).all())


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    location: str = "zenica",
    hours: int = Query(default=24, ge=6, le=24 * 92),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    return build_dashboard(db, resolve_location(db, location), hours)


@router.get("/history", response_model=HistoricalSeriesResponse)
def history(
    location: str = "zenica",
    hours: int = Query(default=24, ge=6, le=24 * 92),
    grouping: str = Query(default="hourly", pattern="^(hourly|daily)$"),
    aggregation: str = Query(default="average", pattern="^(average|maximum)$"),
    source: str = Query(default="modeled", pattern="^(modeled|sensor)$"),
    station_id: int | None = None,
    db: Session = Depends(get_db),
) -> HistoricalSeriesResponse:
    selected = resolve_location(db, location)
    validate_dataset(db, selected, source, station_id)
    return build_historical_series(
        db,
        resolve_location(db, location),
        hours=hours,
        grouping=grouping,
        aggregation=aggregation,
        source=source, station_id=station_id,
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    location: str = "zenica",
    force: bool = False,
    db: Session = Depends(get_db),
) -> RefreshResponse:
    selected = resolve_location(db, location)
    queued = enqueue(db, f'sync:{selected.slug}', 'sync', {'city': selected.slug, 'days': 90}, -10)
    return RefreshResponse(status='queued' if queued else 'cached', received=0, inserted=0, updated=0,
        message='Osvježavanje je zakazano u pozadini.' if queued else 'Provjera je već zakazana ili je predmemorija još svježa.')



@router.get("/forecast/pm25", response_model=MLForecastResponse)
def pm25_forecast(
    location: str = "zenica",
    horizon: int = Query(default=24, ge=6, le=72),
    source: str = Query(default="modeled", pattern="^(modeled|sensor)$"),
    station_id: int | None = None,
    db: Session = Depends(get_db),
) -> MLForecastResponse:
    selected = resolve_location(db, location)
    validate_dataset(db, selected, source, station_id)
    return cached_model_response(db, selected, horizon, source, station_id, 'base')


@router.get("/weather", response_model=WeatherDashboardResponse)
def weather(
    location: str = "zenica",
    db: Session = Depends(get_db),
) -> WeatherDashboardResponse:
    return build_weather_dashboard(db, resolve_location(db, location))


@router.post('/forecast/retrain')
def retrain(location: str = 'zenica', source: str = Query(default='modeled', pattern='^(modeled|sensor)$'),
    station_id: int | None = None, db: Session = Depends(get_db)):
    from sqlalchemy import update
    from app.services.jobs import model_key
    from app.services.air_quality import utc_now
    selected = resolve_location(db, location)
    validate_dataset(db, selected, source, station_id)
    for model in ('base', 'weather'):
        key = model_key(location, source, station_id, model, 24)
        db.execute(update(BackgroundJob).where(BackgroundJob.key == key, BackgroundJob.status == 'done')
            .values(available_at=utc_now(), completed_at=None))
        db.commit()
        enqueue(db, key, 'ml', dict(city=location, source=source, station_id=station_id, model=model, horizon=24, retrain=True), 90)
    return {'status': 'queued', 'message': 'Ponovno treniranje je zatraženo; postojeći rezultati ostaju dostupni.'}


@router.post("/weather/refresh", response_model=WeatherRefreshResponse)
async def weather_refresh(
    location: str = "zenica",
    force: bool = False,
    db: Session = Depends(get_db),
) -> WeatherRefreshResponse:
    result = await refresh(location, force, db)
    return WeatherRefreshResponse(status=result.status, live_status=result.status,
        historical_status=result.status, archive_status=result.status, inserted=0, updated=0, message=result.message)



@router.get(
    "/forecast/pm25/weather-comparison",
    response_model=WeatherModelComparisonResponse,
)
def pm25_weather_comparison(
    location: str = "zenica",
    horizon: int = Query(default=24, ge=6, le=72),
    source: str = Query(default="modeled", pattern="^(modeled|sensor)$"),
    station_id: int | None = None,
    db: Session = Depends(get_db),
) -> WeatherModelComparisonResponse:
    selected = resolve_location(db, location)
    validate_dataset(db, selected, source, station_id)
    return cached_model_response(db, selected, horizon, source, station_id, 'weather')


@router.get("/sensors/stations")
def sensor_stations(location: str = "zenica", db: Session = Depends(get_db)):
    selected = resolve_location(db, location)
    rows = db.execute(select(SensorStation, func.count(SensorMeasurement.id),
        func.min(SensorMeasurement.measured_at), func.max(SensorMeasurement.measured_at))
        .outerjoin(SensorMeasurement, SensorMeasurement.station_id == SensorStation.id)
        .where(SensorStation.location_id == selected.id).group_by(SensorStation.id)
        .order_by(SensorStation.last_measurement_at.desc())).all()
    # Licence metadata survives legacy current-value refreshes that stored only provider attribution.
    attribution = {s.id: s.attribution for s, *_ in rows}
    for state in db.scalars(select(SensorImportState).where(SensorImportState.station_id.in_(attribution))).all():
        meta = json.loads(state.metadata_json)
        if meta.get("licenses"):
            attribution[state.station_id] = f"OpenAQ / {(meta.get('provider') or {}).get('name', '')}; " + "; ".join(
                f"{lic.get('name', '')}: {(lic.get('attribution') or {}).get('name', '')}" for lic in meta['licenses'])
    quality = {}
    for sid, validation, amount in db.execute(select(SensorMeasurement.station_id,
        SensorMeasurement.validation_status, func.count(SensorMeasurement.id))
        .where(SensorMeasurement.station_id.in_(attribution))
        .group_by(SensorMeasurement.station_id, SensorMeasurement.validation_status)):
        quality.setdefault(sid, {})[validation] = amount
    return [{"id": s.id, "name": s.name, "provider": s.provider, "source_url": s.source_url,
        "attribution": attribution[s.id], "latitude": s.latitude, "longitude": s.longitude,
        "location": selected.slug, "measurement_type": "physical", "validation_counts": quality.get(s.id, {}),
        "measurement_count": count, "first_measurement_at": aware_utc(first) if first else None,
        "last_measurement_at": aware_utc(last) if last else None} for s, count, first, last in rows]


@router.post("/sensors/history/refresh")
async def sensor_history_refresh(location: str = "zenica", days: int = Query(default=92, ge=1, le=366),
    force: bool = False, db: Session = Depends(get_db)):
    selected = resolve_location(db, location)
    queued = enqueue(db, f'sync-history:{selected.slug}', 'sync', {'city': selected.slug, 'days': days, 'physical_only': True}, -10)
    return {'status': 'queued' if queued else 'cached', 'message': 'Inkrementalna historija se provjerava u pozadini.'}



@router.get("/sensors/current", response_model=SensorCurrentResponse)
def sensor_current(
    location: str = "zenica",
    db: Session = Depends(get_db),
) -> SensorCurrentResponse:
    return build_sensor_current(db, resolve_location(db, location))


@router.get("/sensors/coverage", response_model=list[SensorCoverageOut])
def sensor_coverage(db: Session = Depends(get_db)) -> list[SensorCoverageOut]:
    supported = ensure_supported_locations(db)
    return build_sensor_coverage(db, list(supported.values()))


@router.post("/sensors/refresh", response_model=SensorRefreshResponse)
async def sensor_refresh(
    location: str = "zenica",
    force: bool = False,
    db: Session = Depends(get_db),
) -> SensorRefreshResponse:
    result = await refresh(location, force, db)
    return SensorRefreshResponse(status=result.status, provider=None, station_name=None,
        received=0, inserted=0, updated=0, message=result.message)



@router.get("/sustainability/metrics")
def sustainability_metrics(
    location: str = "zenica",
    db: Session = Depends(get_db),
) -> dict:
    selected = resolve_location(db, location)
    readings = int(
        db.scalar(select(func.count(AirQualityReading.id)).where(AirQualityReading.location_id == selected.id))
        or 0
    )
    weather_readings = int(
        db.scalar(select(func.count(WeatherReading.id)).where(WeatherReading.location_id == selected.id))
        or 0
    )
    sensor_readings = int(
        db.scalar(
            select(func.count(SensorMeasurement.id))
            .join(SensorStation, SensorMeasurement.station_id == SensorStation.id)
            .where(SensorStation.location_id == selected.id)
        )
        or 0
    )
    successful_requests = int(
        db.scalar(
            select(func.count(SyncRun.id)).where(
                SyncRun.location_id == selected.id,
                SyncRun.status == "success",
            )
        )
        or 0
    )
    failed_requests = int(
        db.scalar(
            select(func.count(SyncRun.id)).where(
                SyncRun.location_id == selected.id,
                SyncRun.status == "failed",
            )
        )
        or 0
    )
    received_rows = int(
        db.scalar(
            select(func.coalesce(func.sum(SyncRun.records_received), 0)).where(
                SyncRun.location_id == selected.id,
                SyncRun.status == "success",
            )
        )
        or 0
    )
    inserted_rows = int(
        db.scalar(
            select(func.coalesce(func.sum(SyncRun.records_inserted), 0)).where(
                SyncRun.location_id == selected.id,
                SyncRun.status == "success",
            )
        )
        or 0
    )
    updated_rows = int(
        db.scalar(
            select(func.coalesce(func.sum(SyncRun.records_updated), 0)).where(
                SyncRun.location_id == selected.id,
                SyncRun.status == "success",
            )
        )
        or 0
    )
    settings = get_settings()
    from app.models import ModelArtifact, ModelResult, ModelExecution
    model_runs = db.scalars(select(ModelExecution).where(ModelExecution.model_key.like(f'ml:{selected.slug}:%'))).all()
    return {
        "location": selected.slug,
        "persisted_models": db.scalar(select(func.count(ModelArtifact.key)).where(ModelArtifact.key.like(f'{selected.slug}:%'))),
        "persisted_model_results": db.scalar(select(func.count(ModelResult.key)).where(ModelResult.key.like(f'ml:{selected.slug}:%'))),
        "recorded_training_runs": sum(r.trained for r in model_runs),
        "recorded_evaluation_runs": sum(r.evaluated for r in model_runs),
        "recorded_prediction_computations": sum(r.forecast_recomputed for r in model_runs),
        "model_execution_note": "Counts start with model_executions instrumentation; older artifacts are not retroactively counted. A training run may fit both evaluation and production forests.",
        "stored_hourly_records": readings,
        "stored_hourly_weather_records": weather_readings,
        "stored_physical_sensor_measurements": sensor_readings,
        "successful_provider_requests": successful_requests,
        "failed_provider_requests": failed_requests,
        "successful_sync_runs": successful_requests,
        "failed_sync_runs": failed_requests,
        "provider_rows_received": received_rows,
        "new_rows_inserted": inserted_rows,
        "existing_rows_refreshed_in_place": updated_rows,
        "provider_cache_minutes": settings.sync_interval_minutes,
        "frontend_polling_policy_minutes": CLIENT_POLLING_MINUTES,
        "estimated_dashboard_requests_per_active_client_hour": round(
            60 / CLIENT_POLLING_MINUTES, 2
        ),
        "weather_archive_refresh_hours": settings.weather_history_sync_hours,
        "sensor_cache_minutes": settings.sensor_cache_minutes,
        "sensor_freshness_hours": settings.sensor_freshness_hours,
        "database_indexes": ["location_id + measured_at", "measured_at", "is_forecast"],
        "measurement_notes": [
            "Legacy *_provider_requests fields count sync runs, not HTTP requests; one run can make several requests. Historical import request counts are returned by its endpoint.",
            "Existing rows are refreshed by identity; this count is not a count of cache hits or avoided requests.",
            "Cache skips are not persisted, so avoided provider calls are not directly measured.",
            "Use X-Process-Time-Ms on API responses for server-side request latency.",
        ],
    }



@router.get('/sync/status')
def sync_status(location: str = 'zenica', db: Session = Depends(get_db)):
    selected = resolve_location(db, location)
    job = db.get(BackgroundJob, f'sync:{location}')
    args = json.loads(job.arguments) if job else {}
    # Promote only already queued initial work. A city visit never schedules a provider refresh.
    if job and job.status == 'queued' and args.get('days', 90) < 90 and job.priority >= 0:
        from sqlalchemy import update
        db.execute(update(BackgroundJob).where(BackgroundJob.key == job.key).values(priority=-1))
        db.commit()
    rows = db.execute(select(DataCoverage.dataset, DataCoverage.status, func.count())
        .where(DataCoverage.location_id == selected.id).group_by(DataCoverage.dataset, DataCoverage.status)).all()
    latest_sync = db.scalar(select(func.max(SyncRun.completed_at)).where(SyncRun.location_id == selected.id, SyncRun.status == 'success'))
    latest_sensor = db.scalar(select(func.max(SensorImportState.completed_at)).join(SensorStation,
        SensorStation.id == SensorImportState.station_id).where(SensorStation.location_id == selected.id))
    revision = '|'.join(str(value or '') for value in (latest_sync, latest_sensor))
    last_result = json.loads(job.result) if job and job.result else {}
    failed_sources = [name for name, result in last_result.get('sources', {}).items()
        if isinstance(result, dict) and result.get('status') == 'failed']
    return {'location': location, 'status': job.status if job else 'idle', 'revision': revision, 'failed_sources': failed_sources,
        'stage_days': args.get('days', 0), 'completed_at': job.completed_at if job else None,
        'last_result': json.loads(job.result) if job and job.result else None,
        'coverage': [{'dataset': dataset, 'status': status, 'checked_days': count} for dataset,status,count in rows],
        'note': 'Provjereni period nije potvrda potpunih mjerenja; dostupnost sati je prikazana na grafikonu.'}
