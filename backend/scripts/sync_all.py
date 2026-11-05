"""Queue cache-aware synchronization; the running backend owns execution."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import Base, SessionLocal, engine
from app.services.air_quality import ensure_supported_locations
from app.services.jobs import seed_sync
Base.metadata.create_all(engine)
with SessionLocal() as db:
    ensure_supported_locations(db)
    seed_sync(db)
print('Persistent synchronization queue initialized; start the backend to execute it.')
