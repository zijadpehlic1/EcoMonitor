"""Bounded OpenAQ hourly imports, explicit station identity and quality metadata."""
import asyncio
import json
from datetime import timedelta
from math import isfinite

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Location, SensorStation, SensorMeasurement, SensorImportState, SensorMeasurementMetadata
from app.services.air_quality import aware_utc, utc_now
from app.services.sensor_measurements import (
    OPENAQ_STATIONS, OPENAQ_POLLUTANTS, UNIT, ProviderBatch, _get_json, _parse_iso, _persist_batch,
)

_lock = asyncio.Lock()
PAGE_SIZE = 1000


def parse_hour(item, parameter, start, end):
    """Use interval END, consistent with latest observations; retain full interval."""
    try:
        period = item["period"]
        stamp = _parse_iso(period["datetimeTo"]["utc"])
        first = _parse_iso(period["datetimeFrom"]["utc"])
        value = float(item["value"])
        unit = item["parameter"]["units"].replace("µ", "μ")
        pollutant = OPENAQ_POLLUTANTS[item["parameter"]["name"]]
        if (item["parameter"]["name"] != parameter["name"] or unit != UNIT
                or not isfinite(value) or value < 0 or not start <= stamp <= end
                or stamp - first != timedelta(hours=1) or stamp.minute or stamp.second):
            return None
        coverage = item.get("coverage") or {}
        flags = item.get("flagInfo") or {}
        status = "provider_flagged" if flags.get("hasFlags") else (
            "incomplete_hour" if coverage.get("percentCoverage", 0) < 100 else "unvalidated")
        return (stamp, pollutant, value, unit), status, {
            "period": period, "coverage": coverage, "flagInfo": flags,
            "timestamp_semantics": "interval_end", "endpoint": "hours",
        }
    except (KeyError, TypeError, ValueError):
        return None


async def synchronize_sensor_history(db: Session, location: Location, *, days=92, force=False, end=None, settings=None):
    """92 days initially, then overlap 72 h for delayed/revised reports. All pages or rollback.

    An explicit end allows reproducible historical imports of discontinued stations.
    No credentials or raw exception text are included in results.
    """
    settings = settings or get_settings()
    if location.slug in ('zenica', 'mostar'):
        from app.services.fhmz_history import synchronize_fhmz_history
        return await synchronize_fhmz_history(db, location, days=days, force=force, end=end, settings=settings)
    if not settings.openaq_api_key:
        return {"status": "unavailable", "message": "OpenAQ ključ nije konfiguriran."}
    if not 1 <= days <= 366:
        raise ValueError("Import range must be 1–366 days")
    ids = OPENAQ_STATIONS.get(location.slug, ())
    if not ids:
        return {"status": "unavailable", "message": "Nema potvrđene OpenAQ stanice za ovaj grad."}
    requested_end = aware_utc(end) if end else utc_now()
    if requested_end > utc_now():
        raise ValueError("Historical import cannot include future data")
    headers = {"X-API-Key": settings.openaq_api_key.get_secret_value()}
    results = []
    async with _lock:
        for external_id in ids:
            try:
                station = db.scalar(select(SensorStation).where(
                    SensorStation.external_id == str(external_id), SensorStation.provider.like("OpenAQ /%")))
                state = db.get(SensorImportState, station.id) if station else None
                if (not force and end is None and state and state.completed_at
                        and utc_now() - aware_utc(state.completed_at) < timedelta(hours=24)):
                    results.append({"external_id": external_id, "status": "cached"})
                    continue
                payload = await _get_json(f"{settings.openaq_base_url}/locations/{external_id}", headers=headers, settings=settings)
                meta = payload["results"][0]
                coords = meta.get("coordinates") or {}
                if (meta["id"] != external_id or not meta.get("isMonitor") or meta.get("isMobile")
                        or (meta.get("country") or {}).get("code") != "BA"
                        or abs(float(coords["latitude"]) - location.latitude) > .12
                        or abs(float(coords["longitude"]) - location.longitude) > .15):
                    raise ValueError("Station identity/location mismatch")
                if not meta.get("licenses") or any(lic.get("name") not in ("ODC-BY", "US Public Domain", "CC BY 4.0") for lic in meta["licenses"]):
                    raise ValueError("Station reuse licence is not declared")
                start = requested_end - timedelta(days=days)
                if not force and end is None and state and state.window_end:
                    start = max(start, aware_utc(state.window_end) - timedelta(hours=72))
                provider = (meta.get("provider") or {}).get("name") or "OpenAQ"
                attribution = f"OpenAQ / {provider}; " + "; ".join(
                    f"{lic['name']}: {(lic.get('attribution') or {}).get('name', '')}" for lic in meta['licenses'])
                inserted = updated = skipped = received = 0
                requests = 1  # Station metadata request, plus hourly pages below.
                # Never collapse multiple instruments of the same pollutant silently.
                parameters = set()
                for sensor in meta.get("sensors", []):
                    parameter = sensor.get("parameter") or {}
                    if parameter.get("name") not in OPENAQ_POLLUTANTS:
                        continue
                    if parameter["name"] in parameters:
                        raise ValueError("Multiple instruments for one pollutant need explicit mapping")
                    parameters.add(parameter["name"])
                    parsed = {}
                    for page in range(1, 12):  # <= 366 days / 1000 h, with safety margin
                        data = await _get_json(f"{settings.openaq_base_url}/sensors/{sensor['id']}/hours",
                            headers=headers, settings=settings, params={"datetime_from": start.isoformat(),
                                "datetime_to": requested_end.isoformat(), "limit": PAGE_SIZE, "page": page})
                        requests += 1
                        items = data.get("results", [])
                        received += len(items)
                        for item in items:
                            row = parse_hour(item, parameter, start, requested_end)
                            if row is None:
                                skipped += 1
                            else:
                                parsed[(row[0][0], row[0][1])] = row
                        if len(items) < PAGE_SIZE:
                            break
                        await asyncio.sleep(.6)  # bounded, below free-tier minute rate
                    else:
                        raise ValueError("Pagination bound exceeded; no success checkpoint written")
                    if not parsed:
                        continue
                    batch = ProviderBatch(f"OpenAQ / {provider}", str(external_id), meta["name"],
                        f"https://explore.openaq.org/locations/{external_id}", attribution, True,
                        coords["latitude"], coords["longitude"], [row[0] for row in parsed.values()])
                    added, changed = _persist_batch(db, location, batch)
                    inserted += added
                    updated += changed
                    db.flush()
                    station = db.scalar(select(SensorStation).where(SensorStation.provider == batch.provider,
                        SensorStation.external_id == str(external_id)))
                    records = db.scalars(select(SensorMeasurement).where(SensorMeasurement.station_id == station.id,
                        SensorMeasurement.measured_at >= start, SensorMeasurement.measured_at <= requested_end,
                        SensorMeasurement.pollutant == OPENAQ_POLLUTANTS[parameter['name']])).all()
                    record_ids = [r.id for r in records]
                    saved_metadata = {}
                    # SQLite parameter limits are respected; avoid a SELECT for every hour.
                    for offset in range(0, len(record_ids), 500):
                        saved_metadata.update({m.measurement_id: m for m in db.scalars(select(SensorMeasurementMetadata)
                            .where(SensorMeasurementMetadata.measurement_id.in_(record_ids[offset:offset + 500]))).all()})
                    for record in records:
                        row = parsed.get((aware_utc(record.measured_at), record.pollutant))
                        if row is None:
                            continue
                        if record.validation_status != row[1]:
                            record.ingested_at = utc_now()
                        record.validation_status = row[1]
                        meta_row = saved_metadata.get(record.id)
                        if meta_row is None:
                            db.add(SensorMeasurementMetadata(measurement_id=record.id,
                                provider_sensor_id=str(sensor["id"]), metadata_json=json.dumps(row[2])))
                        else:
                            meta_row.provider_sensor_id = str(sensor["id"])
                            meta_row.metadata_json = json.dumps(row[2])
                if station:
                    db.merge(SensorImportState(station_id=station.id, metadata_json=json.dumps(meta),
                        completed_at=utc_now(), window_start=start, window_end=requested_end))
                db.commit()
                results.append({"external_id": external_id, "status": "success", "received": received,
                    "inserted": inserted, "updated": updated, "skipped": skipped, "provider_requests": requests})
            except Exception as exc:
                db.rollback()
                results.append({"external_id": external_id, "status": "failed", "error": type(exc).__name__})
    return {"status": "failed" if any(r['status'] == 'failed' for r in results) else "success", "stations": results}
