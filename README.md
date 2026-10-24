# Wind Forecast Intelligence

Wind Forecast Intelligence is a decision-support project for evaluating the
national wind forecast available at a configurable day-ahead purchasing
cutoff. The supported decision dates are 1–31 January 2026; delivery is the
following Europe/London calendar date, including 1 February.

## Current status

Phase 2B implements historical Elexon ingestion, normalization, provenance,
validation, and provisional half-hour-to-hour actual alignment. It deliberately
does **not** include Flask routes, forecast selection APIs, accuracy metrics,
React components, charts, or deployment configuration.

The Phase 2A local probe verified 48 half-hour WIND actuals for 15 January and
584 WINDFOR rows across eight 14 January publications. At a 12:00 UTC cutoff,
the 11:30 publication supplied 24 delivery targets and all 24 aligned with
complete candidate hourly actuals.

## Setup and tests

Python 3.11 or newer is required. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 -m pytest backend/tests -q
```

Elexon uses a public API and no credentials are required.

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

This is intentionally a separate, explicit command and was not automatically
run during Phase 2B development:

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

## Key Phase 2B policies

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

See [data exploration](docs/DATA_EXPLORATION.md),
[architecture](docs/ARCHITECTURE.md), and
[assumptions](docs/ASSUMPTIONS.md) for rationale and limitations.
