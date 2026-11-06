# EcoMonitor correctness and thesis-readiness audit

## Physical-station hourly category — 6 November 2026

The earlier physical hero suppressed the index solely because hourly observations were automatic and not finally validated. [FHMZ's published methodology](https://www.fhmzbih.gov.ba/latinica/ZRAK/AQI-metodologija.php) explicitly uses such hourly data, the worst of PM2.5, PM10, NO₂, O₃ and SO₂, and six **categories (1–6)** rather than a numeric 0–100 index. FHMZ also [publishes separate general and sensitive-group guidance](https://www.fhmzbih.gov.ba/latinica/ZRAK/AQI-efekti.php). Its [station index page](https://www.fhmzbih.gov.ba/latinica/ZRAK/AQI-satne.php) confirms an official category display, but the existing stored FHMZ history did not carry a timestamped, station-ID-matched official category. EcoMonitor therefore labels its result as **derived/provisional FHMZ/EEA hourly category**, not an official category fetched from FHMZ. No OpenAQ station-specific official AQI field was verified in stored metadata; OpenAQ concentrations use the same published European hourly thresholds as an application-derived category, never falsely attributed to OpenAQ as its own AQI.

The calculation uses only valid μg/m³ measurements from the selected station and **one exact UTC reporting hour**. It uses the published threshold boundaries and worst-pollutant rule. Traffic stations require NO₂ and PM; background/industrial stations require NO₂, O₃ and PM. With unknown station type, the conservative union of those requirements applies. FHMZ's incomplete-station restriction is preserved: levels 1–4 are withheld if the required pollutants are absent; a severe level 5–6 may be shown with an explicit incompleteness warning and without reassuring health guidance. FHMZ Brist and Mostar carry `Pozadinska` in stored official metadata. OpenAQ Sarajevo and Lazarevo have no confirmed station-type field, so the conservative completeness rule applies. Flagged measurements, wrong units and future valid times are excluded. A later incomplete low hour does not hide a valid older category; the response returns the older hour with its true age.

Freshness uses the Sarajevo calendar date: up to 90 minutes is current, 91–180 minutes is recent, and older or previous-day data is historical/stale. An older category may remain visible with its timestamp and age, but no current health recommendation is issued. Full general-public and sensitive-group advice is taken from the FHMZ category table only when the snapshot is complete and current/recent. CAMS retains a separately labeled modeled AQI. The circular station indicator shows **1–6**, not a fabricated 0–100 score.

At a local HTTP check shortly after 00:30 UTC on 6 November, Zenica Brist showed **3, Umjeren**, complete and **recent** (23:00 UTC, 93 minutes old); Mostar showed **2, Dobar**, complete but **stale** (22:00 UTC on the preceding Sarajevo date, 153 minutes old); Banja Luka Lazarevo showed **4, Zagađen**, complete but **stale** (21:00 UTC, 213 minutes old). Sarajevo AirNow had only PM2.5 in its recent hour, so a low/moderate category cannot be shown for that hour. The latest reportable historical severe snapshot was **6, Izuzetno zagađen**, **incomplete**, from **17 September 2026 12:00 UTC**; the UI must identify it as a historical category roughly 49 days old and suppress current health advice. These are stored-data results at one time, not claims of official provider-published categories. Provider updates can change them.

Verification: **61 backend tests**, **26 frontend tests** and the production Vite build passed. Focused tests cover official threshold boundaries, worst pollutant, unit/quality exclusion, station-type completeness, severe incomplete exceptions, one-hour alignment, future exclusion, historical fallback, Sarajevo date boundary, source switching, stale guidance and the independent CAMS indicator. The existing pytest-asyncio Python 3.14 deprecation warning and Vite bundle-size advisory remain.

---

## Main status and source consistency — 6 November 2026

The hero and health card previously read CAMS `dashboard.latest` regardless of the chart/ML source selector. `/sensors/current` independently selected the city's latest station, so its panel could differ from the selected station. The hero now follows the selected city, source and physical station. The current sensor endpoint accepts an optional validated station ID; physical station measurements remain separate from CAMS pollutant cards and weather. An unvalidated automatic sensor hour is never converted into a station AQI or AQI-based health advice: the required official averaging periods and validated inputs are not established. The hero explains this and labels an available CAMS European AQI as a separate modeled regional indicator. Modeled selection retains CAMS AQI guidance. Stale, absent and future-valid-time values do not receive a current AQI or health classification.

The apparent `06.11.2026. 00:00` on a `05.11` UK-date screenshot can be a legitimate Sarajevo local clock hour while UTC is still `05.11 23:00`; the hero now appends `Europe/Sarajevo` to its time. The backend dashboard already constrained `measured_at <= utc_now()`; the frontend adds a second valid-time guard. A stored forecast flag alone is not used to decide current status. Tests cover excluding a future CAMS hour and selecting physical station data by ID.

Verification for this change: **57 backend tests passed**, **25 frontend tests passed**, and the production Vite build passed. The existing Python 3.14 pytest-asyncio deprecation and Vite chunk-size advisories remain. This change makes no assertion that a scientifically valid station AQI has been calculated.

---

## Loading, persistence and provenance optimization — 5 November 2026 UTC

This section supersedes older descriptions of request-time ML, repeated full-window synchronization, process-only caches and the fixed CAMS provenance card. No measurement table was reset or historical dataset deleted. Changes are limited to the requested loading/execution/provenance architecture and its tests/documentation; the homepage theme/layout and scientific 24-step evaluation remain.

### Confirmed causes and corrections

| Cause | Correction |
|---|---|
| CAMS `past_days=92` was requested on each stale cache; historical weather/Previous Runs repeated their complete date range | Persistent date coverage, incremental bounded missing intervals, legacy full-day adoption and recent revision overlap |
| Only latest success controlled freshness; an empty old provider window had no durable record of being checked | Checked/partial/unavailable/failed coverage with retry times, separate from actual sample completeness |
| RF fitting, backtesting and prediction all ran inside GET handlers; cache was process memory and weather ingestion timestamps invalidated it repeatedly | Database-backed versioned JSON forests/evaluations, independent forecast results, input-content checks and separate ML worker process |
| City remounts discarded fetched responses; StrictMode duplicated concurrent GETs; non-live sensor loads POSTed to providers | Per-query frontend cache, shared in-flight promise, persistent small responses, read-only city switching and stale-data retention |
| Manual refresh forced all three providers and immediately called both ML calculations | One deduplicated queued city refresh respecting provider TTLs; affected-city response invalidation; independent model input check |
| Provenance card always read `dashboard.source` and city-wide modeled count | Selected station/source provenance, station-specific quality/count metadata, explicit CAMS/weather labels and provider grid metadata |
| New worker initially imported NumPy inside an executor thread; actual Windows/Python 3.14 run hung inside native-module initialization | Initialize native ML libraries on the separate worker's main thread before starting executor tasks; cap numerical/forest worker threads |
| Expired job claim used SQLAlchemy in-memory evaluation of mixed SQLite naive/aware timestamps | Atomic database predicate with session-side evaluation disabled; tested reclaim and stale-owner protection |
| Reusing a frozen evaluation could retain an old unavailable status after fresh forecast inputs arrived | Recompute forecast availability independently of frozen metrics; regression covers recovery and subsequent missing/stale inputs |

### Architecture and correctness limits

The queue has deterministic default city/stage order, one elected sync worker and one elected ML worker, atomic claims, renewable leases, retry/backoff and committed interval progress. Selecting a city may promote an existing incomplete initial stage. A 90-second abandoned lease delays takeover after a hard crash, while cached API results remain available. Startup does not await history or ML. Provider operations and CPU-heavy model work are outside the API process. Additive tables: `background_jobs`, `data_coverage`, `model_artifacts`, `model_results`, `model_executions`, `source_metadata`. SQLite WAL and dialect-aware SQLite/PostgreSQL metadata upserts were added; PostgreSQL integration was not exercised here.

Coverage is a ledger of provider requests/adopted full UTC days, not proof that every pollutant has 24 observations. Date-based endpoints may return existing hours when repairing a partial day; physical interval-end and Sarajevo DST aggregation rules remain unchanged. Stages target last 24h/7d/30d/90d; calendar requests can include partial boundary days. Older missing provider values are not fabricated. Historical physical gaps in a successfully checked range remain missing, while recent overlap and explicit bounded history jobs allow later checks. Cache markers and sync failures never delete prior readings.

The exact original chronological split, feature construction, recursive horizon and matched comparison calculation remain. Production forests and historical metrics share an immutable training-data version until scheduled/revision-triggered replacement; new forecast inference reuses them separately. Prefix corrections/removals (including archived weather corrections) invalidate training/evaluation. Appended samples alone do not force an hourly refit. Forecast-response identity includes relevant pollution/weather content and freshness, horizon, algorithm version and schedule bucket. The held-out test interval displayed may be older than the latest forecast; that is intentional and explicit. JSON tree inference is tested against scikit-learn, with no arbitrary model deserialization.

All four city's physical/CAMS result identities are isolated. The bottom physical provenance includes provider, station, last stored timestamp, validation distribution and number of pollutant-time records. It never reuses a modeled count. AQI and pollutant cards explicitly retain CAMS labels; weather remains modeled Open-Meteo. Legacy requested coordinates are no longer mislabeled as returned grid coordinates; newly returned grid coordinates are persisted separately.

### Actual verification evidence

- Final verification: **57 backend tests passed** (`.venv/Scripts/python.exe -m pytest -q`, 10.46 s), **23 frontend tests passed** (`npm.cmd test -- --run`), and **production build passed** (`npm.cmd run build`). One pytest-asyncio Python 3.14 deprecation warning remains. Vite reports a 664.15 kB minified JavaScript chunk (196.30 kB gzip), above its 500 kB advisory. Tests cover sequential city/stage priority, duplicate claims, expired leases/backoff, restart reuse, missing intervals, partial-provider cooldown, incremental persistence, manual-refresh zero HTTP calls, JSON forest equivalence/integrity, retraining thresholds, unchanged-input skips/revisions, station-specific counts, source/city/station UI identity, persistent response-cache reuse and failure retention.
- A first sequential local HTTP run during cold background ML initialization is saved in `backend/loading-performance-cold.json`: dashboard medians 8.19–56.99 ms and 24-hour physical-history medians 12.07–21.67 ms (three requests per city). ML responses in that first run were **pending**, not completed predictions; those times must not be described as inference performance.
- After restarting the backend with persisted results, `backend/loading-performance.json` (23:27 UTC) records dashboard medians **8.82–10.54 ms**, 24-hour physical history **10.04–13.78 ms**, and saved ML/evaluation responses **6.19–7.37 ms** across four cities (three requests per endpoint/city). Zenica, Sarajevo and Mostar returned ready forecasts. Banja Luka correctly retained its evaluation while reporting `comparison_ready_forecast_unavailable` for stale measurements. This measures HTTP delivery, not ML inference, first paint or a controlled before/after deployment benchmark.
- Real Mostar physical-data computations are recorded in `model-reuse-training.json`, `model-reuse-restart.json`, and `model-reuse-regenerate.json`. A required fit/evaluation after input revision took **18,982.37 ms / 2 RF fits** for PM2.5-only and **28,008.35 ms / 3 fits** for weather comparison. Fresh-process unchanged-result reuse took **262.21 / 372.63 ms**, with **0 fits**. Expiring only the derived forecast identity regenerated forecasts with retained models/evaluations in **739.04 / 867.84 ms**, also **0 fits**. These are single local runs with actual fit-call instrumentation, not percentile or general speedup claims.
- Real Open-Meteo date-range connectivity returned HTTP 200 with 48 hourly timestamps for each two-day AQ/weather probe. The actual incremental ingestion path then refreshed 48 existing rows per provider using **one request each**; immediate repeat used **zero** requests. No 90-day request was made in that check.
- Real Mostar FHMZ incremental verification checked two days: **230 received, 0 inserted, 230 updated, 0 skipped**, **6 requests** (station metadata plus five pollutant series). Immediate repeat returned cached with **0 ranges**. These are pollutant-time records, not 230 unique hours.
- Early sandboxed provider calls failed; a later background attempt also observed DNS failures. Cached observations and evaluations remained accessible and the UI exposed partial-source failure. Direct bounded provider verification subsequently succeeded. This is evidence of resilient local fallback, not a claim of uninterrupted upstream availability.
- Browser checks confirmed Mostar FHMZ provenance, validation and station count, then CAMS provenance/count after source switching; the AQI/card/weather distinctions stayed visible. Reload and Zenica-to-Mostar switching after backend restart reused stored data. The final browser error-log query was empty. `optimization-provenance.jpg` records the physical-source view. Exact first-paint and browser interaction latency are not claimed from automation wall time.

### Remaining limitations

No Redis/Celery was added. Worker leases assume synchronized machine clocks and a functioning database. Unexpected worker exits require API restart (durable jobs survive); automatic supervision/production service management is a next step. Slow native jobs are isolated but not automatically killed by a per-job CPU deadline. Explicit offline scientific replay scripts must not run alongside background imports. Historical intervals are tracked at date granularity, not individual pollutant/instrument gaps; existing single-instrument constraints and FHMZ reuse limitations remain. Large hourly frontend responses are memory-cached; the database, not browser storage, guarantees their persistence. Browser-storage quotas fail gracefully. No PostgreSQL/load/energy benchmark or general forecast accuracy improvement is asserted. Public deployment still needs access control, rate limits, migration management and data-use permission.

---

## Comprehensive implementation review — 5 November 2026

This section supersedes older statements below about absent sensor history, CAMS-only ML, Zenica-only scheduling, missing OpenAQ credentials and the former future-timestamp tolerance. Earlier sections are retained as the history of previous fixes. Scope: actual backend/frontend code, models, configuration, tests, README, local database, authenticated provider requests, official documentation and local browser/REST verification. The new attachment also ends mid-sentence in section 9; the visible requirements were implemented without inventing missing instructions. No Git repository was present, so there was no Git diff/history to inspect. Existing files were edited in place; the database was extended without deleting existing readings.

### Assessment and implemented scope

The application now supports historical **physical** measurements and station-specific forecasts for all four cities, alongside explicitly separate CAMS data. Its original design, Bosnian UI, 5174/8001 ports, Random Forest algorithms and valid 24-step chronological evaluation remain. This is substantially stronger thesis implementation evidence, but it is still an academic prototype. Public-health validation, production operations and robust multi-season scientific validation remain incomplete.

| Priority | Confirmed issue | Implemented correction |
|---|---|---|
| Critical | Charts and both ML queries lacked a selectable physical dataset; ML queried all air-quality sources at a location | Added shared `datasets.py`, explicit `source`/`station_id`, strict city ownership, exact CAMS source filtering and a shared UI selector. No implicit CAMS fallback. |
| Critical | Physical adapters polled only latest values, leaving months of legitimate history unused | Added bounded/paged OpenAQ hourly imports and public FHMZ source-hour imports, daily checkpoints, 72-hour overlap, metadata, quality exclusion and replay-safe identities. |
| High | ML continuity compared only total elapsed span; a duplicate and a gap could cancel | Every adjacent timestamp must be exactly one hour apart. No imputation. |
| High | Old lag windows could produce a nominal future forecast entirely in the past | Stale/incomplete latest windows suppress operational predictions; historical metrics remain available. Cached responses remove elapsed points. UI explains remaining horizon. |
| High | Station persistence could silently move an existing station to another city; repeated rows within one payload could violate uniqueness | Reject reassignment; update the in-memory identity map immediately; historical imports cannot move `last_measurement_at` backwards. |
| High | Two-hour future timestamp tolerance could mark future-labelled sensor values live | Live eligibility now requires a non-future timestamp within three hours, reference status, correct units, finite/nonnegative values and accepted quality. |
| High | Background CAMS/weather refresh ran only for Zenica | All four cities now run current physical, CAMS, weather and historical physical refreshes; failures are isolated per service/city. |
| High | Source discovery could choose a nearby station in another municipality | Explicit verified OpenAQ station IDs; historical imports additionally validate country, coordinates, stationary/reference status and licence metadata. Kakanj is not treated as Zenica. |
| Medium | Completely missing hours had no chart row, so lines could bridge long gaps | Emit null buckets; never fill measurements. Daily aggregation uses hourly means, per-series counts and independent peaks; DST remains 23/24/25 hours. |
| Medium | Midnight-ending physical measurements were liable to enter the next day's summary | Physical daily buckets use interval-end semantics; midnight belongs to the preceding Sarajevo day. Peak timestamps retain original UTC labels. |
| Medium | Null operational temperature suppressed available reanalysis for the same hour | Prefer finite available operational values, otherwise use historical weather; reanalysis never enters ML backtesting. |
| Medium | City/source changes could accept stale asynchronous responses | City-scoped React state remounts and dataset/range guards prevent cross-city/source rendering. Removed redundant ML effects on unrelated sync fields. |
| Medium | Missing AQI could display green health guidance; embedded browser used `M11` and decimal points despite bs-BA | Unknown/invalid/stale AQI has unknown guidance; Sarajevo timezone and Bosnian numeric/date fallbacks are verified in the embedded browser. Existing AQI category boundaries are preserved. |
| Medium | Insufficient weather comparison incorrectly reported aligned rows as tested samples | Test count remains zero until an actual hold-out evaluation occurs. Added matched per-horizon scores. |
| Medium | Sustainability fields described sync-run counts as HTTP requests | Added accurately named sync-run fields and explicit legacy-field notes. Import responses count their actual requests. No energy/carbon claim. |
| Medium | Fetch timeout ended before JSON body parsing; partial refresh could display total success | Await response parsing inside timeout scope; inspect semantic response statuses before displaying success. |

### Provider evidence and availability

The configured key was read through `SecretStr` and sent only to OpenAQ in `X-API-Key`. It was never printed, stored in evidence files, or placed in URLs. Authenticated location searches returned HTTP 200 for all four cities. Public metadata is recorded in `backend/source-verification.json`; `scripts/verify_sources.py` repeats the check.

| City | Verified physical identity | History/access result | Freshness evidence |
|---|---|---|---|
| Zenica | FHMZ **Zenica Brist**, ID 6, STA-BA0036A, 44.202220 / 17.900500 | Public hourly source history works; OpenAQ Tetovo 2656051 ends 12 July 2024 and has no PM2.5 | FHMZ live at local REST smoke check; discontinued Tetovo never labelled live |
| Sarajevo | OpenAQ **Sarajevo**, 9598, AirNow, 43.856665 / 18.398205 | PM2.5 historical `/hours` works, US Public Domain metadata; this station is **not** Bjelave | Live at local smoke check; FHMZ Bjelave 3 remains the separately identified fallback |
| Mostar | FHMZ **Mostar**, ID 30, STA-BA0067A, 43.348000 / 17.794000 | No OpenAQ results in the verified search; FHMZ public hourly history works | Live at local smoke check |
| Banja Luka | OpenAQ/EEA **BANJA LUKA - LAZAREVO**, 6482140, ODC-BY | Hourly history includes PM2.5, PM10, NO2, SO2, O3 and CO in μg/m³; series begins August 2026 | Latest metadata initially 5 November 17:00 UTC; exceeded the three-hour limit during smoke testing and correctly returned `stale`, `is_live=false` |

FHMZ `/rest/station/detail/{id}` independently confirmed names, coordinates and municipality for Brist, Bjelave and Mostar. The portal's linked `/js/data.js`, `/js/aqdata.js` and `/rest/forms/type1` expose the public historical GET contract: station, pollutant, `aqdata_type`, `begin_date`, `end_date`, maximum one year. A two-day PM2.5 probe for Brist/Mostar returned HTTP 200 and hourly rows. The importer uses only type 0, **source hourly data**; `Valid` in those rows is preserved as a provider quality flag, never relabelled as final validated data. Offset-free DST-fold/nonexistent hours are skipped. Negative/nonfinite/malformed values are excluded and counted. Rejected/flagged data are not replaced with invented values.

Public access is not proof of a redistribution licence. No FHMZ machine-readable licence was established. The implementation uses the official public read interface for this local academic task, preserves attribution, bounds frequency/range and makes no public deployment or dataset redistribution. Written reuse confirmation remains necessary before publication/commercial redistribution. OpenAQ licence/owner/provider metadata and original coverage/period flags are stored in additive metadata tables.

Official research also confirmed [EEA's historical/UTD download service](https://www.eea.europa.eu/en/datahub/datahubitem-view/datahubitem-view/778ef9f5-6293-4846-badd-56a29c70880d) and [RHMZ RS public reports](https://www.rhmzrs.com/). Those remain alternative acquisition paths; no direct EEA Parquet importer or PDF-to-hourly RHMZ reconstruction was implemented. Daily/report summaries must not be passed off as hourly observations. OpenAQ already supplies the verified EEA Lazarevo series.

Actual initial 92-day import results (counts are pollutant records, not days or distinct hours):

| Station | Received | Inserted | Existing refreshed | Skipped invalid/out-of-window/ambiguous | HTTP requests |
|---|---:|---:|---:|---:|---:|
| Sarajevo / AirNow | 2,155 | 2,122 | 20 | 13 | 4 including station metadata (3 hourly pages) |
| Lazarevo / EEA | 9,141 | 9,053 | 88 | 0 | 13 including station metadata (12 hourly pages) |
| Zenica Brist / FHMZ | 10,200 | 9,671 | 105 | 424 | 6 |
| Mostar / FHMZ | 11,140 | 10,920 | 105 | 115 | 6 |

Counts do not imply complete days. OpenAQ `received` includes any repeated page rows; storage deduplicates by station/time/pollutant. Accepted provider-flagged/incomplete values retain metadata but are excluded from analysis. Current-value refreshes retain the same station identity. The 92-day import is a rolling request window, not a claim of 92 complete days for every station.

### Scientific review and measured results

The corrected fixed-training, non-overlapping **24-step recursive walk-forward** evaluation is preserved. Each step uses predicted previous steps; no actual future PM2.5 is fed back inside an origin. Later origins may use observations known by that later origin. The initial 80% of engineered samples trains the evaluation model; it is not refitted on the hold-out. Final forecasting separately refits on all eligible data. MAE and RMSE use matched targets/predictions; persistence repeats the origin value for all 24 steps.

Weather comparison uses exactly the same aligned training samples, origins and target hours for both forests and persistence. `previous_day1` is a fixed 24-hour lead; for target t within origin+1…24, its nominal issuance t−24 is no later than origin. No future observed/reanalysis weather is substituted. Temperature, wind, humidity, precipitation and annual cyclical features augment the original lag/calendar features. The frontend exposes per-horizon errors and source identity. Standalone PM-only metrics are not necessarily comparable to the aligned comparison if weather data are missing.

Observed physical-station comparison on 5 November 2026; all errors are μg/m³. These are actual runs against mutable, unvalidated local data, not cross-validated claims of general accuracy:

| Station | Eligible PM2.5 hours | Origins / test hours | PM-only MAE / RMSE | Weather MAE / RMSE | Persistence MAE / RMSE | Weather MAE change |
|---|---:|---:|---|---|---|---|
| Brist | 2,018 | 15 / 360 | 9.074 / 12.765 | 9.266 / 11.842 | 10.431 / 14.096 | **2.1% worse** |
| Sarajevo | 2,132 | 12 / 288 | 7.842 / 11.211 | 7.732 / 10.997 | 9.726 / 13.135 | 1.4% lower |
| Mostar | 2,205 | 17 / 408 | 3.164 / 4.223 | 2.872 / 3.958 | 3.653 / 5.366 | 9.2% lower |
| Lazarevo | 1,557 | 9 / 216 | 23.828 / 30.742 | 22.598 / 29.187 | 31.207 / 37.435 | 5.2% lower |

Lazarevo's incomplete latest lag window prevents a current operational prediction; complete older hold-out windows still support evaluation. Its smaller coverage and different target range prohibit comparing city accuracy as though the datasets were equivalent. There is no evidence here that seasonality alone improves accuracy: that requires a separate ablation and multi-season hold-out. Lower MAE also does not always mean lower RMSE (Brist illustrates the trade-off).

Evidence: `backend/audit-evaluation.json`, with the focused rerun `backend/audit-evaluation-banja-luka.json`, contains periods, hashes, package versions and per-horizon results. Pollution hash alone is not a frozen experiment: retain an offline DB snapshot including archived meteorology and exact code/dependency versions. Provider revisions and pollution publication latency are not replayed. Fixed-lead weather inputs are not a single coherent run issued at each origin; this operational approximation remains documented in both API and README. No measured evaluation is claimed for API horizons beyond 24 hours.

### AQI, UI and blank-panel review

The application displays the Open-Meteo European AQI, not a locally calculated physical-station AQI. Category limits remain 20/40/60/80/100. [Open-Meteo's current documented EEA bands](https://open-meteo.com/en/docs/air-quality-api) use hourly values and the maximum pollutant sub-index; concentrations are not themselves AQI scores. Missing pollutants and station measurements are not fabricated into a complete sensor AQI. Guidance remains explicitly general and tied to a fresh modeled index. Unit mismatches are rejected rather than converting ppb to mass without required assumptions.

The former blank-section fix is present and retained: `ForecastPanel` previously rendered an empty fixed-height 420px skeleton while expensive ML work ran. It now displays a compact visible Bosnian loading explanation; unavailable states contain text. Weather panels do not reserve unexplained empty wrappers. Browser verification observed the chart followed by informative ML states/results, with no original blank panel and no console error/warning in the captured check. Bosnian formatting initially failed in the embedded browser despite locale arguments; numeric/timezone-aware fallbacks fixed the visible `M11`/English decimal formatting. The hero, colors, cards and section order are preserved.

### Verification and sustainability evidence

- Backend: **44 tests passed**, one existing Python 3.14 `pytest-asyncio` deprecation warning. New coverage includes station ownership, source isolation, duplicate payloads, unchanged-ingestion identity, future freshness rejection, invalid values, DST-fold rejection, interval-end daily boundary, missing-hour buckets, hourly-first maxima, fallback temperature, pagination/checkpoints, rollback, quality exclusion and per-horizon arithmetic.
- Frontend: **16 tests passed** across two files; AQI edge cases and Sarajevo/bs-BA formatting included. Production build passed; existing >500 kB bundle warning remains.
- Browser checks covered 390px mobile and 1440px desktop layouts, city changes, physical/CAMS source changes and 90-day daily controls. Captured console checks contained no error/warning. A final restarted-server check confirmed retained Sarajevo licence attribution and Lazarevo's 216 evaluated hours with zero unsupported operational forecast points.
- `scripts/smoke_api.py`: **29 assertions/checks passed**. All four dashboard/weather/current endpoints and both source modes of 90-day hourly/daily history returned 200. Wrong-city station access returned 422. Every tested count was within its expected-hour bound. Raw evidence is in `backend/audit-api-smoke.json`.
- One cache-aware live synchronization succeeded for CAMS/weather in **all four cities**, fixing the formerly empty Mostar/Banja Luka datasets. Current physical refresh returned success for Brist, Sarajevo and Mostar; Lazarevo correctly remained stale at that instant.
- The 90-day Brist physical maximum response measured 1,293,419 bytes hourly versus 56,952 bytes daily: about **95.6% smaller payload**, not a measured energy reduction. Daily queries produced 91 local calendar buckets versus 2,161 inclusive hourly buckets. Some buckets are partial/null by design.
- Observed smoke latency varied widely (including a 9.4 s response during concurrent model work). These are single local measurements under changing CPU load, not p95 throughput claims. Cold model evaluation takes tens of seconds on this environment; visible loading and caching are necessary.
- No API key, paid service, physical hardware or synthetic environmental measurement was used as a substitute for real data. Synthetic test fixtures only test software behavior and are not imported into the application database.

### Remaining limitations and next development phase

1. **Freeze the experiment:** version a permitted snapshot and code revision, record weather and pollution hashes, use rolling chronological folds, seasonal coverage, separate seasonality/weather ablations, confidence intervals and publication-delay simulation. Obtain validated measurements when available. Never infer general superiority from this single split.
2. **Data governance:** secure FHMZ redistribution terms; expose optional flagged-data inspection/export with quality metadata; retain provider revisions instead of overwriting corrections; distinguish individual instruments if a station has multiple instruments for one pollutant (currently rejected).
3. **Operations:** add Alembic migrations and PostgreSQL CI, backups/restore tests, external scheduler and distributed locks. `create_all` only adds absent tables; it does not migrate changed schemas. SQLite foreign-key enforcement and concurrent-write behavior need dedicated production treatment. Async routes still perform synchronous DB work.
4. **Reliability/security:** persist retry/backoff state for failed historical imports (currently retried at the next scheduled cycle), instrument total HTTP calls/cache skips, coalesce concurrent ML work, limit costly manual force-refresh endpoints and add authentication/rate limits before network exposure. The development server should remain loopback-only.
5. **Efficiency:** legacy CAMS refresh still requests the full configured history; reduce stable-history overlap after a measured correctness/revision policy is established. Source selection and metadata are explicit, but no shared HTTP connection pool or cross-worker cache is implemented. Reduce/chart-split the frontend bundle without redesigning it.
6. **UX:** source selection currently scopes chart and ML; hero/AQI remain explicitly modeled. A future physical AQI needs documented pollutant availability/quality rules. Add full browser interaction regression automation and broader accessibility checks; current frontend unit tests do not substitute for complete UI test coverage.
7. **IoT/MQTT:** document an optional adapter feeding the same normalized station/time/quality model; no MQTT broker or hardware implementation is claimed or required here.

Re-run commands and precise startup instructions are in README. Relevant primary methodology references: [OpenAQ hourly measurements](https://docs.openaq.org/resources/measurements), [OpenAQ terms/licensing](https://docs.openaq.org/about/terms), [FHMZ public data view](https://zrak.fhmzbih.gov.ba/aqdata.htm), [Open-Meteo Previous Runs](https://open-meteo.com/en/docs/previous-runs-api).

---

**Audit date:** 29 October 2026  
**Scope:** ingestion, timestamps/provenance, caching and identity, PM2.5 forecasting, AQI/units/guidance, REST/database/scheduling, sustainability claims, frontend development port, tests and thesis documentation.

## Executive assessment

EcoMonitor is a credible bachelor-level software prototype with a clear layered implementation and unusually good source-provenance disclosure. It is suitable as the implementation base for the thesis, but it should not yet be described as a validated operational environmental monitoring system. The current dataset is CAMS model output delivered by Open-Meteo, not a Zenica sensor dataset, and the application still lacks the empirical validation, migration/deployment work and actual-measurement integration required for a stronger scientific conclusion.

One critical methodological error was confirmed and fixed: the application displayed a recursive 24-hour PM2.5 forecast but previously reported one-step-ahead hold-out metrics. The revised evaluation now measures non-overlapping, recursive 24-step forecasts with a matching 24-hour persistence baseline and a fixed chronological training boundary.

## Findings and fixes

### 1. Open-Meteo ingestion, time semantics and provenance

Verified behavior:

- The request uses the documented `/v1/air-quality` endpoint, valid variable names, `past_days <= 92`, `forecast_days=7`, `domains=cams_europe`, `timeformat=unixtime` and `timezone=GMT`.
- Unix timestamps are converted with `datetime.fromtimestamp(..., tz=UTC)`, producing unambiguous UTC instants without local-DST conversion errors.
- PM2.5, PM10, NO2, SO2, CO and O3 are documented by Open-Meteo in `μg/m³`. European AQI is a separate index value.
- Every row records source name, source URL, `source_type="modeled"`, model description, valid time and ingestion time. Dashboard responses repeat the modeled-data disclaimer.
- Open-Meteo describes `past_days` as archived forecasts. Therefore “historical” in EcoMonitor means a modeled value whose valid time is in the past, not an observed measurement.
- The `(location_id, measured_at, source_name)` uniqueness constraint provides database-level identity. A range lookup updates an existing row instead of inserting another row.
- The latest successful synchronization completion controls the configurable provider cache window. Failed syncs do not falsely refresh that cache.

Fixes made:

- Historical/future classification in dashboard and ML queries now uses the timestamp at read time. Previously, an old row could remain excluded after its forecast flag became stale if no later synchronization occurred.
- Provider concentration units are validated when `hourly_units` is present, preventing a silent unit-contract change.
- An in-process synchronization lock now prevents the scheduled loop and manual refresh from racing in the standard single-process deployment.
- Tests now cover UTC conversion, current-hour versus future classification, modeled provenance, unit rejection, cache freshness and idempotent persistence.

Remaining limitations:

- The unit contract is normalized at schema/API level rather than repeated per row. This is storage-efficient, but a future multi-provider system should add versioned pollutant metadata or source-variable metadata if providers use different units.
- The lock is process-local. Multiple API workers or replicas still require a PostgreSQL advisory lock, a job queue, or atomic database upserts.
- The system does not preserve raw provider responses, response model/version identifiers, requested versus returned grid coordinates, or provider `hourly_units` as audit records.
- `records_received` counts provider timestamps, while inserted rows exclude timestamps for which every requested value is null. This is intentional but must be explained when reporting ingestion totals.
- OpenAQ/verified station ingestion is not implemented. The current adapter boundary only makes that extension possible.

### 2. PM2.5 machine-learning audit

Verified feature construction:

- Each supervised target uses only earlier PM2.5 values: lag 1, means of the previous 3, 6 and 24 values, lag 24, plus hour and weekday sine/cosine terms.
- A target value is not present in its own feature row.
- Feature windows are accepted only when their timestamps form a continuous hourly interval.
- The split is chronological at 80/20 and is not shuffled.
- The evaluation model is fitted only on the first 80%. It is not refitted at later test origins.
- The final production forecast is generated only after a separate refit on all available historical modeled values. This does not contaminate the reported hold-out metrics.
- MAE is the mean absolute paired error. RMSE is the square root of mean squared paired error. Both model and baseline use identical target timestamps.

Critical issue fixed — forecast-horizon mismatch:

- **Before:** metrics were computed from one-step predictions across the final 20%, using the true previous test value as lag 1. Those metrics did not evaluate the recursive 24-hour chart shown to users and were optimistically mismatched to the product claim.
- **After:** the final 20% is evaluated through non-overlapping rolling origins. Each origin recursively predicts 24 hours, feeding predictions back into the lag history. The persistence baseline repeats the value known at the origin for the same 24 targets. Returned metrics include `evaluation_horizon_hours`, `evaluation_origins` and the total number of evaluated forecast hours.

Additional fixes:

- The ML cache key now includes the latest ingestion timestamp and row count as well as the latest valid timestamp. Updating historical values without extending the series can no longer return stale metrics.
- Forecast generation explicitly refuses to run when the latest 24-hour lag window is discontinuous.
- Recursive prediction uses one worker after parallel model fitting, avoiding repeated parallel-scheduling overhead and warning amplification for hundreds of small prediction calls.
- Tests independently verify metric arithmetic, prior-only feature construction and the identity `test_samples = evaluation_origins × 24`.

Remaining scientific limitations:

- The target is CAMS/Open-Meteo modeled PM2.5, not sensor-measured PM2.5. Results measure how well the model predicts another model’s time series.
- Only up to 92 days are ingested, which is inadequate for seasonal generalization claims.
- The random-forest hyperparameters are fixed without nested time-series validation. The hold-out set must not be reused repeatedly to select model settings.
- Meteorological predictors were absent at the time of the original audit; the weather extension below adds leakage-aware forecast temperature, wind, humidity and precipitation. Emissions, holiday/heating-season and terrain predictors remain absent.
- No prediction intervals, uncertainty calibration, horizon-specific error curve, residual diagnostics or drift monitoring are provided.
- A stronger thesis evaluation should compare persistence, seasonal persistence (`t-24`), linear autoregression and the random forest across several chronological folds and report error by horizons 1–24.

### 3. AQI, pollutant units and health guidance

Verified behavior:

- EcoMonitor does not calculate European AQI locally; it displays Open-Meteo’s consolidated `european_aqi`. Open-Meteo documents that this is the maximum of pollutant-specific European AQI values.
- The frontend bands match the revised European AQI ranges exposed by Open-Meteo: Good 0–20, Fair 20–40, Moderate 40–60, Poor 60–80, Very poor 80–100 and Extremely poor above 100.
- Focused frontend tests cover every category boundary and missing values.
- Concentration displays use `μg/m³`, including CO, matching the provider contract. European AQI is not displayed as a concentration.

Fixes made:

- AQI categorization was moved into a testable pure module.
- Unsourced prescriptive wording such as “keep windows closed” was replaced with cautious, simplified guidance that directs users to official local advice at high levels.

Interpretation limits:

- The guidance is simplified application text, not a verbatim implementation of the EEA’s separate messages for the general population and sensitive groups. It remains labeled as general information rather than medical advice.
- CO is displayed as a pollutant concentration but is not one of the five pollutants used in the European AQI.
- The dashboard takes the most recent hourly modeled value. It does not request Open-Meteo’s separate 15-minute `current` field.
- The 2024 AQI boundaries are not legal compliance thresholds, annual WHO guidelines, or evidence of individual exposure.

Authoritative references reviewed:

- [Open-Meteo Air Quality API](https://open-meteo.com/en/docs/air-quality-api)
- [EEA explanation of European AQI categories and health messages](https://www.eea.europa.eu/en/about/contact-us/faqs/what-do-the-air-quality-index-values-mean)
- [EEA European Air Quality Index](https://airindex.eea.europa.eu/AQI/?webgl=0)

### 4. REST API, database, scheduling and sustainability

Strengths:

- Query limits constrain dashboard history and forecast horizons.
- Provider failures produce HTTP 503 for explicit refresh while stored data remains readable.
- The wide hourly table is appropriate for one provider with a fixed pollutant set and avoids repeated timestamp/source columns.
- Composite location/time identity and range indexes match the primary access pattern.
- Sync runs preserve success/failure status, row counts, provider generation time and error text.
- Background refresh is non-blocking at application startup and applies a minimum five-minute interval.
- Response timing is exposed as `X-Process-Time-Ms` without claiming it measures end-to-end network latency or energy.

Fixes made:

- Sustainability output no longer calls all refreshed rows “duplicates.” It now separates provider rows received, new rows inserted and existing rows refreshed in place.
- Successful and failed provider request counts are both exposed.
- The cache duration comes from application settings instead of a hard-coded value.
- Metric notes explicitly disclose that cache skips are not persisted; avoided provider calls therefore are not measured.

Remaining reliability limitations:

- `/health` is a liveness endpoint only; it does not check database readiness or data freshness.
- `create_all` is not a migration strategy. Alembic migrations are required before schema evolution or deployment.
- The in-process scheduler runs once per application process. Multiple workers would duplicate scheduled work.
- The async refresh route performs synchronous SQLAlchemy work around an async HTTP request. For higher load, use async SQLAlchemy or move ingestion to a worker.
- There is no authentication or rate limit on forced refresh. A production deployment should protect it.
- No retention policy, backup/restore test, structured observability, retry/backoff policy or circuit breaker is implemented.
- PostgreSQL is configured but the automated suite currently validates SQLite only.

Sustainability claim limits:

- The endpoint measures request/storage counters and exposes policy settings. It does not measure joules, CPU time, embodied emissions or CO2e.
- “Four dashboard requests per active client hour” is a policy-derived estimate from the 15-minute interval, not observed traffic.
- Thesis measurements should use a defined workload, repeated runs, payload bytes, database size, CPU time and an explicitly named energy/carbon measurement method where available.

### 5. README and thesis architecture gaps

The README now describes the corrected 24-hour evaluation, current port, unit normalization, archived-model history semantics and sustainability metric boundaries. The following work remains for a thesis-ready submission:

1. Integrate and validate at least one actual measurement source (OpenAQ or an official Bosnia and Herzegovina station feed), or explicitly narrow the research claim to modeled-data monitoring.
2. Add an ER diagram, component/C4 diagram, ingestion sequence diagram and ML training/evaluation data-flow diagram with traceable figure numbers.
3. Add Alembic migrations, PostgreSQL integration tests and a reproducible deployment architecture.
4. Define functional and non-functional requirements with acceptance criteria and a requirements-to-test traceability matrix.
5. Document validity threats: model-on-model target, spatial resolution, missing values, forecast revisions, seasonality and selection bias.
6. Add a reproducible experimental protocol, frozen dataset snapshot/hash, software versions, random seeds and full evaluation tables.
7. Add security, privacy, accessibility and failure-mode analysis. No personal data is expected, but operational risks still need treatment.
8. Implement configurable alert rules and persistence if the thesis claims an alerting subsystem; current “alerts” are presentation-time guidance only.
9. Add continuous integration, code coverage reporting, API contract tests and browser accessibility/responsive tests.
10. Document licensing/attribution text required by CAMS and Open-Meteo in the thesis and any deployed footer.

## Frontend port

Vite now defaults to `5174` with `strictPort: true`. Backend CORS defaults and `.env.example` accept both `http://localhost:5174` and `http://127.0.0.1:5174`. No configuration for other projects was changed.

## Verification performed

The following commands were executed after the fixes:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm.cmd test
npm.cmd run build
```

Observed results:

- Backend: **8 passed**. One dependency deprecation warning from `pytest-asyncio` under Python 3.14 was reported; it is not an application test failure.
- Frontend: **1 test file passed, 12 tests passed**.
- Production build: **completed successfully**. Vite reported a non-failing warning that the main JavaScript chunk exceeds 500 kB after minification.
- Existing local database smoke test: forecast endpoint returned HTTP 200/`ready` with **18 evaluation origins × 24 hours = 432 paired test samples**. This verifies the returned evaluation structure, not model accuracy.

No new live-provider accuracy figure is recorded in this audit. ML metrics are data-dependent and must be captured from a named dataset snapshot or a dated live run when used in the thesis.

## Recommended next phase

Prioritize scientific validation over additional interface work:

1. Add a verified Zenica measurement dataset and retain modeled/sensor series separately.
2. Freeze and version an evaluation dataset.
3. Implement rolling-origin comparisons against persistence and seasonal persistence with horizon-specific results.
4. Add PostgreSQL migrations/integration tests and make scheduling safe across multiple processes.
5. Produce the thesis diagrams, traceability matrix and validity-threat discussion from the implemented architecture.

## Weather integration extension — 29 October 2026

### Implemented and verified

- Added independent Open-Meteo Weather Forecast and Previous Runs ingestion for hourly temperature, relative humidity, 10 m wind speed and precipitation, plus daily minimum, maximum and mean temperature.
- Hourly timestamps are normalized to UTC and joined to air-quality values by exact valid time. Daily dates use the location timezone (`Europe/Sarajevo`).
- Added database identities for hourly weather `(location, timestamp, source, forecast lead)` and daily weather `(location, date, source)`. Repeated live synchronization updated existing records instead of creating duplicates.
- Added separate 30-minute operational-weather and 24-hour archived-forecast caches, a process-local synchronization lock, partial-source failure reporting, nullable missing fields and provider-unit validation.
- Added a Bosnian weather panel without changing the established homepage structure or visual language. Latest values are labeled as modelirani podaci and future values as prognoza, never local-station measurements.
- Preserved the original PM2.5-only Random Forest and corrected 24-step evaluation. The weather-aware model adds temperature, wind, humidity, precipitation and annual cyclical features.
- Both model variants use the same aligned samples, chronological split, non-overlapping 24-step recursive origins and PM2.5 targets. The persistence baseline uses those same targets. Missing archived forecasts return `insufficient_data` rather than falling back to observations/reanalysis.
- The operational weather-aware forecast requires a complete future-weather horizon. Comparative metrics remain available while a forecast is withheld if that horizon is incomplete.

### Leakage assessment and limitation

Historical meteorological predictors use Open-Meteo Previous Runs fields suffixed `_previous_day1`. For target timestamp `t`, the value was issued at `t-24h`; it was therefore available by every evaluated PM2.5 origin covering that target. This prevents use of future observed/reanalysis weather. However, each target uses its own fixed 24-hour-lead value, so a 24-step window is not reconstructed from one coherent forecast run issued at the PM2.5 origin. The comparison is leakage-safe under an information-availability test but remains an approximation of a fully archived operational forecast. The API and README disclose this limitation.

### Focused verification results

Commands executed after implementation:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q

cd ..\frontend
npm.cmd test
npm.cmd run build
```

- Backend: **13 passed**; one non-failing `pytest-asyncio` deprecation warning under Python 3.14.
- Frontend: **1 test file passed, 12 tests passed**.
- Production frontend build: **completed successfully**; Vite retained its non-failing chunk-size warning.
- A live Zenica Open-Meteo synchronization completed successfully for both operational and Previous Runs endpoints. The database held 2,568 hourly weather rows and 14 daily summaries at verification time; the dashboard returned a latest value, daily summary and 24 forecast hours.
- On the mutable local dataset at that dated run, the fair comparison used 18 origins and 432 paired forecast hours. PM2.5-only MAE/RMSE were 8.811/12.061 μg/m³, weather-aware 8.469/11.807 μg/m³, and persistence 10.142/13.690 μg/m³; weather-aware MAE was 3.9% lower. These are observed smoke-test results for the current local modeled dataset, not a frozen thesis experiment or a general accuracy claim.
- REST smoke checks returned HTTP 200 for both new read endpoints. `/weather` returned latest/daily data and 24 forecast hours; `/forecast/pm25/weather-comparison` returned `ready`, `comparison_is_fair=true`, 432 test samples and 24 forecast hours.

### Remaining limitations and next recommendations

1. Freeze provider responses or a versioned dataset snapshot with hashes before reporting final thesis results; upstream revisions make live metrics non-reproducible over time.
2. For a stronger operational experiment, archive complete forecast runs at each prediction origin rather than combining fixed 24-hour-lead values.
3. Add horizon-specific errors for hours 1–24, seasonal persistence, rolling chronological folds and uncertainty before concluding that meteorology improves accuracy.
4. Replace `create_all` with Alembic migrations for the weather tables and test PostgreSQL migration/upsert behavior.
5. Make scheduler locking cross-process before multiple-worker deployment and persist cache-skip counters if avoided calls are to be measured directly.
6. This recommendation was superseded by the physical-station extension below: the location catalog now includes Sarajevo, Mostar and Banja Luka, while each city's sensor status remains independently provenance- and freshness-gated.

## Physical-station integration — 29 October 2026

### Connectivity and coverage verification

- No `OPENAQ_API_KEY` variable was present in the local `backend/.env` or process environment during this run. A direct OpenAQ v3 request reached the service but returned HTTP 401, so no OpenAQ measurement was marked locally verified or live.
- OpenAQ Explorer showed a fresh EEA reference monitor for Sarajevo and a fresh EEA reference monitor for Banja Luka. The indexed Zenica EEA location was approximately two years stale, and no current Mostar location was verified through OpenAQ search. These Explorer observations are discovery evidence, not authenticated API ingestion results.
- The official FHMZ station list and timestamped hourly endpoint were queried directly. Fresh automatic measurements were verified for Zenica Brist, Sarajevo Bjelave and Mostar at `2026-10-29T13:00:00Z`. Zenica and Mostar both included PM2.5, PM10, NO2, SO2 and O3.
- Banja Luka is outside FHMZ jurisdiction. Because the local OpenAQ key was absent, EcoMonitor correctly returned `unavailable` for Banja Luka instead of claiming live coverage.

### Implementation and safeguards

- Added an OpenAQ v3 adapter that reads the key as `SecretStr`, uses the `X-API-Key` header, searches within 25 km, requires `isMonitor=true`, checks station and measurement timestamps, accepts only recognized `μg/m³` pollutant values and never logs the credential.
- Added an FHMZ fallback using the public endpoints consumed by the official portal. It parses local `Europe/Sarajevo` timestamps into UTC, imports only hourly source values and maps PM2.5, PM10, NO2, SO2 and O3.
- Added normalized `sensor_stations` and `sensor_measurements` tables with provider identity, attribution, unique measurement identity, units and validation state.
- A three-hour freshness rule, with a two-hour future-label tolerance for provider interval timestamps, gates the `is_live` field. Stale individual pollutants are excluded even when another pollutant from the station is fresh.
- The homepage design is preserved. A Bosnian physical-station panel appears before modeled pollutant cards; modeled history, weather-aware forecasting and all prior provenance distinctions remain unchanged.
- FHMZ measurements are explicitly labeled automatic and unvalidated. The provider warns that real-time values may change after validation. CO is not imported because the fallback response does not expose an unambiguous per-value unit.
- Requests use a 30-minute cache. OpenAQ is attempted first when a key exists; FHMZ is used only where configured and fresh. If neither is verified, the API returns `unavailable` rather than relabeling modeled data.

### Compliance limitation

The FHMZ endpoints are public, power the official public portal and FHMZ reports acknowledge automated redistribution to third-party air-quality services. No explicit machine-readable API license was found during this review. The academic implementation minimizes request frequency, links the official source, preserves attribution and repeats the unvalidated-data warning. Written confirmation of redistribution terms is recommended before public commercial deployment.

### Verification results

- Backend: **16 tests passed**; the existing non-failing `pytest-asyncio` deprecation warning under Python 3.14 remains.
- Frontend: **1 test file passed, 12 tests passed**.
- Production frontend build: **completed successfully**; the existing non-failing bundle-size warning remains.
- An isolated live synchronization returned `success`, five fresh measurements and `is_live=true` for Zenica Brist, Sarajevo Bjelave and Mostar. Banja Luka returned `unavailable`, zero measurements and `is_live=false`, as required while authenticated OpenAQ access is absent.
- The weather-aware forecasting implementation and its focused tests were unchanged and continued passing in the full regression suite.

## Historical chart and blank-section correction — 29 October 2026

### Confirmed cause of the blank section

The blank area was not produced by `WeatherPanel`, `WeatherModelPanel`, an empty grid wrapper or an excessive page margin. `ForecastPanel` rendered an empty white card with fixed height `420px` whenever the PM2.5 endpoint was loading. A runtime request to `/api/v1/forecast/pm25` exceeded 15 seconds during verification because the chronological Random Forest backtest is computed synchronously; throughout that interval the card contained only screen-reader text. It therefore appeared as a large unexplained white section directly between the historical chart and the next visible machine-learning panel.

The empty skeleton was replaced by a compact, visible Bosnian status panel explaining that the 24-hour walk-forward evaluation is running. Failed or timed-out requests continue into the existing informative insufficient/unavailable state. A client timeout now prevents provider or ML requests from remaining visually pending without bound. Neither Random Forest implementation nor its evaluation logic was changed.

### Historical chart implementation

- Added a separate backend `/api/v1/history` contract so 30/90-day daily aggregation is transferred efficiently instead of sending every raw hourly row to the browser for calculation.
- Added hourly/daily grouping and average/maximum selection. Daily maxima are independent per pollutant and temperature; peak timestamps are retained separately.
- Added per-series sample counts and the expected local-day sample count. Missing values remain `NULL`, lines break across gaps and the UI explicitly warns when a day is incomplete.
- Calendar buckets use `Europe/Sarajevo`. DST start and end days correctly contain 23 and 25 expected hours. Repeated autumn local hours remain distinct in hourly mode because their UTC instants are preserved.
- Added temperature on the right °C axis as an enabled-by-default dashed line. Pollutants remain on the left μg/m³ axis. Buttons independently toggle temperature, PM2.5, PM10, NO₂, SO₂, O₃ and CO; the legend and tooltip use Bosnian labels.
- CAMS modeled pollution is queried only from the modeled air-quality table. Physical station readings are never merged into this chart and remain in their dedicated panel.
- Added Open-Meteo Historical Weather reanalysis ingestion for the older portion of the 92-day chart range. Operational seven-day weather, historical reanalysis and leakage-safe Previous Runs forecasts retain separate source names and classifications. The Historical Weather endpoint returned HTTP 200 in a direct connectivity check; unavailable values are not fabricated.

### Focused verification results

Commands executed:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q

cd ..\frontend
npm.cmd test
npm.cmd run build
```

- Backend: **23 tests passed**. The non-failing Python 3.14 `pytest-asyncio` deprecation warning remains.
- Frontend: **1 test file passed, 12 tests passed**.
- Production build: **completed successfully**. Vite retained the existing non-failing warning for a JavaScript chunk larger than 500 kB.
- Isolated REST smoke test: `/api/v1/history` returned HTTP 200 with 24 hourly points, 24 available temperature points, modeled pollution provenance and `Europe/Sarajevo` timezone metadata.
- After the cache-aware historical weather sync, the 90-day request returned 91 local calendar-day buckets with temperature available in all 91, sourced from both the operational and Historical Weather APIs. The DST-end bucket for 25 October 2026 reported 25 expected, 25 PM2.5 and 25 temperature samples.
- A 30-day maximum request exposed the first partial day as 7/24 PM2.5 and 7/24 temperature samples and returned different pollutant/temperature peak timestamps where the maxima occurred at different hours.

Focused backend tests cover independent daily maxima, daily means over only available samples, hourly bucketing, missing fields, local-midnight separation and both 23-hour and 25-hour DST days. Test counts describe executed tests only; no environmental measurements or model accuracy results were fabricated.

