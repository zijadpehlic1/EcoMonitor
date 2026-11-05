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
    result = asyncio.run(synchronize_sensor_history(db, city, days=args.days,
        force=args.force, end=_parse_iso(args.end) if args.end else None))
    print(json.dumps(result, ensure_ascii=True))
