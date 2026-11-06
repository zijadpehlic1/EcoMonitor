# EcoMonitor

The selected physical station now has a provisional **FHMZ/EEA six-level hourly air-quality category** derived from one valid station/hour, using the published pollutant limits, worst-pollutant rule and station-type completeness checks. Automatic, not finally validated data is allowed and labeled provisional. Incomplete low/moderate snapshots receive no reassuring category; severe incomplete levels are flagged. Historical categories retain their timestamp and age and do not drive today's health advice. OpenAQ station type is treated as unknown unless verified, so conservative completeness applies. CAMS remains a separate regional modeled AQI. Methodology and actual station availability are recorded in [AUDIT.md](AUDIT.md).

EcoMonitor is a working academic environmental monitoring application for **“Primjena informacionih tehnologija u zaštiti okoliša”**. It supports Zenica, Sarajevo, Mostar and Banja Luka, with separate physical measurements, CAMS estimates, weather and station-specific PM2.5 forecasts. It is a thesis prototype, not a validated public-health or production monitoring service. See the dated audit for tested scope and limitations.

> **Data integrity:** Open-Meteo air-quality values come from CAMS atmospheric models. They are regional modeled estimates—not measurements from a physical sensor in Zenica. EcoMonitor preserves this distinction throughout the database, API, and user interface and never invents missing measurements.

## Persistent loading and background execution (November 2026)

The API serves existing local records immediately. Startup launches two separate worker processes: one for synchronization and one for ML. NumPy is initialized on the ML process main thread before threaded execution, avoiding a Windows/Python 3.14 native-import hang observed during testing. The API does not import scikit-learn or run model training in a request handler.

- **Durable queue:** `background_jobs` has unique job identities, atomic claims, renewable 90-second database leases, priorities and retry times. A separate leader lease elects one worker of each kind even with multiple API processes/reloaders. A crash is recoverable after lease expiry. Graceful shutdown signals workers through stdin, permits 30 seconds to finish, then terminates remaining processes; committed intervals and results survive. SQLite uses WAL and a 30-second busy timeout. PostgreSQL remains supported by SQLAlchemy and dialect-specific upserts, but was not integration-tested in this run.
- **Initial priority:** Zenica → Sarajevo → Mostar → Banja Luka, with 1 → 7 → 30 → 90-day stages inside each city. Selecting a city can promote its already queued initial stage; it does not create an external refresh. Provider date granularity means the 24-hour stage may span two calendar dates, and future operational weather/CAMS forecasts are also refreshed. The chart still displays the selected exact lookback and sample counts.
- **Persistent interval ledger:** `data_coverage` tracks each city/dataset/UTC date. Source names distinguish CAMS, operational weather, reanalysis and Previous Runs; physical keys include the verified station ID. Already stored full UTC days are adopted; missing/partial dates are requested in adjacent batches of at most seven days. Each later stage requests only its missing extension. Daily provider endpoints necessarily return some existing hours when repairing a partial date. A checked date is **not** a claim of complete measurements.
- **Refresh policy:** recent operational data uses `SYNC_INTERVAL_MINUTES` (default 30); physical history uses a 60-minute recent check; archived weather uses `WEATHER_HISTORY_SYNC_HOURS` (default 24). `SYNC_REVISION_HOURS=48` defines the small recent revision window. Old partial/empty meteorological responses are reconsidered after `UNAVAILABLE_RETRY_DAYS=7`; failed intervals wait 30 minutes. Unavailable physical endpoints are also recorded. Successful historical physical responses, including missing hours, remain checked; recent overlap captures delayed values. Failed outer jobs use bounded exponential backoff. No historical records are removed.
- **Manual refresh:** existing POST refresh endpoints now return `queued` or `cached` promptly. They schedule the deduplicated city job and respect provider freshness; `force` no longer means downloading all 90 days. Read `/api/v1/sync/status?location=mostar` for stage, source failures, revision and coverage. Background work continues with the browser closed. `/sensors/history/refresh?days=...` retains a bounded 1–366-day physical-only import scope.
- **Frontend:** exact URL keys isolate city, station, source, range, grouping and aggregation. Concurrent identical GETs share a promise. In-memory caching plus bounded-size localStorage entries retain small responses across reloads; large hourly arrays remain in memory and are always persisted in the backend database. GET data TTL is five minutes; job/ML polling has a short TTL. Existing same-dataset charts and metrics remain visible while refreshing or on network errors. A source/city mismatch is never rendered as the newly selected dataset. Background revision changes invalidate only that city's responses. Status polling is 30 seconds; settled ML checks are five minutes and ordinary data polling remains 15 minutes.

### Persisted ML artifacts

`model_artifacts` stores JSON numeric tree arrays, a checksum, algorithm/scikit-learn version, training-data fingerprint and frozen evaluation JSON. No pickle, joblib file, uploaded model or executable deserialization is used. `model_results` separately stores generated forecast responses and input fingerprints. The forest's JSON inference uses float32 input comparisons, matching scikit-learn tree behavior in tests. `model_executions` records actual completed computation duration and whether training/evaluation occurred; counts start when this instrumentation was introduced and do not invent historical counts.

The existing chronological 80/20, recursive 24-step, matched-origin comparison and persistence baseline are unchanged. Historical evaluation and the final production fit are saved as one consistent version; future inference reuses that version independently. New pollution/operational-weather inputs can regenerate a forecast without retraining or repeating the historical backtest. Unchanged inputs reuse the existing response across process restarts. Retraining requires both `ML_RETRAIN_HOURS=24` elapsed and `ML_MIN_NEW_SAMPLES=24` new valid raw PM2.5 samples, or a correction/removal in the previously used pollution/archive prefix, an algorithm/version change, or explicit `POST /api/v1/forecast/retrain?location=...&source=sensor&station_id=...`. A new model's old evaluation metrics remain visible until its replacement commits; displayed test dates identify their actual period. Insufficient/stale inputs produce informative states; no unverified improvement is asserted.

`/forecast/pm25` and `/forecast/pm25/weather-comparison` now return saved results or `status=pending`, with `computation_status` (`queued`, `running`, `done`). They enqueue only local computation, never provider downloads. The calculation worker checks fingerprints before doing expensive work. Model tasks are deduplicated; one ML process with single-thread forests protects normal API responsiveness.

### Source selection and provenance

The bottom provenance card follows the **same city/source/station selection as history and ML**. Physical mode reports provider, station, latest stored timestamp, validation counts and pollutant-time record count for that station only. CAMS mode retains its modeled explanation and CAMS-only row count. Newly received CAMS grid coordinates are persisted in `source_metadata`; if absent in legacy records, the interface explicitly labels coordinates as the **query location**, not a verified grid cell. AQI/health guidance and modeled pollutant cards remain CAMS; weather and the temperature overlay remain Open-Meteo models/reanalysis. These simultaneous sources are explicitly identified. UI theme, layout, filters, localization and ports are preserved.

### Reproducible optimization checks

From `backend`, with the server running:

```powershell
.\.venv\Scripts\python.exe scripts/measure_loading.py
.\.venv\Scripts\python.exe scripts/measure_model_reuse.py --city mostar --regenerate
.\.venv\Scripts\python.exe scripts/measure_model_reuse.py --city mostar
```

The second command expires only a derived forecast-response identity to measure inference with retained models/evaluations. It refuses an actively running job for that model. The third runs in a fresh process and measures persisted reuse. Read the resulting JSON rather than assuming a speedup. `scripts/sync_all.py` and ordinary historical-import CLI calls enqueue durable jobs; start the backend to execute them. An explicit `--end` historical research replay requires the sync worker to be stopped. Use an offline snapshot for reproducible scientific evaluation.

Actual local verification on 5 November 2026 UTC: **57 backend tests, 23 frontend tests and the production build passed**. After backend restart, three-request medians across four cities were **8.82–10.54 ms** for dashboard responses, **10.04–13.78 ms** for 24-hour physical history and **6.19–7.37 ms** for stored ML/evaluation responses. Actual Mostar model reuse and forecast regeneration both made **zero RF fit calls**; regeneration took **739.04 ms** (PM2.5-only) and **867.84 ms** (weather-aware). A prior required training/evaluation took 18.98 s and 28.01 s respectively. Raw JSON reports and the distinctions between response delivery, inference and training are documented in `AUDIT.md`. These are local observations, not controlled legacy-baseline, load or energy benchmarks. Immediate repeat ingestion checks made zero additional provider requests after bounded CAMS/weather/FHMZ refreshes.

New tables are additive (`create_all`); existing measurements are neither reset nor deleted. Back up the SQLite database with SQLite's backup API (or PostgreSQL with `pg_dump`) before deploying changes. There is no general migration framework yet. Single-machine clock agreement is assumed for leases; multi-host failover, automated worker supervision and large-scale load testing remain future work. API auth/rate limiting and FHMZ redistribution permission remain necessary before public deployment. No energy or carbon savings are claimed.

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

`sensor_history.py` imports OpenAQ `/sensors/{id}/hours` with pagination, units, coverage/quality flags and licence metadata. `fhmz_history.py` imports the public portal's `/rest/aqdata/data` using `aqdata_type=0` (hourly source data), after checking station metadata. The background queue progressively checks 1, 7, 30 and 90 days and reuses the persistent interval ledger. Small recent overlap captures delayed/revised values; ordinary refresh never forces the full historical range. Neither importer invents missing hours. Imports fail atomically and do not advance a success checkpoint after a failed page/request.

Both providers label physical hours by interval **end**. This timestamp remains in UTC for ML alignment; for daily charts midnight-ending measurements belong to the preceding Sarajevo day. FHMZ local timestamps lack offsets: ambiguous/nonexistent DST times are skipped, not guessed. Negative/nonfinite values are rejected. Provider-flagged or incomplete OpenAQ hours remain stored with metadata but are excluded from charts and ML. Every physical series uses exactly one station.

Run from `backend` to enqueue historical work (the running backend executes it):

```powershell
.\.venv\Scripts\python.exe scripts/import_sensor_history.py --city zenica --days 92
.\.venv\Scripts\python.exe scripts/import_sensor_history.py --city sarajevo --days 92
.\.venv\Scripts\python.exe scripts/import_sensor_history.py --city mostar --days 92
.\.venv\Scripts\python.exe scripts/import_sensor_history.py --city banja-luka --days 92
```

FHMZ public academic access was verified, but no explicit redistribution licence was established. Preserve attribution and obtain permission before republishing a historical dataset or deploying commercially. OpenAQ station licence metadata is retained (AirNow: US Public Domain; EEA: ODC-BY).

## Quick start (Windows PowerShell)

The default configuration uses SQLite and requires no external database or queue service. Provider synchronization requires internet connectivity.

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
    API -->|enqueue / read cached result| Q[Durable jobs and model results]
    Q --> BG[Separate sync worker]
    Q --> MW[Separate ML worker]
    MW --> ML[Training / evaluation / inference]
    BG --> IN[Incremental Open-Meteo adapters]
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
| `sync_runs` | Provider sync-run audit, row counts and failures | Indexed source; linked location |
| `background_jobs` | Durable queue, priorities, leases, retry times and latest result | Unique job key |
| `data_coverage` | Per-city/source/station UTC-date checks and retry states | Unique dataset/date key; indexed location/source |
| `model_artifacts` | JSON forest, versioned input fingerprint and evaluation | Unique city/source/station/model key |
| `model_results` | Latest completed forecast response and input version | Unique model/horizon key |
| `model_executions` | Actual computation duration and training/evaluation flags | Indexed model key |
| `source_metadata` | Returned provider grid coordinates and units | Unique city/provider key |

Pollutant columns have a schema-level unit contract of `μg/m³`; European AQI is unitless. Units are validated when Open-Meteo supplies `hourly_units` and the REST response includes an explicit units map. Units are not repeated in every database row.

## Data flow and refresh behavior

1. Startup seeds city metadata and launches isolated sync/ML workers without awaiting downloads or fitting.
2. The durable queue checks cities and 1/7/30/90-day stages in the priority order documented above. The coverage planner requests missing date intervals and bounded recent revisions, preserving historical data.
3. Unix timestamps requested in GMT are normalized to UTC. Read-time classification distinguishes past/current estimates from future forecasts; past CAMS forecasts never become physical observations.
4. Identity constraints, indexed lookups, atomic metadata upserts and database job/leader leases prevent duplicate background work. Interval transactions preserve previously committed readings after failures.
5. React reads local data, caches exact dataset queries and polls job progress separately. A manual refresh enqueues work rather than synchronously downloading history or retraining.
6. The ML worker persists model/evaluation versions and generated responses; API reads return those immediately while replacements run. Failed provider intervals and job retries remain visible through progress metadata.


Weather follows the same identity and failure-handling pattern. The Weather Forecast API incrementally checks the recent operational window and up to seven forecast dates for `temperature_2m`, `relative_humidity_2m`, `wind_speed_10m`, `precipitation` and daily minimum/maximum/mean temperature. The Historical Weather API supplies the older portion of the configured 90-day staged chart window as model reanalysis. Past/current values are labeled **modeled** or **historical modeled**, future values **forecast**, and none are presented as a local weather-station observation. Daily values use `Europe/Sarajevo`; hourly Unix timestamps are normalized to UTC before joining air-quality rows. Historical weather and archived forecasts are separate datasets: reanalysis is used only for visualization, while leakage-safe ML evaluation continues to use Previous Runs data that was available at the historical prediction origin.

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
| POST | `/api/v1/refresh?location=zenica&force=false` | Enqueue deduplicated incremental city refresh |
| GET | `/api/v1/forecast/pm25?location=zenica&horizon=24` | Persisted forecast/hold-out metrics or pending state |
| GET | `/api/v1/weather?location=zenica` | Latest modeled weather, daily summary and next 24 forecast hours |
| POST | `/api/v1/weather/refresh?location=zenica&force=false` | Independently cache-aware operational, historical-reanalysis and archived-forecast weather synchronization |
| GET | `/api/v1/forecast/pm25/weather-comparison?location=zenica&horizon=24` | Matched PM2.5-only, weather-aware and persistence metrics plus weather-aware forecast |
| GET | `/api/v1/sensors/current?location=zenica` | Fresh/stale physical-station status and latest verified measurements |
| GET | `/api/v1/sensors/coverage` | Locally verified coverage state for all configured cities |
| POST | `/api/v1/sensors/refresh?location=zenica&force=false` | Cache-aware OpenAQ-first/FHMZ-fallback synchronization |
| GET | `/api/v1/sensors/stations?location=mostar` | Station identities, station-specific counts, validation distribution and attribution |
| POST | `/api/v1/sensors/history/refresh?location=mostar&days=90` | Enqueue incremental physical history check |
| GET | `/api/v1/sync/status?location=mostar` | Durable queue stage, failures, revision and checked dates |
| POST | `/api/v1/forecast/retrain?location=mostar&source=sensor&station_id=2` | Explicitly queue training/evaluation; keep existing results available |
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
- **Computation reuse:** durable JSON model/evaluation artifacts and independent forecast results distinguish city, station, source, horizon and input version. Queue identities coalesce repeated work, and unchanged inputs skip computation across restarts.
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

