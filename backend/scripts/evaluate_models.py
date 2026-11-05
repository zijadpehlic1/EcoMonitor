"""Reproducible configuration; mutable provider data requires a database snapshot.

Writes actual metrics, dataset hashes, package versions and elapsed seconds. Never creates observations.
"""
import argparse
from datetime import UTC, datetime
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import sys
from time import perf_counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models import Location, SensorStation
from app.services.datasets import pm25_rows
from app.services.weather_ml import generate_weather_model_comparison
from app.services.ml_forecast import generate_pm25_forecast

parser = argparse.ArgumentParser()
parser.add_argument('--city')
args = parser.parse_args()
report = {'generated_at': datetime.now(UTC).isoformat(), 'python': sys.version,
    'packages': {p: importlib.metadata.version(p) for p in ('scikit-learn', 'numpy', 'sqlalchemy', 'fastapi')}, 'evaluations': []}
with SessionLocal() as db:
    cities = db.scalars(select(Location).where(Location.active.is_(True))).all()
    for city in cities:
        if args.city and city.slug != args.city:
            continue
        stations = db.scalars(select(SensorStation).where(SensorStation.location_id == city.id)).all()
        for station in stations:
            rows = pm25_rows(db, city, 'sensor', station.id)
            data_hash = sha256(json.dumps([(r.measured_at.isoformat(), r.pm2_5) for r in rows]).encode()).hexdigest()
            started = perf_counter()
            original = generate_pm25_forecast(db, city, 24, 'sensor', station.id)
            comparison = generate_weather_model_comparison(db, city, 24, 'sensor', station.id)
            report['evaluations'].append({'city': city.slug, 'station': station.name, 'station_id': station.id,
                'pm25_rows': len(rows), 'pm25_sha256': data_hash, 'elapsed_seconds': round(perf_counter()-started, 3),
                'original': original.model_dump(mode='json'), 'comparison': comparison.model_dump(mode='json')})
            print(json.dumps({'city': city.slug, 'station': station.name, 'rows': len(rows),
                'original_status': original.status, 'comparison_status': comparison.status,
                'comparison_test_hours': comparison.test_samples, 'base': comparison.pollution_only.model_dump() if comparison.pollution_only else None,
                'weather': comparison.weather_aware.model_dump() if comparison.weather_aware else None,
                'persistence': comparison.persistence.model_dump() if comparison.persistence else None}), flush=True)
path = Path(__file__).resolve().parents[1] / ('audit-evaluation' + (f'-{args.city}' if args.city else '') + '.json')
path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding='utf-8')
