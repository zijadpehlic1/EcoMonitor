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


@asynccontextmanager
async def lifespan(_: FastAPI):
    import os
    import sys
    import subprocess
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_supported_locations(db)
    workers = []
    if settings.enable_background_sync:
        for kind in ('sync', 'ml'):
            workers.append(await asyncio.create_subprocess_exec(sys.executable, '-m', 'app.worker', kind,
                stdin=asyncio.subprocess.PIPE, env={**os.environ, 'ECOMONITOR_MANAGED_WORKER': '1'},
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
    try:
        yield
    finally:
        for worker in workers:
            if worker.returncode is None:
                worker.stdin.write(b'stop\n')
                await worker.stdin.drain()
        for worker in workers:
            with suppress(ProcessLookupError):
                try:
                    await asyncio.wait_for(worker.wait(), timeout=30)
                except TimeoutError:
                    worker.terminate()
                    await worker.wait()



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

