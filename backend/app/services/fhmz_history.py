"""Public FHMZ portal history, source (not validated) hourly data only.

Endpoint/parameters are those exposed by aqdata.htm, /js/data.js and forms/type1.
Public access is not a redistribution licence: keep attribution and academic-use limitation.
"""
import asyncio
import json
from datetime import datetime, timedelta, UTC
from math import isfinite
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.models import SensorStation, SensorImportState, SensorMeasurement, SensorMeasurementMetadata
from app.services.air_quality import aware_utc, utc_now
from app.services.sensor_measurements import (
    FHMZ_PRIMARY_STATIONS, FHMZ_PROVIDER, FHMZ_SOURCE_URL, UNIT, ProviderBatch, _get_json, _persist_batch,
)

FIELDS = {379: 'pm2_5', 287: 'pm10', 657: 'nitrogen_dioxide', 1: 'sulphur_dioxide', 499: 'ozone'}
_lock = asyncio.Lock()


def parse_fhmz_hour(row, pollutant, zone, start, end):
    try:
        naive = datetime.fromisoformat(row[0])
        if naive.tzinfo is not None or naive.minute or naive.second:
            return None
        early, late = naive.replace(tzinfo=zone, fold=0), naive.replace(tzinfo=zone, fold=1)
        if early.utcoffset() != late.utcoffset():
            return None
        stamp = early.astimezone(UTC)
        value = float(row[1])
        if not isfinite(value) or value < 0 or not start <= stamp <= end:
            return None
        return (stamp, pollutant, value, UNIT), 'unvalidated' if row[2] == 'Valid' else 'provider_flagged', {
            'timestamp_semantics': 'interval_end', 'provider_timestamp_local': row[0],
            'provider_quality': row[2], 'provider_flag': row[3] if len(row) > 3 else None,
            'aqdata_type': 0, 'note': 'Valid flag on source data is not final validation',
        }
    except (ValueError, TypeError, IndexError):
        return None


async def synchronize_fhmz_history(db, location, *, days=92, force=False, end=None, settings):
    configured = FHMZ_PRIMARY_STATIONS.get(location.slug)
    if not configured:
        return {'status': 'unavailable', 'message': 'Nema potvrđene FHMZ stanice.'}
    if not 1 <= days <= 366:
        raise ValueError('Import range must be 1–366 days')
    explicit_end = end is not None
    end = aware_utc(end) if end else utc_now()
    if end > utc_now():
        raise ValueError('Historical import cannot include future data')
    external_id, name = configured
    async with _lock:
        station = db.scalar(select(SensorStation).where(SensorStation.provider == FHMZ_PROVIDER,
            SensorStation.external_id == str(external_id)))
        state = db.get(SensorImportState, station.id) if station else None
        if not force and not explicit_end and state and state.completed_at and utc_now() - aware_utc(state.completed_at) < timedelta(hours=24):
            return {'status': 'cached'}
        start = end - timedelta(days=days)
        if not force and not explicit_end and state and state.window_end:
            start = max(start, aware_utc(state.window_end) - timedelta(hours=72))
        zone = ZoneInfo(location.timezone)
        try:
            meta = await _get_json(f'{settings.fhmz_air_quality_url}/rest/station/detail/{external_id}', settings=settings)
            if (meta.get('id') != external_id or meta.get('name') != name or meta.get('mobile')
                    or abs(float(meta['latitude']) - location.latitude) > .12
                    or abs(float(meta['longitude']) - location.longitude) > .15):
                raise ValueError('FHMZ station identity mismatch')
            collected = {}
            received = skipped = requests = 0
            for external_pollutant, pollutant in FIELDS.items():
                data = await _get_json(f'{settings.fhmz_air_quality_url}/rest/aqdata/data', settings=settings,
                    params={'station': external_id, 'pollutant': external_pollutant, 'aqdata_type': 0,
                        'begin_date': start.astimezone(zone).strftime('%d.%m.%Y.'),
                        'end_date': end.astimezone(zone).strftime('%d.%m.%Y.')})
                requests += 1
                if not isinstance(data, list):
                    raise ValueError('Unexpected FHMZ history response')
                received += len(data)
                for item in data:
                    parsed = parse_fhmz_hour(item, pollutant, zone, start, end)
                    if parsed is None:
                        skipped += 1
                    else:
                        collected[(parsed[0][0], pollutant)] = parsed
                await asyncio.sleep(.25)
            if not collected:
                return {'status': 'unavailable', 'received': received, 'skipped': skipped}
            batch = ProviderBatch(FHMZ_PROVIDER, str(external_id), name, FHMZ_SOURCE_URL,
                'Federalni hidrometeorološki zavod BiH; javni izvorni satni podaci; uslovi redistribucije nisu potvrđeni',
                True, meta['latitude'], meta['longitude'], [r[0] for r in collected.values()])
            inserted, updated = _persist_batch(db, location, batch)
            db.flush()
            station = db.scalar(select(SensorStation).where(SensorStation.provider == FHMZ_PROVIDER,
                SensorStation.external_id == str(external_id)))
            records = db.scalars(select(SensorMeasurement).where(SensorMeasurement.station_id == station.id,
                SensorMeasurement.measured_at >= start, SensorMeasurement.measured_at <= end)).all()
            existing = {m.measurement_id: m for m in db.scalars(select(SensorMeasurementMetadata)
                .join(SensorMeasurement, SensorMeasurement.id == SensorMeasurementMetadata.measurement_id)
                .where(SensorMeasurement.station_id == station.id)).all()}
            for record in records:
                parsed = collected.get((aware_utc(record.measured_at), record.pollutant))
                if parsed is None:
                    continue
                if record.validation_status != parsed[1]:
                    record.ingested_at = utc_now()
                record.validation_status = parsed[1]
                metadata = existing.get(record.id)
                if metadata is None:
                    metadata = SensorMeasurementMetadata(measurement_id=record.id,
                        provider_sensor_id=f'FHMZ:{external_id}:{record.pollutant}')
                    db.add(metadata)
                metadata.metadata_json = json.dumps(parsed[2])
            db.merge(SensorImportState(station_id=station.id, metadata_json=json.dumps(meta),
                completed_at=utc_now(), window_start=start, window_end=end))
            db.commit()
            return {'status': 'success', 'received': received, 'inserted': inserted, 'updated': updated,
                'skipped': skipped, 'provider_requests': requests + 1, 'station': name}
        except Exception as exc:
            db.rollback()
            return {'status': 'failed', 'error': type(exc).__name__}
