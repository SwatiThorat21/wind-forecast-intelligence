# Elexon data exploration

## Scope and verification status

Phase 1 inspected the public Elexon Insights documentation and the published OpenAPI contract for `FUELHH` and `WINDFOR`. The official documentation was reachable, and it confirms that the API is public and requires no API key.

Phase 2A was subsequently run successfully in the project owner's local
environment against January 2026. The observed counts below are empirical for
that bounded sample; they are not a guarantee about every January batch. The
Codex execution sandbox still cannot resolve the Elexon host, so Phase 2B has
not claimed a second live download here.

## Base API and endpoint style

- Base URL: `https://data.elexon.co.uk/bmrs/api/v1`
- Actual source: `GET /datasets/FUELHH/stream`
- Forecast source: `GET /datasets/WINDFOR/stream`
- Authentication: none
- Stream responses: optimized JSON arrays rather than the non-stream endpoint's `{ "data": [...] }` envelope
- Documented errors: HTTP 400 for query errors, 429 for rate limiting, and 500 for server errors
- Pagination: no cursor, page, offset, or limit parameter is defined for either stream endpoint in the inspected OpenAPI contract
- Response-size limits: not stated in the inspected endpoint contract; ingestion should use small bounded windows until behavior is measured

The dataset endpoints expose records as received from the data provider and allow publication-time queries, which is important for retaining superseded forecasts.

## FUELHH: half-hourly outturn

Elexon describes FUELHH as Great Britain generation outturn aggregated by fuel category, updated at 30-minute intervals, with average MW values over each 30-minute period.

### Filters

The stream endpoint defines these optional query parameters:

- `publishDateTimeFrom` and `publishDateTimeTo` (`date-time`)
- `settlementDateFrom` and `settlementDateTo` (`YYYY-MM-DD`)
- repeated/list `settlementPeriod` values
- repeated/list `fuelType` values, including `WIND`

The documentation states that settlement-date fields cannot be combined with publish-date fields. For this MVP, requesting the delivery range by settlement date and filtering to `WIND` is the clearest initial strategy.

Verified request shape:

```text
GET /datasets/FUELHH/stream
    ?settlementDateFrom=2026-01-02
    &settlementDateTo=2026-01-02
    &fuelType=WIND
```

### Documented response shape

This is a schema-shaped example, not observed January data:

```json
[
  {
    "dataset": "FUELHH",
    "publishTime": "<RFC3339 timestamp or null>",
    "startTime": "<RFC3339 timestamp or null>",
    "settlementDate": "<YYYY-MM-DD or null>",
    "settlementPeriod": 1,
    "fuelType": "WIND",
    "generation": 0
  }
]
```

The OpenAPI model permits nullable dataset, time, settlement, fuel, and generation fields, so normalization must validate rather than assume completeness.

## WINDFOR: historical wind forecasts

The raw WINDFOR stream exposes forecast publications, including superseded historical forecasts needed for a decision-time reconstruction.

### Filters

The endpoint defines only:

- `publishDateTimeFrom` (`date-time`)
- `publishDateTimeTo` (`date-time`)

If no publication-time filter is supplied, the documentation says the latest published forecast is returned. There is no raw `startTime` query filter in this endpoint contract. Phase 2B therefore requests bounded publication windows, then filters target `startTime` locally for the required delivery day.

Verified request shape:

```text
GET /datasets/WINDFOR/stream
    ?publishDateTimeFrom=2026-01-01T00:00:00Z
    &publishDateTimeTo=2026-01-01T12:00:00Z
```

### Documented response shape

This is a schema-shaped example, not observed January data:

```json
[
  {
    "dataset": "WINDFOR",
    "publishTime": "<RFC3339 timestamp>",
    "startTime": "<RFC3339 timestamp>",
    "generation": 0
  }
]
```

The OpenAPI model permits `generation` to be null. Its timestamp fields are required by the schema and formatted as date-time. The raw schema does not include settlement date or settlement period; those can be derived from the target instant when needed.

Elexon's higher-level “latest forecast” documentation says wind forecast data can be published up to eight times daily. The raw dataset endpoint remains the appropriate ingestion source because cutoff-aware analysis needs all eligible historical publication records, not a preselected latest view.

## Consequences for ingestion and selection

1. Fetch FUELHH by delivery settlement dates and `fuelType=WIND`.
2. Fetch WINDFOR by publication time, using small windows ending at each decision cutoff (or a safely bounded consolidated range).
3. Parse all timestamps as aware instants and store canonical UTC.
4. Filter WINDFOR targets to the relevant delivery interval after retrieval.
5. Group forecast rows by target `startTime`; within each group retain `publishTime <= cutoff`, then choose the maximum `publishTime`.
6. Join the selection to FUELHH on canonical `startTime` and preserve unmatched periods.

Because the WINDFOR query is publication-based, querying only the delivery date would be incorrect: a next-day target is normally forecast before delivery begins.

## Duplicate and missing-data handling

The contract does not promise uniqueness or complete half-hour coverage. Phase 2 should profile keys before deciding a final deduplication rule:

- FUELHH candidate key: `(startTime, fuelType)` plus publication/revision context if multiple records exist;
- WINDFOR candidate key: `(startTime, publishTime)`;
- exact duplicate count and conflicting-value count;
- nulls in required analytical fields;
- expected versus observed delivery periods;
- ordering of returned rows;
- whether date/publish range endpoints are inclusive at both boundaries.

No missing value should be converted to zero. Conflicts should be retained or quarantined with an explicit quality report.

## Phase 2A live probe results

The locally executed probe established the following for its bounded sample:

- FUELHH returned 48 WIND rows for 15 January 2026 at 30-minute target intervals.
- No duplicate `(startTime, fuelType)` key occurred in that sample.
- WINDFOR returned 584 rows in the 14 January publication window, comprising
  eight distinct publication timestamps and hourly target timestamps.
- 120 WINDFOR rows had negative lead time and 464 had positive lead time.
- No duplicate `(publishTime, startTime)` key occurred in that sample.
- At a 14 January 12:00 UTC decision cutoff, the latest eligible publication
  was 11:30 UTC. There were 24 selected delivery targets, 24 complete hourly
  actual aggregates, and 24 matched hour starts for 15 January.

The probe's single publication date does not prove that earlier publications
are unnecessary for every cutoff. In particular, a cutoff before the first
same-day publication can depend on a previous day's forecast.

The 15 January FUELHH sample exposed one row per settlement period and no
duplicate `(startTime, fuelType)` keys. Neither the verified API schema nor the
sample provides a finality indicator, so it remains unproven whether a
settlement-date query exposes every historical outturn revision. Phase 2B keeps
all versions it receives and uses greatest `publishTime` only as an explicit
latest-available proxy; a later retrieval snapshot may still differ.

## Publication lookback investigation and policy

Official BSC material describes WINDFOR coverage as D through D+2 and the
current Elexon endpoint documents up to eight publications per day. This means
that a next-day target may have been published before the decision date. A
decision-date-only query is therefore insufficient by construction.

Phase 2B uses a default **72-hour lookback before the decision cutoff**. Daily
UTC request batches span the UTC date containing that boundary through the
decision date, so the first batch may include some additional hours. This is a
bounded and deliberately conservative window: it covers the documented D to
D+2 horizon and adds room to observe boundary dependence. The validation
report counts relevant delivery targets found in the oldest 24 hours. A
non-zero count is an explicit signal to investigate a longer window before
claiming complete historical coverage.

This duration is evidence-based but completeness is not guaranteed. Only the
full ingestion report can establish observed coverage for all configured
cutoffs, and missing targets remain missing.

## Earlier probe checklist retained for reproducibility

Run these as small, read-only calls before downloading the January window:

1. One FUELHH settlement date with `fuelType=WIND`; capture status, headers, row count, first/last target, and fields.
2. A 30–60 minute FUELHH publication window to compare publication filtering with settlement filtering.
3. A short WINDFOR publication window around one documented publication cycle; inspect multiple target times per publication.
4. Two adjacent windows sharing a boundary to determine range inclusivity and prevent duplicate ingestion.
5. A deliberately invalid parameter combination to record the 400 response shape.
6. Checks for stable ordering, exact duplicates, conflicting `(startTime, publishTime)` rows, nulls, and forecast horizon.
7. A request large enough to discover practical response-size behavior, while remaining far smaller than the full assignment dataset.

## Unresolved questions

- Whether any January decision depends on publications at the 72-hour boundary;
  the full validation report must answer this empirically.
- Are `publishDateTimeFrom` and `publishDateTimeTo` inclusive, exclusive, or mixed in live behavior?
- Does FUELHH contain revisions for the same wind `startTime`, and which publication represents the intended final outturn?
- Can WINDFOR contain exact or conflicting duplicate `(startTime, publishTime)` records?
- Are results returned in a stable order?
- Are there January 2026 gaps or null generation values in either series?
- Is WINDFOR `generation` explicitly documented as MW outside the schema context?
- What undocumented maximum window, payload size, timeout, or throttling behavior applies?
- Should the business prefer one coherent forecast publication curve, or the latest eligible row independently per target period? The assignment wording supports per-period selection, which is the current assumption.

## Sources inspected

- Elexon Insights API documentation: `https://bmrs.elexon.co.uk/api-documentation/endpoint`
- FUELHH stream documentation: `https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream`
- WINDFOR stream documentation: `https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream`
- Elexon developer documentation repository: `https://github.com/elexon-data/insights-docs`
- Published OpenAPI endpoint: `https://data.elexon.co.uk/swagger/v1/swagger.json` (direct access blocked in this environment; its mirrored contract was inspected)

The OpenAPI mirror used to inspect exact parameter and schema definitions is maintained outside Elexon. Phase 2 should compare it with Elexon's live OpenAPI document when network access is available.

## Phase 2A timestamp and resolution investigation

### Browser-verified January field structures

The following structures were supplied from successful, direct browser requests. They are real January 2026 examples rather than OpenAPI placeholders:

```json
{
  "dataset": "FUELHH",
  "publishTime": "2026-01-15T23:30:00Z",
  "startTime": "2026-01-15T23:00:00Z",
  "settlementDate": "2026-01-15",
  "settlementPeriod": 47,
  "fuelType": "WIND",
  "generation": 7258
}
```

```json
{
  "dataset": "WINDFOR",
  "publishTime": "2026-01-14T22:30:00Z",
  "startTime": "2026-01-13T21:00:00Z",
  "generation": 12079
}
```

The FUELHH row is consistent with a half-hour average MW reading for the interval beginning at `startTime`: settlement period 47 begins at 23:00 GMT and the row was published at 23:30. Both `generation` fields are numeric MW according to Elexon's FUELHH and WINDFOR interface descriptions.

### Negative WINDFOR lead times

Forecast lead time is defined as:

```text
lead_time = startTime - publishTime
```

The supplied WINDFOR example has a lead time of `-25.5 hours`, so it cannot represent a forecast that was available before that target. Elexon's interface definition explains that an updated WINDFOR message can additionally include previously received forecast values from the current day onward. Elexon also describes WINDFOR coverage as extending from day D to D+2. This provides a plausible documented reason for an archived publication batch to contain already-passed targets.

The exact relationship between the modern Insights row-level `publishTime` and the legacy message's per-period publishing time still needs confirmation from Elexon. Regardless of that semantic detail, rows with `startTime < publishTime` must be counted and retained for data-quality reporting but excluded from day-ahead selection.

Zero lead-time rows are not negative, but they are not day-ahead evidence either. The probe reports them separately rather than treating them as positive-lead forecasts.

### Expected time resolutions

- FUELHH is documented and browser-observed as half-hourly average MW. A normal January day should produce consecutive target starts 30 minutes apart.
- Elexon documentation describes WINDFOR values provided for each hour, and the supplied example lies on an hourly boundary.
- This supports an expectation of hourly WINDFOR targets, but consistency across the January 14 sample remains an empirical question.
- Publication frequency and target frequency are different concepts. Multiple publication batches may repeat the same hourly targets with updated values.

`backend/scripts/probe_elexon.py` reports target deltas both across all unique WINDFOR targets and separately within each `publishTime` batch. It also reports exact duplicate `(publishTime, startTime)` rows and targets repeated across different publications. Repetition across publications is expected forecast evolution and must not be mistaken for a duplicate.

### Candidate hourly comparison

If the probe confirms hourly WINDFOR targets and 30-minute FUELHH readings, the least-assumptive resolution match is hourly:

1. Treat a FUELHH `startTime` at `HH:00` as the beginning of the first half-hour window.
2. Require another valid FUELHH reading at `HH:30`.
3. Calculate the hour's actual average MW as `(actual_HH:00 + actual_HH:30) / 2`.
4. Compare it only with a selected WINDFOR target aligned to that same hour start.
5. If either half-hour is absent or conflicting, mark that hour incomplete and exclude it from metrics.

This calculation is dimensionally sound because the mean of two equal-duration average-MW readings is the average MW over their combined hour. It is preferable to repeating, forward-filling, or interpolating an hourly forecast into fabricated half-hour values: those approaches create forecast observations Elexon never published, overstate sample size, and can distort error metrics.

One semantic check remains: Elexon describes hourly forecast values at specified times, but the inspected materials do not conclusively state whether each value is an average over the following hour or a point forecast at the timestamp. Hourly-average comparison should therefore remain provisional until this is confirmed. The probe reports aligned candidates but does not calculate accuracy metrics.

### Historical selection demonstration

For a January 14 decision and January 15 delivery, selection must operate as follows:

1. Convert the configured January 14 `Europe/London` cutoff to a UTC instant.
2. Retain targets whose London calendar date is January 15.
3. Exclude records with `publishTime > cutoff`.
4. Exclude records with `startTime < publishTime` from day-ahead analysis.
5. Group the remainder by target `startTime`.
6. Select the maximum eligible `publishTime` per target.
7. If the latest key has conflicting generation values, report the conflict rather than choosing silently.

The Phase 2A probe implements that algorithm over its bounded January 14 publication sample. This is a demonstration, not a complete historical selection: a production selection window must extend far enough backward to find earlier eligible publications for any targets absent from the sampled day.

### Running the Phase 2A probe

From the repository root, with Python 3.11+ and `requests` installed:

```bash
python3 -m pip install requests
python3 backend/scripts/probe_elexon.py \
  --decision-cutoff 2026-01-14T12:00:00+00:00
```

The cutoff above is an explicit example, not the application's business default. Substitute the actual procurement cutoff being evaluated. The script uses bounded requests, connection/read timeouts, timezone-aware parsing, compact summaries, and no file writes.

The project owner executed this probe successfully and supplied the verified
counts recorded above. Codex cannot independently repeat the live call in its
current network-restricted environment.

### Remaining limitations

- Run the full ingestion locally before deciding that all January WINDFOR batches are hourly or complete.
- Confirm whether `publishDateTimeTo` includes midnight at the next boundary; adjacent probe windows may overlap.
- Confirm the modern Insights meaning of WINDFOR `publishTime` for carried-forward past targets.
- Confirm whether WINDFOR values represent an hourly average or a point value at the named time.
- Establish a publication lookback window that captures earlier eligible candidates when a target is absent from the decision day's publications.
- Determine a revision policy if FUELHH returns more than one value for the same wind target.
- Do not interpolate, repeat, or zero-fill missing forecast or actual values.
