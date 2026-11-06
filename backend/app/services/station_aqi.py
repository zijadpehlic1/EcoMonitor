"""FHMZ 2024/EEA six-category hourly index for a single station and valid hour.

https://www.fhmzbih.gov.ba/latinica/ZRAK/AQI-metodologija.php
https://www.fhmzbih.gov.ba/latinica/ZRAK/AQI-efekti.php
"""
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

LIMITS = {
    'pm2_5': (5, 15, 50, 90, 140),
    'pm10': (15, 45, 120, 195, 270),
    'ozone': (60, 100, 120, 160, 180),
    'nitrogen_dioxide': (10, 25, 60, 100, 150),
    'sulphur_dioxide': (20, 40, 125, 190, 275),
}
LABELS = ('Odličan', 'Dobar', 'Umjeren', 'Zagađen', 'Vrlo zagađen', 'Izuzetno zagađen')
GENERAL = (
    'Uobičajene aktivnosti na otvorenom.', 'Uobičajene aktivnosti na otvorenom.',
    'Uobičajene aktivnosti na otvorenom.',
    'Razmotrite smanjenje intenzivnih aktivnosti na otvorenom ako primijetite simptome.',
    'Razmotrite smanjenje intenzivnih aktivnosti na otvorenom ako osjetite simptome.',
    'Smanjite fizičke aktivnosti na otvorenom.',
)
SENSITIVE = (
    'Uobičajene aktivnosti na otvorenom.', 'Uobičajene aktivnosti na otvorenom.',
    'Razmotrite smanjenje intenzivnih aktivnosti na otvorenom ako osjetite simptome.',
    'Razmotrite smanjenje fizičkih aktivnosti na otvorenom, posebno ako osjetite simptome.',
    'Smanjite fizičke aktivnosti, posebno na otvorenom, ako osjetite simptome.',
    'Izbjegavajte fizičke aktivnosti na otvorenom.',
)


@dataclass(frozen=True)
class Category:
    level: int | None
    label: str | None
    complete: bool
    limiting_pollutant: str | None
    available_pollutants: tuple[str, ...]


def classify(measurements, station_type: str | None) -> Category:
    """Inputs are already restricted to the same station and exact UTC valid hour."""
    levels = {}
    for row in measurements:
        if (row.pollutant in LIMITS and row.unit == 'μg/m³'
                and row.validation_status in ('unvalidated', 'validated')
                and isfinite(row.value) and row.value >= 0):
            levels[row.pollutant] = 1 + sum(row.value > threshold for threshold in LIMITS[row.pollutant])
    if not levels:
        return Category(None, None, False, None, ())
    has_pm = 'pm2_5' in levels or 'pm10' in levels
    kind = (station_type or '').lower()
    if 'saobra' in kind or 'traffic' in kind:
        complete = has_pm and 'nitrogen_dioxide' in levels
    elif 'pozad' in kind or 'industr' in kind or 'background' in kind or 'industrial' in kind:
        complete = has_pm and 'nitrogen_dioxide' in levels and 'ozone' in levels
    else:
        # Unknown type: require the union of traffic and background minima.
        complete = has_pm and 'nitrogen_dioxide' in levels and 'ozone' in levels
    limiting = max(levels, key=levels.get)
    worst = levels[limiting]
    # FHMZ: incomplete stations have no low/moderate category; severe
    # concentrations remain reportable even with incomplete coverage.
    if not complete and worst < 5:
        return Category(None, None, False, limiting, tuple(sorted(levels)))
    return Category(worst, LABELS[worst-1], complete, limiting, tuple(sorted(levels)))


def freshness(measured_at: datetime | None, now: datetime, local_today) -> tuple[str, int | None]:
    if measured_at is None or measured_at > now:
        return 'unavailable', None
    age = max(0, int((now-measured_at).total_seconds() / 60))
    if measured_at.astimezone(local_today.tzinfo).date() != local_today.date() or age > 180:
        return 'stale', age
    return ('current' if age <= 90 else 'recent'), age
