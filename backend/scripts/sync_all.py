"""One cache-aware synchronization, no background service needed."""
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import Base, SessionLocal, engine
from app.services.air_quality import ensure_supported_locations, synchronize_location
from app.services.weather import synchronize_weather
from app.services.sensor_measurements import synchronize_sensor_location

async def main():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for city in ensure_supported_locations(db).values():
            for sync in (synchronize_sensor_location, synchronize_location, synchronize_weather):
                try:
                    result = await sync(db, city)
                    print(json.dumps({'city': city.slug, 'service': sync.__name__, 'status': result.status}), flush=True)
                except Exception as exc:
                    db.rollback()
                    print(json.dumps({'city': city.slug, 'service': sync.__name__, 'error': type(exc).__name__}), flush=True)

asyncio.run(main())
