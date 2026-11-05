from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AirQualityReading, Location
from app.schemas import DashboardResponse, LocationOut, ReadingOut, SyncInfo
from app.services.air_quality import (
    MODEL_NAME,
    SOURCE_NAME,
    SOURCE_URL,
    aware_utc,
    get_last_successful_sync,
    stored_reading_count,
    utc_now,
)

UNITS = {
    "pm2_5": "μg/m³",
    "pm10": "μg/m³",
    "nitrogen_dioxide": "μg/m³",
    "sulphur_dioxide": "μg/m³",
    "carbon_monoxide": "μg/m³",
    "ozone": "μg/m³",
    "european_aqi": "EAQI",
}


def _reading_out(reading: AirQualityReading) -> ReadingOut:
    measured_at = aware_utc(reading.measured_at)
    return ReadingOut(
        measured_at=measured_at,
        pm2_5=reading.pm2_5,
        pm10=reading.pm10,
        nitrogen_dioxide=reading.nitrogen_dioxide,
        sulphur_dioxide=reading.sulphur_dioxide,
        carbon_monoxide=reading.carbon_monoxide,
        ozone=reading.ozone,
        european_aqi=reading.european_aqi,
        source_name=reading.source_name,
        source_type=reading.source_type,
        model_name=reading.model_name,
        is_forecast=measured_at > utc_now(),
    )


def build_dashboard(db: Session, location: Location, hours: int) -> DashboardResponse:
    now = utc_now()
    start = now - timedelta(hours=hours)
    readings = db.scalars(
        select(AirQualityReading)
        .where(
            AirQualityReading.location_id == location.id,
            AirQualityReading.source_name == SOURCE_NAME,
            AirQualityReading.source_type == "modeled",
            AirQualityReading.measured_at >= start,
            AirQualityReading.measured_at <= now,
        )
        .order_by(AirQualityReading.measured_at.asc())
    ).all()
    latest = readings[-1] if readings else db.scalar(
        select(AirQualityReading)
        .where(
            AirQualityReading.location_id == location.id,
            AirQualityReading.source_name == SOURCE_NAME,
            AirQualityReading.source_type == "modeled",
            AirQualityReading.measured_at <= now,
        )
        .order_by(AirQualityReading.measured_at.desc())
        .limit(1)
    )

    last_sync = get_last_successful_sync(db, location.id)
    cache_age = None
    if last_sync and last_sync.completed_at:
        cache_age = round((now - aware_utc(last_sync.completed_at)).total_seconds() / 60, 1)

    return DashboardResponse(
        location=LocationOut.model_validate(location),
        latest=_reading_out(latest) if latest else None,
        history=[_reading_out(item) for item in readings],
        units=UNITS,
        source={
            "name": SOURCE_NAME,
            "model": MODEL_NAME,
            "type": "modeled",
            "url": SOURCE_URL,
            "disclaimer": (
                "CAMS atmospheric model estimates supplied through Open-Meteo. "
                f"These values are not measurements from a physical station in {location.name}."
            ),
        },
        sync=SyncInfo(
            status="available" if latest else "awaiting_data",
            last_successful_sync=aware_utc(last_sync.completed_at)
            if last_sync and last_sync.completed_at
            else None,
            records_stored=stored_reading_count(db, location.id),
            cache_age_minutes=cache_age,
        ),
        requested_hours=hours,
        generated_at=datetime.now(UTC),
    )

