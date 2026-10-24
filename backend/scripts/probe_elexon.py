#!/usr/bin/env python3
"""Run small, read-only probes against Elexon FUELHH and WINDFOR.

This is an exploratory script, not the historical ingestion pipeline. It prints
compact summaries and does not persist API payloads or interpolate values.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

import requests


BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
FUELHH_PATH = "/datasets/FUELHH/stream"
WINDFOR_PATH = "/datasets/WINDFOR/stream"
FUELHH_DATE = date(2026, 1, 15)
WINDFOR_PUBLICATION_DATE = date(2026, 1, 14)
DELIVERY_DATE = date(2026, 1, 15)
LONDON = ZoneInfo("Europe/London")


class ProbeError(RuntimeError):
    """Raised when a bounded Elexon probe cannot be completed safely."""


@dataclass(frozen=True)
class ParsedForecast:
    record: dict[str, Any]
    publish_time: datetime
    start_time: datetime

    @property
    def lead_time(self) -> timedelta:
        return self.start_time - self.publish_time


def parse_timestamp(value: Any, field_name: str) -> datetime:
    """Parse an ISO 8601 timestamp and require an explicit UTC offset."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware: {value!r}")
    return parsed.astimezone(timezone.utc)


def fetch_records(
    session: requests.Session,
    path: str,
    params: Sequence[tuple[str, str]],
    timeout: tuple[float, float],
) -> list[dict[str, Any]]:
    """Fetch one small JSON result set and validate its top-level shape."""
    url = f"{BASE_URL}{path}"
    try:
        response = session.get(url, params=params, timeout=timeout)
        response.raise_for_status()
    except requests.Timeout as exc:
        raise ProbeError(f"Timed out requesting {url}: {exc}") from exc
    except requests.ConnectionError as exc:
        raise ProbeError(f"Could not connect to {url}: {exc}") from exc
    except requests.HTTPError as exc:
        body = exc.response.text[:500] if exc.response is not None else ""
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise ProbeError(f"Elexon returned HTTP {status} for {url}: {body}") from exc
    except requests.RequestException as exc:
        raise ProbeError(f"Request failed for {url}: {exc}") from exc

    try:
        payload = response.json()
    except requests.JSONDecodeError as exc:
        raise ProbeError(
            f"Elexon returned non-JSON content for {response.url}: "
            f"{response.text[:500]}"
        ) from exc

    # Stream endpoints should return a bare list. Accepting a data envelope makes
    # the diagnostic useful if Elexon routes the request through a non-stream shape.
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        payload = payload["data"]
    if not isinstance(payload, list):
        raise ProbeError(
            f"Unexpected response shape from {response.url}: "
            f"expected list, received {type(payload).__name__}"
        )
    if not all(isinstance(record, dict) for record in payload):
        raise ProbeError(f"Response from {response.url} contains non-object records")

    print(f"Fetched {len(payload)} records from {response.url}")
    return payload


def interval_counts(timestamps: Iterable[datetime]) -> Counter[float]:
    unique = sorted(set(timestamps))
    return Counter(
        round((later - earlier).total_seconds() / 60, 6)
        for earlier, later in zip(unique, unique[1:])
    )


def parse_record_times(
    records: Sequence[dict[str, Any]], field_name: str
) -> tuple[list[datetime], list[str]]:
    parsed: list[datetime] = []
    errors: list[str] = []
    for index, record in enumerate(records):
        try:
            parsed.append(parse_timestamp(record.get(field_name), field_name))
        except (TypeError, ValueError) as exc:
            errors.append(f"record {index}: {exc}")
    return parsed, errors


def analyse_fuelhh(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    starts, errors = parse_record_times(records, "startTime")
    key_counts = Counter(
        (record.get("startTime"), record.get("fuelType")) for record in records
    )
    duplicate_keys = sum(count - 1 for count in key_counts.values() if count > 1)
    return {
        "record_count": len(records),
        "datasets": sorted({str(record.get("dataset")) for record in records}),
        "fuel_types": sorted({str(record.get("fuelType")) for record in records}),
        "start_interval_minutes": dict(sorted(interval_counts(starts).items())),
        "duplicate_start_and_fuel_rows": duplicate_keys,
        "timestamp_error_count": len(errors),
        "timestamp_error_examples": errors[:5],
        "sample": records[:1],
    }


def parse_forecasts(
    records: Sequence[dict[str, Any]],
) -> tuple[list[ParsedForecast], list[str]]:
    parsed: list[ParsedForecast] = []
    errors: list[str] = []
    for index, record in enumerate(records):
        try:
            parsed.append(
                ParsedForecast(
                    record=record,
                    publish_time=parse_timestamp(record.get("publishTime"), "publishTime"),
                    start_time=parse_timestamp(record.get("startTime"), "startTime"),
                )
            )
        except (TypeError, ValueError) as exc:
            errors.append(f"record {index}: {exc}")
    return parsed, errors


def analyse_windfor(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    forecasts, errors = parse_forecasts(records)
    lead_categories = Counter(
        "positive" if row.lead_time > timedelta(0) else
        "negative" if row.lead_time < timedelta(0) else
        "zero"
        for row in forecasts
    )
    publication_times = sorted({row.publish_time for row in forecasts})
    targets_by_publication: dict[datetime, list[datetime]] = defaultdict(list)
    for row in forecasts:
        targets_by_publication[row.publish_time].append(row.start_time)

    batch_intervals = {
        publish_time.isoformat(): dict(sorted(interval_counts(targets).items()))
        for publish_time, targets in sorted(targets_by_publication.items())
    }
    pair_counts = Counter(
        (row.publish_time, row.start_time) for row in forecasts
    )
    duplicate_pairs = sum(count - 1 for count in pair_counts.values() if count > 1)
    target_publication_counts: dict[datetime, set[datetime]] = defaultdict(set)
    for row in forecasts:
        target_publication_counts[row.start_time].add(row.publish_time)

    leads = [row.lead_time.total_seconds() / 3600 for row in forecasts]
    negative_examples = [
        {
            "publishTime": row.record.get("publishTime"),
            "startTime": row.record.get("startTime"),
            "lead_hours": round(row.lead_time.total_seconds() / 3600, 3),
            "generation": row.record.get("generation"),
        }
        for row in forecasts
        if row.lead_time < timedelta(0)
    ][:5]

    return {
        "record_count": len(records),
        "valid_timestamp_record_count": len(forecasts),
        "lead_time_counts": {
            category: lead_categories.get(category, 0)
            for category in ("positive", "zero", "negative")
        },
        "lead_hours_min": round(min(leads), 3) if leads else None,
        "lead_hours_max": round(max(leads), 3) if leads else None,
        "distinct_publication_count": len(publication_times),
        "publication_times": [value.isoformat() for value in publication_times],
        "overall_unique_target_interval_minutes": dict(
            sorted(interval_counts(row.start_time for row in forecasts).items())
        ),
        "target_interval_minutes_by_publication": batch_intervals,
        "duplicate_publish_and_target_rows": duplicate_pairs,
        "targets_repeated_across_publications": sum(
            len(publications) > 1
            for publications in target_publication_counts.values()
        ),
        "negative_lead_examples": negative_examples,
        "timestamp_error_count": len(errors),
        "timestamp_error_examples": errors[:5],
        "sample": records[:1],
    }


def select_delivery_forecasts(
    records: Sequence[dict[str, Any]],
    cutoff: datetime,
    delivery_date: date,
) -> tuple[dict[datetime, ParsedForecast], list[str], dict[str, int]]:
    """Select latest eligible rows per target within the sampled records.

    Conflicting records at the same latest publication and target are not selected.
    """
    parsed, parse_errors = parse_forecasts(records)
    eligible: dict[datetime, list[ParsedForecast]] = defaultdict(list)
    counts = Counter()

    for row in parsed:
        if row.start_time.astimezone(LONDON).date() != delivery_date:
            counts["excluded_wrong_delivery_date"] += 1
            continue
        if row.publish_time > cutoff:
            counts["excluded_after_cutoff"] += 1
            continue
        if row.start_time < row.publish_time:
            counts["excluded_negative_lead"] += 1
            continue
        eligible[row.start_time].append(row)

    selected: dict[datetime, ParsedForecast] = {}
    conflicts: list[str] = []
    for target, candidates in sorted(eligible.items()):
        latest_publish = max(candidate.publish_time for candidate in candidates)
        latest = [
            candidate for candidate in candidates
            if candidate.publish_time == latest_publish
        ]
        generations = {candidate.record.get("generation") for candidate in latest}
        if len(generations) > 1:
            conflicts.append(
                f"{target.isoformat()}: conflicting generation values at "
                f"{latest_publish.isoformat()}: {sorted(map(str, generations))}"
            )
            counts["excluded_conflicting_latest_rows"] += 1
            continue
        selected[target] = latest[0]

    counts["selected_targets"] = len(selected)
    counts["parse_errors"] = len(parse_errors)
    return selected, parse_errors + conflicts, dict(counts)


def aggregate_complete_actual_hours(
    records: Sequence[dict[str, Any]],
) -> tuple[dict[datetime, float], list[str]]:
    """Average two half-hour MW readings only for complete aligned UTC hours."""
    by_start: dict[datetime, list[float]] = defaultdict(list)
    warnings: list[str] = []

    for index, record in enumerate(records):
        try:
            start = parse_timestamp(record.get("startTime"), "startTime")
            generation = record.get("generation")
            if not isinstance(generation, (int, float)) or isinstance(generation, bool):
                raise ValueError("generation must be numeric")
            by_start[start].append(float(generation))
        except (TypeError, ValueError) as exc:
            warnings.append(f"record {index}: {exc}")

    # Conflicting revisions cannot be averaged safely in this exploratory step.
    unique: dict[datetime, float] = {}
    for start, values in by_start.items():
        if len(set(values)) == 1:
            unique[start] = values[0]
        else:
            warnings.append(
                f"{start.isoformat()}: conflicting actual values {sorted(set(values))}"
            )

    hourly: dict[datetime, float] = {}
    for start, first_value in sorted(unique.items()):
        if start.minute != 0 or start.second != 0 or start.microsecond != 0:
            continue
        second_start = start + timedelta(minutes=30)
        if second_start in unique:
            hourly[start] = (first_value + unique[second_start]) / 2
    return hourly, warnings


def comparison_summary(
    selected: dict[datetime, ParsedForecast],
    actual_hourly: dict[datetime, float],
) -> dict[str, Any]:
    matched = sorted(set(selected) & set(actual_hourly))
    return {
        "selected_forecast_targets": len(selected),
        "complete_actual_hours": len(actual_hourly),
        "matched_hour_starts": len(matched),
        "unmatched_forecast_targets": len(set(selected) - set(actual_hourly)),
        "unmatched_actual_hours": len(set(actual_hourly) - set(selected)),
        "match_examples": [
            {
                "hour_start": target.isoformat(),
                "forecast_mw": selected[target].record.get("generation"),
                "actual_hourly_mean_mw": actual_hourly[target],
                "forecast_publish_time": selected[target].publish_time.isoformat(),
            }
            for target in matched[:5]
        ],
    }


def print_section(title: str, value: Any) -> None:
    print(f"\n{title}")
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def parse_cutoff(value: str) -> datetime:
    parsed = parse_timestamp(value, "decision cutoff")
    local = parsed.astimezone(LONDON)
    if local.date() != date(2026, 1, 14):
        raise argparse.ArgumentTypeError(
            "the Phase 2A demonstration cutoff must fall on 2026-01-14 in Europe/London"
        )
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--decision-cutoff",
        required=True,
        type=parse_cutoff,
        help=(
            "Timezone-aware cutoff on 2026-01-14, for example "
            "2026-01-14T12:00:00+00:00. No business default is assumed."
        ),
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=5.0,
        help="Connection timeout in seconds (default: 5).",
    )
    parser.add_argument(
        "--read-timeout",
        type=float,
        default=30.0,
        help="Response read timeout in seconds (default: 30).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.connect_timeout <= 0 or args.read_timeout <= 0:
        print("Timeout values must be positive.", file=sys.stderr)
        return 2

    timeout = (args.connect_timeout, args.read_timeout)
    publication_end = WINDFOR_PUBLICATION_DATE + timedelta(days=1)

    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "wind-forecast-intelligence-phase-2a-probe/1.0",
        }
    )

    try:
        fuelhh = fetch_records(
            session,
            FUELHH_PATH,
            [
                ("settlementDateFrom", FUELHH_DATE.isoformat()),
                ("settlementDateTo", FUELHH_DATE.isoformat()),
                ("fuelType", "WIND"),
            ],
            timeout,
        )
        windfor = fetch_records(
            session,
            WINDFOR_PATH,
            [
                (
                    "publishDateTimeFrom",
                    f"{WINDFOR_PUBLICATION_DATE.isoformat()}T00:00:00Z",
                ),
                (
                    "publishDateTimeTo",
                    f"{publication_end.isoformat()}T00:00:00Z",
                ),
            ],
            timeout,
        )
    except ProbeError as exc:
        print(f"Probe failed: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()

    print_section("FUELHH analysis", analyse_fuelhh(fuelhh))
    print_section("WINDFOR analysis", analyse_windfor(windfor))

    selected, selection_warnings, selection_counts = select_delivery_forecasts(
        windfor,
        cutoff=args.decision_cutoff,
        delivery_date=DELIVERY_DATE,
    )
    actual_hourly, actual_warnings = aggregate_complete_actual_hours(fuelhh)
    print_section(
        "January 14 decision / January 15 delivery selection",
        {
            "cutoff_utc": args.decision_cutoff.isoformat(),
            "cutoff_europe_london": args.decision_cutoff.astimezone(LONDON).isoformat(),
            "delivery_date_europe_london": DELIVERY_DATE.isoformat(),
            "scope_warning": (
                "Selection is only within the sampled January 14 publication window; "
                "it is not proof that earlier eligible publications do not exist."
            ),
            "counts": selection_counts,
            "warning_count": len(selection_warnings),
            "warning_examples": selection_warnings[:5],
            "selected_examples": [
                {
                    "startTime": row.start_time.isoformat(),
                    "publishTime": row.publish_time.isoformat(),
                    "lead_hours": round(row.lead_time.total_seconds() / 3600, 3),
                    "generation": row.record.get("generation"),
                }
                for _, row in sorted(selected.items())[:5]
            ],
        },
    )
    print_section(
        "Candidate hourly alignment",
        {
            **comparison_summary(selected, actual_hourly),
            "actual_aggregation_warning_count": len(actual_warnings),
            "actual_aggregation_warning_examples": actual_warnings[:5],
            "methodology_note": (
                "Each actual hour is the arithmetic mean of readings at HH:00 and "
                "HH:30 only when both exist. No interpolation is performed. This is "
                "a candidate comparison pending confirmation that WINDFOR targets "
                "represent the same hourly window rather than a point-in-time value."
            ),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
