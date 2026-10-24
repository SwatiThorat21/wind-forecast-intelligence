# Wind Forecast Intelligence

Wind Forecast Intelligence is a decision-support project for evaluating the
national wind forecast available at a configurable day-ahead purchasing
cutoff. The supported decision dates are 1–31 January 2026; delivery is the
following Europe/London calendar date, including 1 February.

## Current status

Phase 5 packages the completed React/Vite dashboard and Flask analysis API for
repeatable local containers and public deployment preparation. The backend runs
under Gunicorn, the frontend is built as static assets, CORS is origin-limited,
and the verified processed Elexon dataset is packaged with the API. No service
performs ingestion or live Elexon requests while serving dashboard traffic.

The Phase 2A local probe verified 48 half-hour WIND actuals for 15 January and
584 WINDFOR rows across eight 14 January publications. At a 12:00 UTC cutoff,
the 11:30 publication supplied 24 delivery targets and all 24 aligned with
complete candidate hourly actuals.

The completed full-month ingestion contains 1,488 FUELHH rows and 19,856
WINDFOR rows with no failed or incomplete batches. At a 12:00 cutoff, all 744
January decision/delivery hours are matched.

## Local development setup

Python 3.11 or newer is required. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 -m pytest backend/tests -q
```

Elexon uses a public API and no credentials are required.

## Frontend setup

From the repository root:

```bash
cd frontend
npm install
cp .env.example .env.development.local
npm run dev
```

The Vite development server is available at `http://127.0.0.1:5173`.

Frontend environment variables:

```text
VITE_API_BASE_URL=http://127.0.0.1:5000
VITE_API_PROXY_TARGET=http://127.0.0.1:5000
```

`VITE_API_BASE_URL` selects the browser API origin. As an alternative during
development, set it to `/api` to use the Vite proxy and configure the proxy
target with `VITE_API_PROXY_TARGET`.

## Start the Flask backend

```bash
source .venv/bin/activate
python3 backend/run.py
```

The development server listens on `http://127.0.0.1:5000`. Debug mode is off by
default. It loads processed JSON once at startup; it does not start ingestion.

For local development, use two terminals:

```bash
# Terminal 1
source .venv/bin/activate
python3 backend/run.py

# Terminal 2
cd frontend
npm run dev
```

The backend permits browser requests only from explicitly configured origins.
The defaults are `http://127.0.0.1:5173` and `http://localhost:5173`. Override
them with a comma-separated `CORS_ALLOWED_ORIGINS` environment variable.

## Environment variables

| Variable | Used by | Purpose |
| --- | --- | --- |
| `PORT` | Backend | Gunicorn/Flask listen port; defaults to `5000` in the container and is supplied by Render. |
| `HISTORICAL_DATA_ROOT` | Backend | Absolute processed-data directory; defaults to `backend/data/processed` outside containers. |
| `FAIL_ON_DATA_LOAD_ERROR` | Backend | Set to `true` in production so missing or corrupt historical files stop startup. |
| `CORS_ALLOWED_ORIGINS` | Backend | Comma-separated, exact browser origins allowed to call the API. Do not use `*` in production. |
| `FLASK_DEBUG` | Local backend only | Optional local debug switch; it is unset/false in production. |
| `VITE_API_BASE_URL` | Frontend build | Public backend origin, for example `https://wind-forecast-api.onrender.com`. |
| `VITE_API_PROXY_TARGET` | Vite development only | Local target for requests made through Vite's `/api` proxy. |

Vite variables are embedded at build time and must not contain secrets. This
project requires no API key. For public builds, set `VITE_API_BASE_URL` to the
deployed HTTPS backend origin, never a localhost value. As a safety guard, a
production build ignores a loopback API value and falls back to same-origin
`/api`; Vercel should always receive the explicit Render origin.

## Docker setup

Docker Compose builds a Gunicorn backend and an Nginx-served frontend. Nginx
proxies same-origin `/api` requests to the backend container, so the browser UI
is available at `http://127.0.0.1:3000` and the API remains directly available
at `http://127.0.0.1:5000` for diagnostics.

```bash
docker compose build
docker compose up -d
docker compose ps

curl http://127.0.0.1:5000/api/health
curl 'http://127.0.0.1:5000/api/forecast?decision_date=2026-01-14&cutoff=12:00'
curl 'http://127.0.0.1:5000/api/summary?cutoff=12:00'
```

Inspect and stop the stack with:

```bash
docker compose logs -f
docker compose down
```

To build only the backend image from the repository root:

```bash
docker build -f backend/Dockerfile -t wind-forecast-backend .
docker run --rm -p 5000:5000 \
  -e CORS_ALLOWED_ORIGINS=http://127.0.0.1:5173 \
  wind-forecast-backend
```

The backend image contains `backend/data/processed` but excludes raw API
responses, the mutable ingestion manifest, tests, virtual environments, caches,
and secrets. The application runs as an unprivileged user. Its production
command is:

```text
gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 120 backend.run:app
```

## Production architecture

```text
Browser
  ├── Vercel: static React/Vite assets
  └── HTTPS JSON requests
        └── Render: Gunicorn → Flask application factory
              └── in-memory indexes loaded once from packaged processed JSON
```

Changing a date or cutoff reuses the loaded publication history. The API does
not download data, write runtime data, or require a database. Invalid inputs and
data-availability failures retain the API's structured JSON error format.

## Deploy the backend to Render

Deployment is prepared but is not performed automatically. After placing the
reviewed repository in a Git provider:

1. In Render, choose **New → Blueprint** and select the repository. The root
   `render.yaml` selects the Docker runtime, `backend/Dockerfile`, repository
   build context, and `/api/health` health check.
2. Set `CORS_ALLOWED_ORIGINS` to the exact Vercel production origin, such as
   `https://wind-forecast-intelligence.vercel.app` (no trailing slash). Add any
   preview origin explicitly if it should be trusted.
3. Keep `HISTORICAL_DATA_ROOT=/app/backend/data/processed` and
   `FAIL_ON_DATA_LOAD_ERROR=true`. Render provides `PORT`; do not hardcode it.
4. Create the service and confirm `/api/health` reports `status: "ok"` before
   connecting the frontend.

For a manual Render Web Service instead of the Blueprint, use:

- Runtime: **Docker**
- Repository root/build context: `.`
- Dockerfile: `backend/Dockerfile`
- Health check path: `/api/health`
- Gunicorn start command: supplied by the Dockerfile `CMD` shown above

All files below `backend/data/processed/fuelhh` and
`backend/data/processed/windfor` are required deployment inputs. They must be
present in the deployed revision; startup intentionally fails if they are
missing or corrupt. Raw files are not needed by Render.

## Deploy the frontend to Vercel

1. Import the same repository into Vercel.
2. Set **Root Directory** to `frontend`.
3. Use framework preset **Vite**, build command `npm run build`, and output
   directory `dist`.
4. Add `VITE_API_BASE_URL=https://<your-render-service>.onrender.com` to the
   Production environment (and Preview if desired).
5. Deploy or redeploy so the build receives that variable.
6. Copy the final Vercel origin into Render's `CORS_ALLOWED_ORIGINS`, then
   restart the backend and verify the dashboard in the browser.

`frontend/vercel.json` provides SPA fallback routing. The production bundle
contains only the public API origin and no credentials or API keys.

## Dashboard features

- January portfolio MAE, RMSE, bias, WAPE, and matched-data coverage cards.
- Decision date and Europe/London purchasing-cutoff controls.
- Interactive hourly forecast-versus-actual chart with signed errors.
- January daily MAE trend and over/underforecast distribution.
- Selected-day metrics and a scrollable 24-hour audit table.
- Explicit loading, API error, empty-data, and partial-coverage states.
- Responsive desktop, tablet, and mobile layouts with accessible labels and
  keyboard-operable controls.

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

For deployment, the processed files are the canonical packaged runtime input.
The raw directory and manifest support local reproducibility but are excluded
from container build contexts and new Git additions to keep deployments small.

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

## Known limitations

- The dashboard covers January 2026 decision dates only.
- Hourly actuals use complete pairs of FUELHH half-hour readings; WINDFOR
  interval semantics remain a documented assumption.
- Forecast accuracy is not a financial-impact measure because electricity
  prices and purchasing volumes are not included.
- The frontend is a read-only analytical client and does not trigger ingestion.
- The January 2026 processed dataset is packaged into the backend image; adding
  another analysis period requires a new ingestion run and image deployment.
- Render free-tier services, if selected, may cold-start; this is hosting
  behavior rather than missing historical data.

## AI-assisted development disclosure

OpenAI Codex was used as an AI-assisted development tool for implementation,
review, tests, documentation, and deployment preparation. The project owner is
responsible for reviewing the code and deployment configuration. Dashboard
runtime values come from the packaged historical Elexon dataset; synthetic data
is restricted to isolated tests and is not presented as production history.
