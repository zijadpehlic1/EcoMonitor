"""Explicit dataset selection shared by charts and both Random Forest models."""
from math import isfinite
from types import SimpleNamespace
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import AirQualityReading, Location, SensorMeasurement, SensorStation
from app.services.air_quality import SOURCE_NAME, aware_utc, utc_now


def resolve_station(db: Session, location: Location, station_id: int | None):
    station = db.get(SensorStation, station_id) if station_id else None
    if not station or station.location_id != location.id:
        raise ValueError("Stanica ne pripada odabranom gradu.")
    return station


def pollution_rows(db, location, source="modeled", station_id=None, start=None, end=None):
    end = end or utc_now()
    if source == "sensor":
        station = resolve_station(db, location, station_id)
        query = select(SensorMeasurement).where(
            SensorMeasurement.station_id == station.id, SensorMeasurement.measured_at <= end,
            SensorMeasurement.unit == "μg/m³", SensorMeasurement.validation_status == "unvalidated")
        if start:
            query = query.where(SensorMeasurement.measured_at >= start)
        grouped = {}
        for row in db.scalars(query.order_by(SensorMeasurement.measured_at)).all():
            if not isfinite(row.value) or row.value < 0:
                continue
            stamp = aware_utc(row.measured_at)
            item = grouped.setdefault(stamp, SimpleNamespace(measured_at=stamp,
                pm2_5=None, pm10=None, nitrogen_dioxide=None, sulphur_dioxide=None,
                carbon_monoxide=None, ozone=None, ingested_at=aware_utc(row.ingested_at)))
            if row.pollutant in ("pm2_5", "pm10", "nitrogen_dioxide", "sulphur_dioxide", "carbon_monoxide", "ozone"):
                setattr(item, row.pollutant, row.value)
            item.ingested_at = max(item.ingested_at, aware_utc(row.ingested_at))
        return list(grouped.values())
    if source != "modeled" or station_id is not None:
        raise ValueError("Neispravan izbor izvora podataka.")
    query = select(AirQualityReading).where(AirQualityReading.location_id == location.id,
        AirQualityReading.source_name == SOURCE_NAME, AirQualityReading.source_type == "modeled",
        AirQualityReading.measured_at <= end)
    if start:
        query = query.where(AirQualityReading.measured_at >= start)
    return list(db.scalars(query.order_by(AirQualityReading.measured_at)).all())


def pm25_rows(db, location, source="modeled", station_id=None):
    return [r for r in pollution_rows(db, location, source, station_id)
            if r.pm2_5 is not None and isfinite(r.pm2_5) and r.pm2_5 >= 0]


def provenance(db, location, source, station_id):
    if source == "sensor":
        station = resolve_station(db, location, station_id)
        return f"Stvarna mjerenja: {station.name} ({station.provider}); automatski podaci nisu konačno validirani."
    return "Modelirani podaci: CAMS / Open-Meteo; nisu stvarna mjerenja."
