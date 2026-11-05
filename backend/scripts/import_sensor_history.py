"""Run from backend: python scripts/import_sensor_history.py --city sarajevo --days 92."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import Base, SessionLocal, engine
from app.services.air_quality import ensure_supported_locations
from app.services.sensor_history import synchronize_sensor_history
from app.services.sensor_measurements import _parse_iso

parser = argparse.ArgumentParser()
parser.add_argument('--city', choices=['zenica', 'sarajevo', 'mostar', 'banja-luka'], required=True)
parser.add_argument('--days', type=int, default=92)
parser.add_argument('--end', help='Explicit ISO UTC/offset timestamp for a historical window')
parser.add_argument('--force', action='store_true')
args = parser.parse_args()
Base.metadata.create_all(engine)
with SessionLocal() as db:
    city = ensure_supported_locations(db)[args.city]
    if args.end:
        # Offline research replay; do not run concurrently with background imports.
        from app.models import BackgroundJob
        from app.services.air_quality import utc_now, aware_utc
        leader = db.get(BackgroundJob, 'leader:sync')
        if leader and leader.status == 'running' and aware_utc(leader.lease_until) > utc_now():
            raise SystemExit('Stop the backend worker before an explicit historical replay.')
        result = asyncio.run(synchronize_sensor_history(db, city, days=args.days,
            force=args.force, end=_parse_iso(args.end)))
    else:
        from app.services.jobs import enqueue
        if not 1 <= args.days <= 366:
            raise SystemExit('days must be 1–366')
        queued = enqueue(db, f'sync-history:{city.slug}', 'sync',
            {'city':city.slug,'days':args.days,'physical_only':True}, -10)
        result = {'status': 'queued' if queued else 'cached', 'message':'Start the backend to process the persistent queue.'}
    print(json.dumps(result, ensure_ascii=True))
