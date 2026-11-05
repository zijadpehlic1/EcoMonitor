import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.services.air_quality import ensure_default_location, ensure_supported_locations, synchronize_location
from app.services.sensor_measurements import synchronize_sensor_location
from app.services.weather import synchronize_weather
from app.services.sensor_history import synchronize_sensor_history

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def background_sync_loop() -> None:
    while True:
        try:
            with SessionLocal() as db:
                for location in ensure_supported_locations(db).values():
                    for sync in (synchronize_sensor_location, synchronize_location, synchronize_weather, synchronize_sensor_history):
                        try:
                            result = await sync(db, location)
                            logger.info("%s for %s: %s", sync.__name__, location.slug,
                                result.get("status") if isinstance(result, dict) else result.status)
                        except Exception as exc:
                            db.rollback()
                            logger.warning("%s for %s failed: %s", sync.__name__, location.slug, type(exc).__name__)
        except Exception:
            logger.exception("Unexpected background synchronization failure")
        await asyncio.sleep(max(settings.sync_interval_minutes, 5) * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_supported_locations(db)

    task = None
    if settings.enable_background_sync:
        task = asyncio.create_task(background_sync_loop())
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "REST API for modeled air-quality and weather data with leakage-safe PM2.5 forecasting. "
        "Interactive documentation is available at /docs."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)


@app.middleware("http")
async def add_performance_headers(request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.2f}"
    response.headers["X-EcoMonitor-Cache-Policy"] = f"provider-max-age={settings.sync_interval_minutes * 60}"
    return response


@app.get("/")
def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs", "health": f"{settings.api_prefix}/health"}

