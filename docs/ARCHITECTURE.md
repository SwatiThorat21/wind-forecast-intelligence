# Architecture

## Goals and boundaries

The MVP answers one auditable question: for a purchasing decision made on a January 2026 date, how accurate was the latest national wind forecast that was actually available at the configured cutoff for the next calendar day?

The design separates retrieval, normalization, decision-time selection, metrics, and presentation. This prevents route handlers or React components from acquiring business logic and makes the no-look-ahead rule directly testable.

## System context

```text
Elexon Insights API
        |
        | scheduled/manual ingestion (not a dashboard request)
        v
backend/data/raw  -> normalization -> backend/data/processed
                                           |
                                           v
                              Flask domain services + API
                                           |
                                      JSON over HTTPS
                                           |
                                           v
                                   React dashboard
```

## React frontend responsibilities

The React application will:

- provide a decision-date selector constrained to 1–31 January 2026;
- display the derived next-day delivery date and configured cutoff, including timezone;
- request analysis from Flask through a single Axios service configured by an environment variable;
- visualize selected hourly forecast versus complete candidate hourly actuals;
- display MAE, RMSE, mean bias error, WAPE, coverage, and missing-period counts;
- expose loading, empty, partial-data, validation, and server-error states;
- label units, sign conventions, timezones, and incomplete coverage clearly.

It will not call Elexon directly, choose eligible forecasts, or calculate authoritative metrics. Keeping those rules on the backend gives every client one consistent, testable result.

## Flask backend responsibilities

Flask will be a thin HTTP layer over domain services. Planned responsibilities are:

- validate decision dates and optional cutoff configuration;
- load normalized JSON through a storage/repository boundary;
- derive the delivery-day interval in `Europe/London` and UTC;
- invoke forecast selection without look-ahead;
- align selected forecast and actual observations on target `startTime`;
- calculate metrics only over matched, valid pairs;
- return analysis data plus coverage, missingness, provenance, and cutoff metadata;
- map invalid input, missing data, and internal failures to explicit API errors.

Routes should parse and serialize only. Elexon access belongs in `elexon_client.py`, selection in `forecast_service.py`, and calculations in `metrics_service.py`. Python functions and returned domain structures will use type hints.

## Elexon ingestion

Ingestion will be an explicit script, separate from the web process, so dashboard latency and availability do not depend on Elexon. It will:

1. request bounded windows with timeouts and clear error handling;
2. fetch FUELHH delivery periods by settlement-date range and filter `fuelType=WIND`;
3. fetch WINDFOR by publication-time windows broad enough to contain candidates available before each decision cutoff;
4. retain response provenance and the request parameters used;
5. validate required fields and timezone-aware timestamps;
6. preserve raw responses before producing deterministic normalized JSON;
7. report duplicates, conflicting records, malformed rows, and gaps rather than silently hiding them.

Retries, exponential backoff, rate-limit handling, atomic replacement, daily
batching, and explicit failed/incomplete states are implemented in Phase 2B.
The full January dataset remains an explicit user-run command after the small
sample is checked.

## Historical JSON storage

`backend/data/raw/` contains source-date extracts that are reused by default and
replaced atomically only under explicit `--refresh`. The manifest retains every
request attempt, endpoint, query parameters, retrieval time, status, count, and
file path. `backend/data/processed/` contains normalized records and validation
reports.

The canonical processed fields are expected to be:

- actual: `start_time`, `settlement_date`, `settlement_period`, `generation_mw`, source metadata;
- forecast: `start_time`, `publish_time`, `generation_mw`, source metadata.

All canonical timestamps will be stored as ISO 8601 UTC strings. JSON is adequate for the bounded MVP and makes the submitted dataset inspectable. A database is deliberately excluded until data volume or concurrent writes justify it.

## Forecast selection

For decision date `D` and configured local cutoff time `C`:

1. Construct `cutoff = D + C` as an aware `Europe/London` datetime.
2. Define delivery date as the next local calendar date, `D + 1 day`.
3. Enumerate hourly WINDFOR targets belonging to that delivery date.
4. For each target `startTime`, retain WINDFOR rows whose `publishTime <= cutoff`.
5. Select the row with the greatest eligible `publishTime`.
6. Never backfill a missing target period with a forecast published after cutoff.
7. Record target periods with no eligible forecast as missing.

Identical duplicate rows are collapsed only in processed output, with source
indices and a duplicate count; raw rows remain unchanged. Conflicting rows
with the same target and publication timestamp are retained and surfaced by
validation rather than silently chosen.

## Phase 2B storage and alignment

Phase 2B is implemented by:

- `backend/app/services/elexon_client.py`: synchronous bounded requests,
  timeout handling, transient retry/backoff, status and JSON validation;
- `backend/app/services/data_normalization.py`: field validation, duplicate and
  conflict detection, revision handling, and provisional hourly actuals;
- `backend/scripts/ingest_data.py`: daily batch planning, idempotence, atomic
  storage, manifest attempts, and validation reports.

Files are separated by dataset and source date:

```text
backend/data/
├── manifest.json
├── raw/{fuelhh,windfor}/YYYY-MM-DD.json
└── processed/
    ├── {fuelhh,windfor}/YYYY-MM-DD.json
    └── reports/validation_<decision-start>_<decision-end>.json
```

Raw envelopes contain the untouched API record list and exact request metadata.
Processed envelopes contain canonical UTC timestamps, original records,
provenance, duplicate counts, and warnings. The append-only manifest records
every success, genuine empty response, incomplete validation, and failed
attempt. Existing successful files are reused unless `--refresh` is set, and a
failed refresh never replaces them.

FUELHH actuals are provisionally aggregated to an hourly average only when
both aligned `HH:00` and `HH:30` average-MW rows exist. Raw half-hours remain
the source of record. The methodology remains provisional because Elexon
describes WINDFOR values at hourly target timestamps but the exact interval
semantics still require confirmation.

## Future alignment and accuracy metrics

Phase 3 may join forecast and provisional hourly actual rows by canonical UTC
`start_time`. No accuracy metric is calculated in Phase 2B. The future error
definition is:

```text
error = forecast_mw - actual_mw
```

In Phase 3, for the set of valid matched hourly pairs:

- MAE: `mean(abs(error))`
- RMSE: `sqrt(mean(error^2))`
- Mean Bias Error: `mean(error)`; positive means over-forecasting
- WAPE: `sum(abs(error)) / sum(abs(actual_mw)) * 100`
- Coverage: `matched_hours / expected_hours * 100`

WAPE is undefined when the actual denominator is zero and must return `null`
plus an explanatory flag. Metrics will include expected, forecast, actual,
matched, and missing hour counts. Delivery-day boundaries will remain
timezone-derived rather than assuming 24 hours on daylight-saving transition
dates.

## API communication

The frontend will use a versioned API prefix such as `/api/v1`. A likely primary resource is `GET /api/v1/analysis?decision_date=YYYY-MM-DD`; the final contract will be designed in Phase 3. Responses should contain:

- decision and delivery metadata;
- cutoff local time and UTC instant;
- period-level forecast, actual, error, and source publication time;
- metrics and coverage;
- data provenance and warnings.

CORS will allow only configured frontend origins outside local development. The frontend base URL and backend allowed origins will come from environment variables; production URLs will not be hardcoded.

## Deployment

- Vercel builds and serves the static Vite frontend.
- Render or a compatible Python platform runs the Flask backend behind a production WSGI server.
- Processed historical JSON is bundled with the backend artifact for this read-only MVP.
- Docker provides reproducible local builds; Docker Compose coordinates only frontend and backend.
- Ingestion runs manually or as a controlled pre-deployment job, not at web-process startup.
- Health checks, structured logs, pinned dependencies, and environment validation will be added before deployment.

This design intentionally omits authentication, databases, queues, caches, and background workers because they do not improve the bounded interview MVP.
