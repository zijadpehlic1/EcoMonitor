"""Persistent interval planning; coverage means checked, never 'all hours measured'."""
from datetime import datetime, timedelta, UTC
from sqlalchemy import select, func
from app.models import DataCoverage, AirQualityReading, WeatherReading, SensorMeasurement, SensorStation, SensorImportState, SyncRun
from app.services import air_quality as aq, weather as wx
from app.core.config import get_settings
from app.services.storage import upsert


def days_between(start, end):
    while start <= end:
        yield start
        start += timedelta(days=1)


def mark(db, location, dataset, start, end, status='checked', retry=None):
    now = aq.utc_now()
    upsert(db, DataCoverage, [dict(key=f'{location.id}:{dataset}:{day}', location_id=location.id,
        dataset=dataset, day=day, status=status, checked_at=now, retry_after=retry)
        for day in days_between(start,end)], ['key'])
    db.commit()


def stored_times(db, location, dataset):
    if dataset.startswith('sensor:'):
        return db.scalars(select(SensorMeasurement.measured_at).where(
            SensorMeasurement.station_id == int(dataset.split(':')[1]))).all()
    cls = AirQualityReading if dataset == aq.SOURCE_NAME else WeatherReading
    return db.scalars(select(cls.measured_at).where(cls.location_id == location.id,
        cls.source_name == dataset)).all()


def missing_ranges(db, location, dataset, start, end, *, recent_hours=0, ttl_minutes=30):
    if start > end:
        return []
    now = aq.utc_now()
    records = {r.day: r for r in db.scalars(select(DataCoverage).where(
        DataCoverage.location_id == location.id, DataCoverage.dataset == dataset,
        DataCoverage.day >= start, DataCoverage.day <= end)).all()}
    # Adopt already downloaded legacy history; absent dates are still fetched.
    # Partial existing dates are probed once rather than assumed complete.
    counts = {}
    for timestamp in stored_times(db, location, dataset):
        stamp = aq.aware_utc(timestamp)
        counts.setdefault(stamp.date(), set()).add(stamp.hour)
    adopted = False
    if dataset.startswith('sensor:'):
        prior = db.get(SensorImportState, int(dataset.split(':')[1]))
        previous_check = prior.completed_at if prior else None
    else:
        prior = wx._last_source_sync(db, location.id, dataset)
        previous_check = prior.completed_at if prior else None
    for day in days_between(start, end):
        if day not in records and len(counts.get(day, set())) == 24:
            row = DataCoverage(key=f'{location.id}:{dataset}:{day}', location_id=location.id,
                dataset=dataset, day=day, status='adopted', checked_at=aq.aware_utc(previous_check) if previous_check else now, retry_after=None)
            db.add(row)
            records[day] = row
            adopted = True
    if adopted:
        db.commit()
    wanted = []
    for day in days_between(start, end):
        row = records.get(day)
        recent = day >= (now - timedelta(hours=recent_hours)).date() if recent_hours else False
        due = not row or (row.retry_after and aq.aware_utc(row.retry_after) <= now)
        if row and row.retry_after and aq.aware_utc(row.retry_after) > now:
            due = False
        elif recent and row and now - aq.aware_utc(row.checked_at) >= timedelta(minutes=ttl_minutes):
            due = True
        if due:
            wanted.append(day)
    # Merge adjacent missing dates, bounded to a week to limit failed-request cost.
    ranges = []
    for day in wanted:
        if ranges and day == ranges[-1][1] + timedelta(days=1) and (day-ranges[-1][0]).days < 7:
            ranges[-1] = (ranges[-1][0], day)
        else:
            ranges.append((day, day))
    return ranges


async def sync_dataset(db, location, dataset, start, end, settings, *, live=False):
    inserted = updated = requests = 0
    ranges = missing_ranges(db, location, dataset, start, end,
        recent_hours=settings.sync_revision_hours if dataset != wx.HISTORICAL_WEATHER_SOURCE else 24 * 8,
        ttl_minutes=settings.sync_interval_minutes if live or dataset == aq.SOURCE_NAME else settings.weather_history_sync_hours * 60)
    for first, last in ranges:
        run = wx._start_sync_run(db, location, dataset)
        try:
            params = dict(latitude=location.latitude, longitude=location.longitude, timeformat='unixtime',
                timezone='GMT', start_date=first.isoformat(), end_date=last.isoformat(), cell_selection='land')
            if dataset == aq.SOURCE_NAME:
                params.update(hourly=','.join(aq.POLLUTANTS), domains='cams_europe')
                payload = await wx._fetch_json(settings.open_meteo_base_url, params, settings)
                requests += 1
                result = aq.persist_payload(db, location, payload, run)
                inserted += result.inserted; updated += result.updated
            else:
                archive = dataset == wx.ARCHIVED_WEATHER_SOURCE
                fields = wx.ARCHIVE_FIELD_MAP if archive else {f: f for f in wx.HOURLY_FIELDS}
                url = settings.open_meteo_previous_runs_url if archive else (
                    settings.open_meteo_weather_url if live else settings.open_meteo_historical_weather_url)
                params.update(hourly=','.join(fields.values()), temperature_unit='celsius', wind_speed_unit='kmh', precipitation_unit='mm')
                if live:
                    params.update(daily=','.join(wx.DAILY_FIELDS), timezone=location.timezone)
                payload = await wx._fetch_json(url, params, settings)
                requests += 1
                count, changed = wx.persist_hourly_weather(db, location, payload, run, source_name=dataset,
                    source_url=wx.PREVIOUS_RUNS_SOURCE_URL if archive else (wx.WEATHER_SOURCE_URL if live else wx.HISTORICAL_WEATHER_SOURCE_URL),
                    field_map=fields, forecast_lead_hours=24 if archive else 0, archived=archive,
                    source_type_override='historical_modeled' if dataset == wx.HISTORICAL_WEATHER_SOURCE else None)
                if live:
                    wx.persist_daily_weather(db, location, payload)
                inserted += count; updated += changed
                wx._finish_success(db, run)
            # A successful response may contain null hours. Keep that absence explicit
            # and don't hammer the provider; reconsider incomplete dates after a week.
            times = {aq.aware_utc(t) for t in stored_times(db, location, dataset)}
            for day in days_between(first, last):
                complete = len({t.hour for t in times if t.date() == day}) == 24
                mark(db, location, dataset, day, day, 'checked' if complete else 'provider_partial',
                    None if complete or day >= (aq.utc_now()-timedelta(days=2)).date() else
                    aq.utc_now()+timedelta(days=settings.unavailable_retry_days))
        except Exception as exc:
            wx._finish_failure(db, run.id, exc)
            mark(db, location, dataset, first, last, 'failed', aq.utc_now()+timedelta(minutes=30))
            raise RuntimeError(f'{dataset}: {type(exc).__name__}') from None
    return {'status': 'success' if requests else 'cached', 'inserted': inserted, 'updated': updated, 'requests': requests}


async def sync_physical(db, location, days, settings):
    from app.services.sensor_history import synchronize_sensor_history
    from app.services.sensor_measurements import FHMZ_PRIMARY_STATIONS, OPENAQ_STATIONS, FHMZ_PROVIDER
    configured = FHMZ_PRIMARY_STATIONS.get(location.slug) if location.slug in ('zenica', 'mostar') else None
    ids = [str(configured[0])] if configured else [str(i) for i in OPENAQ_STATIONS.get(location.slug, ())]
    station = db.scalar(select(SensorStation).where(SensorStation.location_id == location.id,
        SensorStation.external_id.in_(ids), SensorStation.provider == FHMZ_PROVIDER if configured else SensorStation.provider.like('OpenAQ /%')))
    dataset = f'sensor:{station.id}' if station else f'sensor-pending:{location.slug}'
    today = aq.utc_now().date()
    # Before first station metadata is stored, no stored series exists to adopt.
    if station:
        ranges = missing_ranges(db, location, dataset, today-timedelta(days=days), today,
            recent_hours=settings.sync_revision_hours, ttl_minutes=60)
    else:
        marker = db.get(DataCoverage, f'{location.id}:{dataset}:{today}')
        if marker and marker.retry_after and aq.aware_utc(marker.retry_after) > aq.utc_now():
            return {'status': 'unavailable'}
        ranges = [(today-timedelta(days=days), today)]
    results = []
    for first, last in ranges:
        end = min(aq.utc_now(), datetime.combine(last+timedelta(days=1), datetime.min.time(), UTC))
        result = await synchronize_sensor_history(db, location, days=(last-first).days+1, force=True,
            start=datetime.combine(first, datetime.min.time(), UTC), end=end, settings=settings)
        if result['status'] == 'failed':
            mark(db, location, dataset, first, last, 'failed', aq.utc_now()+timedelta(minutes=30))
            raise RuntimeError('Physical history provider failed')
        if not station:
            station = db.scalar(select(SensorStation).where(SensorStation.location_id == location.id,
                SensorStation.external_id.in_(ids)))
            if station:
                dataset = f'sensor:{station.id}'
        mark(db, location, dataset, first, last, 'checked' if result['status'] == 'success' else 'unavailable',
            None if result['status'] == 'success' else aq.utc_now()+timedelta(days=settings.unavailable_retry_days))
        results.append(result)
    return {'status': 'success' if results else 'cached', 'ranges': len(results), 'results': results}


async def sync_city_stage(db, location, days):
    from app.services.sensor_measurements import synchronize_sensor_location
    settings = get_settings()
    today = aq.utc_now().date()
    first = today - timedelta(days=days)
    outcomes = {}
    # Failures in one source never discard the other sources' committed records.
    tasks = [
        ('physical', lambda: sync_physical(db, location, days, settings)),
        ('cams', lambda: sync_dataset(db, location, aq.SOURCE_NAME, first, today+timedelta(days=6), settings, live=True)),
        ('weather', lambda: sync_dataset(db, location, wx.LIVE_WEATHER_SOURCE, max(first, today-timedelta(days=6)), today+timedelta(days=6), settings, live=True)),
        ('archive', lambda: sync_dataset(db, location, wx.ARCHIVED_WEATHER_SOURCE, first, today, settings)),
        ('reanalysis', lambda: sync_dataset(db, location, wx.HISTORICAL_WEATHER_SOURCE, first, today-timedelta(days=7), settings)),
    ]
    if days == 1 or days == 90:
        try:
            outcomes['current_sensor'] = (await synchronize_sensor_location(db, location)).status
        except Exception as exc:
            db.rollback(); outcomes['current_sensor'] = type(exc).__name__
    for name, action in tasks:
        try:
            outcomes[name] = await action()
        except Exception as exc:
            db.rollback(); outcomes[name] = {'status': 'failed', 'error': type(exc).__name__}
    return {'days_checked': days, 'sources': outcomes}
