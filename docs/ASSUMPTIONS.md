# Assumptions and decisions

## Analysis window

- A **decision date** is a local UK calendar date from 1 January through 31 January 2026, inclusive.
- A decision date identifies when the procurement decision was made; it is not the forecast target date.
- The **delivery date** is the next local calendar day. Therefore supported delivery dates are 2 January through 1 February 2026, inclusive.
- January 31 is valid even though its delivery periods fall outside January.
- The product analyzes national-level wind only. It does not infer regional generation, embedded wind, prices, purchased volumes, or procurement cost.

## Configurable decision cutoff

- The assignment does not define the purchasing cutoff, so it must be configuration rather than an implicit constant.
- The cutoff consists of a local wall-clock time and the `Europe/London` timezone.
- The UI and API response must show the effective cutoff used.
- No business default has been agreed. Phase 3 therefore requires an explicit
  `cutoff=HH:MM` query parameter rather than presenting a convenient time as an
  Elexon rule.
- Changing the cutoff changes forecast eligibility and therefore can change every reported metric.

## Time handling

- User-facing decision and delivery times use IANA timezone `Europe/London`.
- Source timestamps must be parsed as timezone-aware values and normalized to UTC for storage, comparison, and joins.
- January and 1 February 2026 are on GMT (`UTC+00:00`), but code will not rely on that seasonal coincidence.
- Delivery-day boundaries will be constructed in `Europe/London` and converted to UTC. This keeps the approach correct for future daylight-saving dates with 46 or 50 settlement periods.
- Naive or invalid timestamps are rejected or quarantined during ingestion rather than assigned an assumed timezone silently.

## Forecast eligibility and selection

- `startTime` is the target generation period.
- `publishTime` is when that forecast became available.
- A row is eligible only when its target belongs to the next-day delivery interval and `publishTime <= decision cutoff`.
- For each hourly target, Phase 3 chooses the eligible row with the maximum `publishTime`.
- The equality case is eligible because the rule says “at or before” the cutoff.
- Selection occurs independently for every target period; a delivery-day curve may therefore contain rows from more than one publication if source coverage differs.
- No later publication may be used to fill a gap. A period with no eligible forecast remains missing.
- Actual and selected forecast values are matched on normalized UTC `startTime`.
- WINDFOR rows with `startTime < publishTime` are retained for diagnostics but excluded from day-ahead selection because the target had already begun before that publication.
- Zero lead-time rows are reported separately and are not assumed to be day-ahead forecasts.

## Phase 3 metrics

- Error and bias use `forecast - actual`; positive mean bias indicates over-forecasting.
- MAE, RMSE, bias, and WAPE are calculated only from hours with both a valid selected forecast and a valid actual value.
- WAPE is `sum(abs(forecast - actual)) / sum(abs(actual)) * 100` and is undefined for a zero denominator.
- Coverage and counts accompany metrics so a deceptively good score over partial data is visible.
- Missing values are not converted to zero and are not interpolated in the MVP.
- If WINDFOR is confirmed to be hourly, comparison will use only complete aligned actual hours: the mean of the FUELHH `HH:00` and `HH:30` average-MW readings. An hour with either half missing is excluded rather than imputed.
- The hourly method remains provisional until Elexon's target semantics are confirmed as comparable to an average over the same hourly window.
- Mean forecast MW, mean actual MW, maximum absolute error, overforecast,
  underforecast, exact-match, matched, and missing counts are also returned.
- Monthly metrics aggregate all matched hourly observations directly. They are
  not an unweighted average of daily metrics.

## Data quality and lineage

- FUELHH `WIND` generation is treated as the requested national outturn series and as average MW for the half-hour, based on the Elexon contract.
- WINDFOR generation is treated as MW based on the Elexon interface definition;
  its precise hourly interval-versus-point semantics remain unresolved.
- Raw records and retrieval metadata are retained so processed results can be reproduced.
- Byte-identical duplicates may be deduplicated with counts retained. Conflicting duplicate keys must produce a data-quality warning until a source revision rule is verified.
- Missing source periods, revised outturn, forecast gaps, and API limitations must be reported, not fabricated or silently imputed.

## Forecast publication lookback

- Phase 2B defaults to a 72-hour lookback before each Europe/London decision
  cutoff. Requests are stored as UTC publication-date batches.
- The duration follows the documented WINDFOR D through D+2 horizon and is
  intentionally broader than the decision date alone.
- The oldest batch is audited for relevant delivery targets. If relevant rows
  occur in the oldest 24 hours, the report flags that earlier publication data
  may be required.
- A bounded window is not treated as proof of complete source coverage. Every
  decision date receives an explicit missing-hour count.
- The completed January ingestion found no delivery target dependent on the
  oldest 24 hours of the lookback and provided 24 eligible targets for every
  decision date at the verified 12:00 cutoff. Other cutoff values are evaluated
  dynamically and may have different coverage.

## Actual-generation revision policy

- The verified FUELHH schema has `publishTime` but no reliable finality flag.
- Raw versions are retained. For candidate historical evaluation, Phase 2B
  selects the greatest non-null `publishTime` for each `startTime` as a proxy
  for the latest available actual.
- If multiple rows at that latest publication conflict, no arbitrary value is
  selected and the hour remains unavailable. A lone version without
  `publishTime` may be used; multiple undated versions are unresolved.
- This is a reproducible revision policy, not a claim that the selected value
  is settlement-final. Retrieval time and original records remain available
  for audit.

## Known limitations

- The forecast represents wind farms visible to the system operator with operational metering; it may not represent all physical UK wind output.
- Forecast accuracy is not the same as procurement financial impact because the MVP has no purchase volumes or market prices.
- Historical source data can be revised after the operational decision. The MVP must preserve retrieval provenance and disclose which outturn extract was used.
- The full January download had no gaps at the 12:00 cutoff, but this does not
  guarantee complete coverage for every possible cutoff.
- WINDFOR interval semantics remain an assumption even though the records are
  hourly. API responses include this methodology disclosure.
