# Wind Forecast Intelligence

Wind Forecast Intelligence is a decision-support project for evaluating the
national wind forecast available at a configurable day-ahead purchasing
cutoff. The supported decision dates are 1–31 January 2026; delivery is the
following Europe/London calendar date, including 1 February.

## Current status

Phase 3 implements an in-memory historical data store, cutoff-aware forecast
selection, accuracy metrics, and Flask REST APIs. The backend reads the
processed Phase 2B JSON once at application startup and never calls Elexon from
a request. React, charts, Docker, and deployment remain out of scope.

The Phase 2A local probe verified 48 half-hour WIND actuals for 15 January and
584 WINDFOR rows across eight 14 January publications. At a 12:00 UTC cutoff,
the 11:30 publication supplied 24 delivery targets and all 24 aligned with
complete candidate hourly actuals.

The completed full-month ingestion contains 1,488 FUELHH rows and 19,856
WINDFOR rows with no failed or incomplete batches. At a 12:00 cutoff, all 744
January decision/delivery hours are matched.

## Setup and tests

Python 3.11 or newer is required. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 -m pytest backend/tests -q
```

Elexon uses a public API and no credentials are required.

## Start the Flask backend

```bash
source .venv/bin/activate
python3 backend/run.py
```

The development server listens on `http://127.0.0.1:5000`. It loads processed
JSON at startup; it does not start ingestion.

## REST API

- `GET /api/health` reports service status, data availability, loaded record
  counts, and the supported analysis period.
- `GET /api/forecast?decision_date=2026-01-14&cutoff=12:00` returns the next-day
  selected forecast, actuals, hourly signed errors, metrics, and coverage.
- `GET /api/summary?cutoff=12:00` returns metrics calculated across all matched
  January hours plus daily statistics.

`decision_date` uses `YYYY-MM-DD` and must fall in January 2026. `cutoff` is a
required Europe/London wall-clock time in 24-hour `HH:MM` format.

Example response shape (numbers abbreviated):

```json
{
  "decisionDate": "2026-01-14",
  "deliveryDate": "2026-01-15",
  "cutoff": "12:00",
  "timezone": "Europe/London",
  "selectedForecastPublicationTimes": ["2026-01-14T11:30:00Z"],
  "metrics": {"mae": 1189.792, "rmse": 1289.019, "bias": 1189.792},
  "coverage": {"expectedPeriods": 24, "matchedPeriods": 24},
  "periods": []
}
```

Errors use `forecast - actual`. MAE, RMSE, bias, WAPE, means, maximum absolute
error, and classification counts use matched values only. WAPE is `null` when
the sum of absolute actual generation is zero. Core calculations are unrounded;
API floating-point presentation is rounded to three decimal places.

## Run the validated small scope first

The cutoff is required and interpreted as a `Europe/London` wall-clock time.
The command below downloads only the 14 January decision / 15 January delivery
sample and its bounded forecast lookback:

```bash
python3 backend/scripts/ingest_data.py \
  --decision-start 2026-01-14 \
  --decision-end 2026-01-14 \
  --decision-cutoff 12:00
```

Inspect
`backend/data/processed/reports/validation_2026-01-14_2026-01-14.json` and the
manifest's `WINDFOR:2026-01-14` entry. Confirm 48 actuals, 584 records in that
publication-date batch, 24 selected targets from 11:30 UTC, and 24 candidate
matched hours against the Phase 2A observations before expanding scope.
Use `--refresh` only when an existing successful batch should be downloaded
again.

## Run the complete January decision range

The full range has been ingested successfully. To refresh or reproduce it,
run:

```bash
python3 backend/scripts/ingest_data.py \
  --decision-start 2026-01-01 \
  --decision-end 2026-01-31 \
  --decision-cutoff 12:00
```

Replace `12:00` with the actual procurement cutoff. Re-running the same command
reuses successful daily batches. Failed attempts are recorded and never appear
as successful empty data.

## Storage format

```text
backend/data/
├── manifest.json
├── raw/
│   ├── fuelhh/YYYY-MM-DD.json
│   └── windfor/YYYY-MM-DD.json
└── processed/
    ├── fuelhh/YYYY-MM-DD.json
    ├── windfor/YYYY-MM-DD.json
    └── reports/validation_<start>_<end>.json
```

Raw files retain untouched API rows plus exact requests. Processed files retain
canonical UTC timestamps, original records, provenance, duplicate information,
and warnings. Writes use temporary files and atomic replacement.

## Data and analysis policies

- WINDFOR uses a configurable 72-hour default publication lookback. The
  documented D-to-D+2 horizon shows why decision-date-only retrieval is not
  sufficient. Boundary dependence and missing hourly targets are reported;
  complete history is never assumed.
- WINDFOR revisions remain separate by `(publishTime, startTime)`. Negative
  lead rows remain in raw and processed data for diagnostics.
- FUELHH uses the greatest `publishTime` as a reproducible proxy for the latest
  actual revision because the verified schema has no finality flag. Conflicting
  latest rows are not chosen.
- Candidate hourly actual MW is the mean of complete aligned `HH:00` and
  `HH:30` half-hour average-MW observations. Missing values are not filled.
  This remains provisional pending confirmation of WINDFOR interval semantics.
- For every hourly delivery target, selection uses the greatest historical
  `publishTime` at or before the requested cutoff. Later publications and
  conflicting latest duplicates are never selected.
- Monthly metrics are recalculated from all matched hourly errors; daily metric
  values are not averaged together.

See [data exploration](docs/DATA_EXPLORATION.md),
[architecture](docs/ARCHITECTURE.md), and
[assumptions](docs/ASSUMPTIONS.md) for rationale and limitations.
