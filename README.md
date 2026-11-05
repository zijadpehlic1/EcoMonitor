# EcoMonitor

EcoMonitor is a working academic environmental monitoring application for **“Primjena informacionih tehnologija u zaštiti okoliša”**. It supports Zenica, Sarajevo, Mostar and Banja Luka, with separate physical measurements, CAMS estimates, weather and station-specific PM2.5 forecasts. It is a thesis prototype, not a validated public-health or production monitoring service. See the dated audit for tested scope and limitations.

> **Data integrity:** Open-Meteo air-quality values come from CAMS atmospheric models. They are regional modeled estimates—not measurements from a physical sensor in Zenica. EcoMonitor preserves this distinction throughout the database, API, and user interface and never invents missing measurements.

## Technology stack

- FastAPI, SQLAlchemy 2, Pydantic and PostgreSQL/SQLite
- React, TypeScript, Vite, Tailwind CSS and Recharts
- scikit-learn random-forest autoregression
- REST communication with generated OpenAPI documentation

## Physical measurement priority

EcoMonitor now keeps physical-station measurements separate from CAMS modeled rows and displays a verified, fresh station panel before the modeled pollutant cards. A measurement is labeled **live** only when it comes from a stationary/reference monitor, carries a provider timestamp, uses the expected `μg/m³` unit and is no older than the configured three-hour freshness limit. Older values remain stored but are labeled stale and are not shown as live.

Source priority is:

1. Explicitly verified OpenAQ v3 stationary/reference station IDs when `OPENAQ_API_KEY` is configured and the API returns fresh timestamped readings. A nearby station in another municipality is never selected automatically.
2. The official FHMZ public station service for Federation of BiH cities where OpenAQ is missing, stale or unavailable.
3. No sensor claim. The interface continues showing CAMS modeled data with its existing disclaimer.

The API key is loaded as a Pydantic `SecretStr`, sent only in the `X-API-Key` request header and never returned by an endpoint or written to logs. Configure it in `backend/.env` as `OPENAQ_API_KEY=...`; do not commit that file.

The verified FHMZ fallback uses Zenica Brist, Sarajevo Bjelave and Mostar. Automatic source measurements remain `unvalidated`; a provider `Valid` flag on source data does not imply final validation. OpenAQ Sarajevo (9598, AirNow) is a different station from Bjelave. Lazarevo (6482140, EEA) is the Banja Luka source. OpenAQ Tetovo is discontinued and has no PM2.5; Mostar had no OpenAQ results on 5 November 2026. FHMZ CO is intentionally omitted; the portal identifies CO in mg/m³, unlike the other pollutants. OpenAQ CO is accepted only when explicitly supplied in μg/m³.

### Historical physical measurements

`sensor_history.py` imports OpenAQ `/sensors/{id}/hours` with pagination, units, coverage/quality flags and licence metadata. `fhmz_history.py` imports the public portal's `/rest/aqdata/data` using `aqdata_type=0` (hourly source data), after checking station metadata. Initial imports request 92 days; subsequent daily imports overlap the last 72 hours for delayed/revised values. `force=true` repeats the selected range. Neither importer invents missing hours. Imports fail atomically and do not advance a success checkpoint after a failed page/request.

Both providers label physical hours by interval **end**. This timestamp remains in UTC for ML alignment; for daily charts midnight-ending measurements belong to the preceding Sarajevo day. FHMZ local timestamps lack offsets: ambiguous/nonexistent DST times are skipped, not guessed. Negative/nonfinite values are rejected. Provider-flagged or incomplete OpenAQ hours remain stored with metadata but are excluded from charts and ML. Every physical series uses exactly one station.

Run from `backend` (the same cache-aware operation runs daily in the scheduler):

```powershell
.\.venv\Scripts\python.exe scripts/import_sensor_history.py --city zenica --days 92
.\.venv\Scripts\python.exe scripts/import_sensor_history.py --city sarajevo --days 92
.\.venv\Scripts\python.exe scripts/import_sensor_history.py --city mostar --days 92
.\.venv\Scripts\python.exe scripts/import_sensor_history.py --city banja-luka --days 92
```

FHMZ public academic access was verified, but no explicit redistribution licence was established. Preserve attribution and obtain permission before republishing a historical dataset or deploying commercially. OpenAQ station licence metadata is retained (AirNow: US Public Domain; EEA: ODC-BY).

## Quick start (Windows PowerShell)

The default configuration uses SQLite and requires no external services.

### 1. Backend

```powershell
cd C:\Users\zijad\Desktop\EcoMonitor\backend
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

The API starts at `http://127.0.0.1:8001`; interactive API documentation is at `http://127.0.0.1:8001/docs`.

### 2. Frontend (second PowerShell window)

```powershell
cd C:\Users\zijad\Desktop\EcoMonitor\frontend
npm.cmd install
npm.cmd run dev
```

Open `http://localhost:5174`. Vite proxies `/api` to the local backend.

## PostgreSQL option

Start the included local database:

```powershell
cd C:\Users\zijad\Desktop\EcoMonitor
docker compose up -d postgres
```

If `backend/.env` is absent, copy `backend/.env.example` to it. Otherwise edit the existing file, preserving the configured OpenAQ key, and set:

```dotenv
DATABASE_URL=postgresql+psycopg://ecomonitor:ecomonitor_local@localhost:5432/ecomonitor
```

SQLAlchemy creates the schema on application startup. SQLite remains the zero-configuration fallback.

## Architecture

```mermaid
flowchart LR
    UI[React dashboard] -->|REST /api/v1| API[FastAPI routes]
    API --> DS[Dashboard service]
    API --> ML[PM2.5-only and weather-aware ML services]
    BG[Background sync] --> IN[Open-Meteo ingestion adapters]
    BG --> SI[OpenAQ / FHMZ adapters]
    SI -->|hourly current + daily historical import| DB
    API --> HS[History / station-scoped dataset service]
    HS --> DB
    IN -->|30 min cache| AQ[Air Quality and Weather Forecast APIs]
    IN -->|24 h cache| HW[Historical Weather API]
    IN -->|24 h cache| PR[Previous Runs weather API]
    IN --> DB[(PostgreSQL or SQLite)]
    DS --> DB
    ML --> DB
```

The backend is layered into API routes, application services, SQLAlchemy persistence, configuration, and schemas. The frontend separates transport types, API access, reusable charts, forecast presentation, and the dashboard shell.

## Database schema

| Table | Purpose | Important constraints |
|---|---|---|
| `locations` | Geographic monitoring points and timezone metadata | Unique `slug` |
| `air_quality_readings` | Hourly pollutant/AQI values plus source, model, forecast flag and ingestion time | Unique `(location_id, measured_at, source_name)`; indexed location/time |
| `weather_readings` | Hourly temperature, humidity, wind and precipitation with valid time, source type and forecast lead | Unique `(location_id, measured_at, source_name, forecast_lead_hours)`; indexed location/time |
| `daily_weather_summaries` | Daily minimum, maximum and mean temperature | Unique `(location_id, date, source_name)` |
| `sensor_stations` | Verified provider/station identity, attribution, reference-monitor status and last measurement time | Unique `(provider, external_id)` |
| `sensor_measurements` | Timestamped physical measurements with pollutant, value, unit and validation status | Unique `(station_id, measured_at, pollutant)` |
| `sensor_import_states` | Public station/licence metadata, last successful import and imported window | Primary key/FK `station_id` |
| `sensor_measurement_metadata` | Instrument ID, period boundaries, coverage and provider flags | Primary key/FK `measurement_id` |
| `sync_runs` | Provider request audit, duration metadata, row counts and failures | Indexed source; linked location |

Pollutant columns have a schema-level unit contract of `μg/m³`; European AQI is unitless. Units are validated when Open-Meteo supplies `hourly_units` and the REST response includes an explicit units map. Units are not repeated in every database row.

## Data flow and refresh behavior

1. Startup seeds all four cities and launches an asynchronous synchronization loop. Every city receives air, weather and sensor refreshes; individual provider failures are isolated. Database work remains synchronous, so this is a single-process development scheduler, not a distributed job system.
2. The ingestion service calls the Open-Meteo Air Quality endpoint for up to 92 past days and seven forecast days. Open-Meteo describes `past_days` as archived model forecasts; these are not station observations.
3. Unix timestamps requested in GMT are normalized to timezone-aware UTC. Provider values, source type (`modeled`), model name and the ingestion-time forecast flag are persisted. API reads classify historical versus future data from valid time, so an old forecast becomes historical modeled data after its valid time passes.
4. A database uniqueness constraint and range lookup prevent duplicate rows. Changed provider values update the existing row. An in-process synchronization lock prevents the background task and a manual refresh racing in the normal single-process deployment.
5. Successful syncs are cached for 30 minutes. The dashboard polls its compact aggregate endpoint every 15 minutes without forcing an upstream request.
6. Provider failures are recorded and stored readings remain queryable.

Weather follows the same identity and failure-handling pattern. The Weather Forecast API retrieves seven past and seven future days for `temperature_2m`, `relative_humidity_2m`, `wind_speed_10m`, `precipitation` and daily minimum/maximum/mean temperature. The Historical Weather API supplies the older portion of the configured 92-day chart window as model reanalysis. Past/current values are labeled **modeled** or **historical modeled**, future values **forecast**, and none are presented as a local weather-station observation. Daily values use `Europe/Sarajevo`; hourly Unix timestamps are normalized to UTC before joining air-quality rows. Historical weather and archived forecasts are separate datasets: reanalysis is used only for visualization, while leakage-safe ML evaluation continues to use Previous Runs data that was available at the historical prediction origin.

The historical chart uses `/history`. The source/station selector also controls both ML panels and defaults to physical measurements. CAMS and physical data are never merged. Daily averages/maxima operate on hourly means, independently per pollutant/temperature, with 23/24/25 expected hours according to Sarajevo DST. Null buckets explicitly break lines across gaps. The tooltip retains sample counts and peak times. The first/last day of a rolling range can be partial. Daily values are descriptive, not regulatory compliance statistics.

Historical ML evaluation separately retrieves Open-Meteo Previous Runs fields ending in `_previous_day1`. A value valid at `t` was predicted 24 hours earlier, so it was available no later than the PM2.5 prediction origin. These rows are stored as `source_type="archived_forecast"` with `forecast_lead_hours=24`. The archive is refreshed at most once every 24 hours, while operational weather uses the standard 30-minute cache. Missing fields remain `NULL`; no interpolation or fabricated measurement is introduced.

`datasets.py` is the common source/station isolation boundary for charts and both ML models. CAMS queries require the exact source name and `modeled` classification; physical queries require a station belonging to the selected city and acceptable quality/units.

## REST endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/health` | Service health |
| GET | `/api/v1/locations` | Supported locations |
| GET | `/api/v1/dashboard?location=zenica&hours=24` | Latest reading, history, units, source and sync metadata in one request |
| GET | `/api/v1/history?location=zenica&hours=720&grouping=daily&aggregation=maximum` | Backend-aligned pollution/temperature history with sample counts and peak timestamps |
| POST | `/api/v1/refresh?location=zenica&force=false` | Cache-aware manual ingestion |
| GET | `/api/v1/forecast/pm25?location=zenica&horizon=24` | ML forecast and chronological hold-out metrics |
| GET | `/api/v1/weather?location=zenica` | Latest modeled weather, daily summary and next 24 forecast hours |
| POST | `/api/v1/weather/refresh?location=zenica&force=false` | Independently cache-aware operational, historical-reanalysis and archived-forecast weather synchronization |
| GET | `/api/v1/forecast/pm25/weather-comparison?location=zenica&horizon=24` | Matched PM2.5-only, weather-aware and persistence metrics plus weather-aware forecast |
| GET | `/api/v1/sensors/current?location=zenica` | Fresh/stale physical-station status and latest verified measurements |
| GET | `/api/v1/sensors/coverage` | Locally verified coverage state for all configured cities |
| POST | `/api/v1/sensors/refresh?location=zenica&force=false` | Cache-aware OpenAQ-first/FHMZ-fallback synchronization |
| GET | `/api/v1/sustainability/metrics` | Measurable storage/request-efficiency indicators |

All responses include `X-Process-Time-Ms` for reproducible server-side latency measurements.

## Machine-learning methodology

The model predicts future hourly PM2.5 using only previously available PM2.5 values and calendar information:

- lag 1, 3-hour mean, 6-hour mean, lag 24 and 24-hour mean;
- cyclical hour-of-day and weekday features;
- random forest with fixed seed (`random_state=42`);
- first 80% of engineered samples for training and the final 20% reserved for evaluation;
- no random shuffling and no evaluation-time refitting, so later observations never enter the training fit;
- non-overlapping rolling origins in the hold-out segment, each evaluated as a complete 24-step recursive forecast;
- a matched 24-hour persistence baseline that repeats the value available at each origin across all 24 steps;
- MAE and RMSE over the same forecast-target pairs for both model and baseline;
- recursive 24-hour prediction after retraining on all available history.

The standalone model requires 336 valid raw hours and 200 continuous engineered samples; the aligned comparison requires 200 engineered samples and complete 24-hour test windows. Every adjacent lag/test timestamp must differ by exactly one hour. Calendar features use Sarajevo local time. Outputs identify city, source, station and training provenance. `source=modeled` predicts CAMS estimates; `source=sensor&station_id=...` trains only on that station's physical observations. No model silently falls back to CAMS. Historical evaluation may remain available when the newest lag window is incomplete/stale; operational predictions then remain empty. Only still-future points from the 24-hour origin horizon are displayed, so delayed measurements can leave fewer than 24 points.

### Weather-aware model and fair comparison

The second Random Forest preserves the original autoregressive implementation and adds hourly temperature, 10 m wind speed, relative humidity, precipitation, and sine/cosine day-of-year seasonality. Training samples require an exact UTC timestamp match between PM2.5 and all four archived forecast weather fields. Future operational PM2.5 predictions use current Open-Meteo weather forecast variables, never a fabricated weather value.

The PM2.5-only model, weather-aware model, and persistence baseline are fitted and evaluated over the same aligned dataset. They use one chronological 80/20 split, identical non-overlapping origins, identical 24-step recursive targets, and identical MAE/RMSE pairs. If archived forecasts or a complete 24-hour evaluation window are unavailable, the endpoint returns `insufficient_data` and does not report a comparison using future observations or reanalysis.

Methodological limitation: `_previous_day1` gives each target hour's forecast made exactly 24 hours earlier. Every input was available by its PM2.5 origin, preventing look-ahead leakage, but the 1–24 hour inputs are not a single coherent model run issued at that origin. This is a leakage-safe operational approximation, not a perfect archived-run replay. The frontend states improvement only when the returned MAE is actually lower; a negative result is shown as no improvement.

The common comparison endpoint also returns `by_horizon` MAE/RMSE for steps 1–24. Compare the three scores **within that response**, not against the standalone endpoint if weather missingness changes its training/test period. Publication latency and retrospective revisions of historical pollution are not replayed; this remains a retrospective concentration-forecast experiment. One season and one split cannot establish general or annual accuracy. API horizons 6–72 remain compatible, but measured evaluation is explicitly 24 steps only; the UI requests 24.

## Green software engineering

EcoMonitor applies and exposes measurable techniques:

- **Request reduction:** separate provider refreshes use 30-minute caches. One synchronization can involve multiple HTTP calls; this is not one total request per city.
- **Tiered weather cache:** frequently changing operational weather uses 30 minutes; historical reanalysis and archived previous-run history use 24 hours.
- **Sensor request reduction:** physical-source discovery/refresh is cached for 30 minutes and only one preferred station per city is ingested.
- **Client efficiency:** a single dashboard endpoint replaces multiple pollutant requests; background polling is every 15 minutes.
- **Storage efficiency:** one wide hourly row stores all pollutants; duplicate keys update in place.
- **Query efficiency:** composite location/time and forecast indexes support the primary range queries.
- **Computation reuse:** bounded 16-entry caches distinguish city, source, station, horizon, pollution content hash and ingestion metadata; weather changes also invalidate the comparison. Concurrent duplicate training is not yet coalesced.
- **Payload discipline:** charts request only the selected range; the default is 24 hours.

Measure the running application with:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/v1/sustainability/metrics
(Invoke-WebRequest http://127.0.0.1:8001/api/v1/dashboard?hours=24).Headers['X-Process-Time-Ms']
```

The metrics endpoint reports successful/failed **sync runs**, received/inserted/refreshed rows, cache policy and polling frequency. Legacy `*_provider_requests` fields are retained for compatibility but count sync runs, not actual HTTP calls. Historical import responses separately expose request counts. Cache skips are not persisted, so avoided calls are not directly measured. No energy or carbon emissions are claimed.

## Testing and reproducible verification

```powershell
cd C:\Users\zijad\Desktop\EcoMonitor\backend
.\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm.cmd test
npm.cmd run build
```

The tests verify duplicate-safe air/weather/sensor ingestion and provenance, UTC and forecast classification, sensor freshness, OpenAQ reference-monitor filtering, FHMZ parsing, provider unit validation, missing-weather handling, cache freshness, matched 24-hour recursive ML evaluation, refusal of observation fallback, metric arithmetic, AQI bands, and API health/performance headers. To reproduce a live model evaluation, start the backend, wait for the first sync, then request:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8001/api/v1/forecast/pm25?location=zenica&horizon=24'
Invoke-RestMethod 'http://127.0.0.1:8001/api/v1/forecast/pm25/weather-comparison?location=zenica&horizon=24'
```

Record the dataset timestamps, sample counts, MAE, RMSE and baseline values returned by that call. Results will vary as the upstream modeled history evolves; the system intentionally makes no hard-coded accuracy claim.

## Thesis implementation notes

The implementation demonstrates REST integration, source-specific time-series storage, visualization, supervised forecasting, chronological evaluation and measurable payload reduction for all four cities. Local SQLite behavior is tested; PostgreSQL migrations, concurrency/load testing, publication permissions, distributed scheduling and a frozen multi-season experiment remain necessary before production or strong thesis accuracy claims. IoT/MQTT is a future adapter boundary, not an implemented hardware feature.

### Added REST contracts and repeatable experiments

- `GET /api/v1/sensors/stations?location=zenica` lists stored stations, coordinates, attribution and actual coverage range/count.
- `POST /api/v1/sensors/history/refresh?location=zenica&days=92&force=false` performs the bounded, cache-aware import.
- `/history`, `/forecast/pm25`, `/forecast/pm25/weather-comparison` accept `source=modeled` (backward-compatible default) or `source=sensor&station_id=<id>`. A city/station mismatch returns 422.

```powershell
cd C:\Users\zijad\Desktop\EcoMonitor\backend
.\.venv\Scripts\python.exe scripts/verify_sources.py
.\.venv\Scripts\python.exe scripts/sync_all.py
.\.venv\Scripts\python.exe scripts/evaluate_models.py
# With the backend running:
.\.venv\Scripts\python.exe scripts/smoke_api.py
```

Evaluation writes `audit-evaluation.json` with real scores, periods, sample counts, PM2.5 hashes, dependency versions and elapsed times. An optional `--city banja-luka` writes a separate report. Snapshot the SQLite database with the server stopped before a thesis experiment; hash that snapshot and retain the source revision/package lock. PM2.5 hashes alone do not freeze weather. Do not repeatedly re-run against changed upstream data and report it as the same experiment. `audit-api-smoke.json` records observed latency and payload size, not a controlled load/energy benchmark.

See [AUDIT.md](AUDIT.md) for the correctness review, fixed issues, evidence, remaining limitations and recommended next thesis phase.

### External attribution

Air-quality forecasts and reanalysis are supplied through [Open-Meteo’s Air Quality API](https://open-meteo.com/en/docs/air-quality-api) using the Copernicus Atmosphere Monitoring Service (CAMS) European ensemble. Follow the provider’s current attribution and license terms in any published deployment or thesis appendix.

Operational meteorology is supplied through the [Open-Meteo Weather Forecast API](https://open-meteo.com/en/docs); chart history comes from the [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api), and leakage-safe historical predictor availability is approximated with the [Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api). Weather values are numerical weather-model output/reanalysis, not verified local-station measurements.

Physical measurements are accessed through [OpenAQ API v3](https://docs.openaq.org/api) when authenticated coverage is available and through the official [FHMZ air-quality portal](https://zrak.fhmzbih.gov.ba/) for the verified Federation of BiH fallback. Confirm redistribution/licensing requirements with FHMZ before a public commercial deployment; the current academic implementation performs low-frequency retrieval, preserves attribution and reproduces the provider's unvalidated-data warning.

