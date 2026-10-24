#!/usr/bin/env python3
"""Ingest and normalize bounded Elexon history for Phase 2B.

The command does not calculate forecast accuracy.  It stores one JSON envelope
per settlement/publication date, records every request attempt in a manifest,
and produces a data-quality report for the requested decision range.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence
from zoneinfo import ZoneInfo


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

try:
    from backend.app.services.data_normalization import (  # noqa: E402
        aggregate_complete_actual_hours,
        normalize_fuelhh,
        normalize_windfor,
        parse_timestamp,
        select_latest_actual_revisions,
        utc_iso,
    )
    from backend.app.services.elexon_client import (  # noqa: E402
        BASE_URL,
        ElexonClient,
        ElexonError,
        FUELHH_PATH,
        WINDFOR_PATH,
    )
except ModuleNotFoundError as exc:  # Direct-script fallback for restricted shells.
    if exc.name != "backend":
        raise
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from app.services.data_normalization import (  # type: ignore[no-redef]  # noqa: E402
        aggregate_complete_actual_hours,
        normalize_fuelhh,
        normalize_windfor,
        parse_timestamp,
        select_latest_actual_revisions,
        utc_iso,
    )
    from app.services.elexon_client import (  # type: ignore[no-redef]  # noqa: E402
        BASE_URL,
        ElexonClient,
        ElexonError,
        FUELHH_PATH,
        WINDFOR_PATH,
    )


LOGGER = logging.getLogger(__name__)
LONDON = ZoneInfo("Europe/London")
UTC = timezone.utc
SUPPORTED_FIRST_DECISION = date(2026, 1, 1)
SUPPORTED_LAST_DECISION = date(2026, 1, 31)
DEFAULT_LOOKBACK_HOURS = 72
MANIFEST_VERSION = 1


@dataclass(frozen=True)
class IngestionConfig:
    decision_start: date
    decision_end: date
    cutoff_time: time
    data_root: Path = BACKEND_ROOT / "data"
    forecast_lookback_hours: int = DEFAULT_LOOKBACK_HOURS
    refresh: bool = False

    def validate(self) -> None:
        if not SUPPORTED_FIRST_DECISION <= self.decision_start <= self.decision_end <= SUPPORTED_LAST_DECISION:
            raise ValueError("decision range must be within 2026-01-01 through 2026-01-31")
        if self.forecast_lookback_hours < 24 or self.forecast_lookback_hours > 168:
            raise ValueError("forecast lookback must be between 24 and 168 hours")


def now_utc() -> datetime:
    return datetime.now(UTC)


def dates_between(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def cutoff_for(decision_date: date, cutoff_time: time) -> datetime:
    """Interpret a decision cutoff as Europe/London and return UTC."""
    local = datetime.combine(decision_date, cutoff_time, tzinfo=LONDON)
    return local.astimezone(UTC)


def atomic_write_json(path: Path, payload: Any) -> None:
    """Replace a JSON file only after a complete write and fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class Manifest:
    """Append-only request-attempt manifest with atomic persistence."""

    def __init__(self, path: Path, clock: Callable[[], datetime] = now_utc) -> None:
        self.path = path
        self.clock = clock
        if path.exists():
            payload = load_json(path)
            if not isinstance(payload, dict) or not isinstance(payload.get("batches"), list):
                raise ValueError(f"invalid manifest structure: {path}")
            self.payload = payload
        else:
            self.payload = {"manifest_version": MANIFEST_VERSION, "batches": []}

    def append(self, entry: dict[str, Any]) -> None:
        self.payload["batches"].append(entry)
        self.payload["updated_at"] = utc_iso(self.clock())
        atomic_write_json(self.path, self.payload)

    def reusable_success(self, dataset: str, batch_id: str) -> dict[str, Any] | None:
        for entry in reversed(self.payload["batches"]):
            if (
                entry.get("dataset_name") == dataset
                and entry.get("batch_id") == batch_id
                and entry.get("request_status") in {"success", "empty"}
            ):
                raw_path = entry.get("raw_file_path")
                processed_path = entry.get("processed_file_path")
                raw_file = _manifest_file_path(raw_path) if raw_path else None
                processed_file = _manifest_file_path(processed_path) if processed_path else None
                if raw_file and processed_file and raw_file.is_file() and processed_file.is_file():
                    try:
                        raw = load_json(raw_file)
                        processed = load_json(processed_file)
                    except (OSError, ValueError, json.JSONDecodeError):
                        return None
                    if isinstance(raw.get("records"), list) and isinstance(processed.get("records"), list):
                        return entry
        return None


def _relative_or_absolute(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPOSITORY_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def _manifest_file_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def _batch_paths(config: IngestionConfig, dataset: str, batch_date: date) -> tuple[Path, Path]:
    stem = batch_date.isoformat()
    return (
        config.data_root / "raw" / dataset.lower() / f"{stem}.json",
        config.data_root / "processed" / dataset.lower() / f"{stem}.json",
    )


def _request_metadata(dataset: str, batch_date: date) -> tuple[str, dict[str, str]]:
    if dataset == "FUELHH":
        return FUELHH_PATH, {
            "settlementDateFrom": batch_date.isoformat(),
            "settlementDateTo": batch_date.isoformat(),
            "fuelType": "WIND",
        }
    start = datetime.combine(batch_date, time.min, tzinfo=UTC)
    # Adjacent calls do not share a boundary. Elexon range inclusivity is not
    # contractually explicit, so the final microsecond remains within this date.
    end = start + timedelta(days=1) - timedelta(microseconds=1)
    return WINDFOR_PATH, {
        "publishDateTimeFrom": utc_iso(start),
        "publishDateTimeTo": utc_iso(end),
    }


def ingest_batch(
    *,
    dataset: str,
    batch_date: date,
    config: IngestionConfig,
    client: ElexonClient,
    manifest: Manifest,
    clock: Callable[[], datetime] = now_utc,
) -> dict[str, Any]:
    """Fetch and normalize one daily batch, or reuse its valid prior output."""
    batch_id = batch_date.isoformat()
    raw_path, processed_path = _batch_paths(config, dataset, batch_date)
    prior = None if config.refresh else manifest.reusable_success(dataset, batch_id)
    if prior:
        LOGGER.info("Reusing %s batch %s", dataset, batch_id)
        return {
            "entry": prior,
            "raw": load_json(_manifest_file_path(prior["raw_file_path"])),
            "processed": load_json(_manifest_file_path(prior["processed_file_path"])),
            "reused": True,
        }

    endpoint, parameters = _request_metadata(dataset, batch_date)
    source_endpoint = f"{getattr(client, 'base_url', BASE_URL).rstrip('/')}{endpoint}"
    retrieved_at = utc_iso(clock())
    base_entry: dict[str, Any] = {
        "dataset_name": dataset,
        "batch_id": batch_id,
        "request_date_range": parameters,
        "retrieval_timestamp": retrieved_at,
        "source_endpoint": source_endpoint,
        "raw_file_path": _relative_or_absolute(raw_path),
        "processed_file_path": _relative_or_absolute(processed_path),
    }
    try:
        if dataset == "FUELHH":
            records = client.fetch_fuelhh(batch_date, batch_date)
        elif dataset == "WINDFOR":
            start = datetime.combine(batch_date, time.min, tzinfo=UTC)
            end = start + timedelta(days=1) - timedelta(microseconds=1)
            records = client.fetch_windfor(start, end)
        else:
            raise ValueError(f"unsupported dataset {dataset}")
    except (ElexonError, OSError) as exc:
        failed = {
            **base_entry,
            "request_status": "failed",
            "record_count": None,
            "validation_status": "not_run",
            "validation_warnings": [str(exc)],
        }
        manifest.append(failed)
        LOGGER.error("Failed %s batch %s: %s", dataset, batch_id, exc)
        return {"entry": failed, "raw": None, "processed": None, "reused": False}

    provenance = {
        "endpoint": source_endpoint,
        "batch_id": batch_id,
        "retrieved_at": retrieved_at,
        "raw_file": _relative_or_absolute(raw_path),
    }
    normalized = (
        normalize_fuelhh(records, provenance=provenance)
        if dataset == "FUELHH"
        else normalize_windfor(records, provenance=provenance)
    )
    raw_envelope = {
        "dataset": dataset,
        "request": {"endpoint": source_endpoint, "parameters": parameters},
        "retrieved_at": retrieved_at,
        "request_status": "empty" if not records else "success",
        "record_count": len(records),
        "records": records,
    }
    validation_status = (
        "incomplete"
        if normalized.invalid_record_count or normalized.conflicting_duplicate_count
        else "complete"
    )
    processed_envelope = {
        "dataset": dataset,
        "batch_id": batch_id,
        "normalized_at": retrieved_at,
        "validation_status": validation_status,
        "normalization": normalized.summary(),
        "warnings": normalized.warnings,
        "record_count": len(normalized.records),
        "records": normalized.records,
    }

    # A failed fetch never reaches these writes. Each replacement is atomic;
    # existing valid files therefore survive transport/JSON failures.
    atomic_write_json(raw_path, raw_envelope)
    atomic_write_json(processed_path, processed_envelope)
    succeeded = {
        **base_entry,
        "request_status": "empty" if not records else "success",
        "record_count": len(records),
        "validation_status": validation_status,
        "validation_warnings": normalized.warnings,
    }
    manifest.append(succeeded)
    return {
        "entry": succeeded,
        "raw": raw_envelope,
        "processed": processed_envelope,
        "reused": False,
    }


def _expected_starts(day: date, interval: timedelta) -> list[datetime]:
    start = datetime.combine(day, time.min, tzinfo=LONDON).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=LONDON).astimezone(UTC)
    values: list[datetime] = []
    current = start
    while current < end:
        values.append(current)
        current += interval
    return values


def build_validation_report(
    config: IngestionConfig,
    batch_results: Sequence[dict[str, Any]],
    manifest: Manifest,
) -> dict[str, Any]:
    raw_actual_count = 0
    raw_forecast_count = 0
    actual_records: list[dict[str, Any]] = []
    forecast_records: list[dict[str, Any]] = []
    normalization_warnings: list[str] = []
    duplicate_counts = {"FUELHH": 0, "WINDFOR": 0}
    conflict_counts = {"FUELHH": 0, "WINDFOR": 0}
    null_counts = {"FUELHH": 0, "WINDFOR": 0}
    failed: list[str] = []
    incomplete: list[str] = []

    for result in batch_results:
        entry = result["entry"]
        label = f"{entry['dataset_name']}:{entry['batch_id']}"
        if entry["request_status"] == "failed":
            failed.append(label)
            continue
        raw = result["raw"]
        processed = result["processed"]
        if entry["dataset_name"] == "FUELHH":
            raw_actual_count += raw["record_count"]
            actual_records.extend(processed["records"])
        else:
            raw_forecast_count += raw["record_count"]
            forecast_records.extend(processed["records"])
        summary = processed["normalization"]
        duplicate_counts[entry["dataset_name"]] += summary["exact_duplicate_count"]
        conflict_counts[entry["dataset_name"]] += summary["conflicting_duplicate_count"]
        null_counts[entry["dataset_name"]] += summary["null_generation_count"]
        normalization_warnings.extend(f"{label}: {warning}" for warning in processed["warnings"])
        if entry.get("validation_status") == "incomplete":
            incomplete.append(label)

    selected_actuals, revision_warnings = select_latest_actual_revisions(actual_records)
    actual_versions_by_start: dict[str, set[str | None]] = defaultdict(set)
    for row in actual_records:
        actual_versions_by_start[row["start_time"]].add(row.get("publish_time"))
    actual_revision_period_count = sum(
        len(publications_for_period) > 1
        for publications_for_period in actual_versions_by_start.values()
    )
    actual_by_start = {parse_timestamp(row["start_time"], "start_time") for row in selected_actuals if row.get("generation_mw") is not None}
    expected_actuals = {
        start
        for delivery in dates_between(config.decision_start + timedelta(days=1), config.decision_end + timedelta(days=1))
        for start in _expected_starts(delivery, timedelta(minutes=30))
    }
    missing_actuals = sorted(expected_actuals - actual_by_start)
    hourly_actuals, hourly_warnings = aggregate_complete_actual_hours(actual_records)
    hourly_actual_starts = {
        parse_timestamp(row["start_time"], "start_time") for row in hourly_actuals
    }

    publications = {row["publish_time"] for row in forecast_records}
    negative_leads = sum(row["lead_time_minutes"] < 0 for row in forecast_records)
    concerns = list(normalization_warnings) + revision_warnings
    missing_forecast_by_decision: dict[str, list[str]] = {}
    lookback_boundary_counts: dict[str, int] = {}
    selected_counts: dict[str, int] = {}
    selected_publications: dict[str, list[str]] = {}
    matched_hour_counts: dict[str, int] = {}
    for decision in dates_between(config.decision_start, config.decision_end):
        cutoff = cutoff_for(decision, config.cutoff_time)
        lookback_boundary = cutoff - timedelta(hours=config.forecast_lookback_hours)
        delivery = decision + timedelta(days=1)
        expected_hours = _expected_starts(delivery, timedelta(hours=1))
        eligible_rows = [
            row
            for row in forecast_records
            if lookback_boundary <= parse_timestamp(row["publish_time"], "publish_time") <= cutoff
            and parse_timestamp(row["start_time"], "start_time") >= parse_timestamp(row["publish_time"], "publish_time")
            and parse_timestamp(row["start_time"], "start_time").astimezone(LONDON).date() == delivery
            and row.get("generation_mw") is not None
        ]
        by_target: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
        for row in eligible_rows:
            by_target[parse_timestamp(row["start_time"], "start_time")].append(row)
        selected: dict[datetime, dict[str, Any]] = {}
        for target, candidates in sorted(by_target.items()):
            latest_publish = max(row["publish_time"] for row in candidates)
            latest = [row for row in candidates if row["publish_time"] == latest_publish]
            values = {repr(row.get("generation_mw")) for row in latest}
            if len(values) != 1:
                concerns.append(
                    f"{decision.isoformat()} target {utc_iso(target)} has conflicting "
                    f"latest forecast values at {latest_publish}."
                )
                continue
            selected[target] = latest[0]
        eligible = set(selected)
        missing_forecast_by_decision[decision.isoformat()] = [
            utc_iso(value) for value in expected_hours if value not in eligible
        ]
        selected_counts[decision.isoformat()] = len(selected)
        selected_publications[decision.isoformat()] = sorted(
            {row["publish_time"] for row in selected.values()}
        )
        matched_hour_counts[decision.isoformat()] = len(eligible & hourly_actual_starts)
        boundary_end = lookback_boundary + timedelta(hours=24)
        lookback_boundary_counts[decision.isoformat()] = sum(
            lookback_boundary <= parse_timestamp(row["publish_time"], "publish_time") < boundary_end
            and parse_timestamp(row["start_time"], "start_time").astimezone(LONDON).date() == delivery
            for row in forecast_records
        )

    start_values = [parse_timestamp(row["start_time"], "start_time") for row in actual_records]
    forecast_targets = [parse_timestamp(row["start_time"], "start_time") for row in forecast_records]
    if any(missing_forecast_by_decision.values()):
        concerns.append("One or more decision dates lack complete eligible hourly forecast target coverage.")
    if any(lookback_boundary_counts.values()):
        concerns.append(
            "Relevant targets occur in the oldest 24 hours of the configured lookback; "
            "earlier publications may need investigation before claiming complete history."
        )
    if failed:
        concerns.append("One or more API batches failed; existing valid files were not overwritten.")

    return {
        "report_version": 1,
        "generated_at": utc_iso(now_utc()),
        "scope": {
            "decision_start": config.decision_start.isoformat(),
            "decision_end": config.decision_end.isoformat(),
            "cutoff_time_europe_london": config.cutoff_time.isoformat(),
            "forecast_lookback_hours": config.forecast_lookback_hours,
        },
        "total_actual_records": raw_actual_count,
        "total_forecast_records": raw_forecast_count,
        "actual_date_coverage_utc": {
            "first": utc_iso(min(start_values)) if start_values else None,
            "last": utc_iso(max(start_values)) if start_values else None,
        },
        "forecast_target_coverage_utc": {
            "first": utc_iso(min(forecast_targets)) if forecast_targets else None,
            "last": utc_iso(max(forecast_targets)) if forecast_targets else None,
        },
        "forecast_publication_count": len(publications),
        "exact_duplicate_counts": duplicate_counts,
        "conflicting_duplicate_counts": conflict_counts,
        "null_generation_counts": null_counts,
        "actual_revision_period_count": actual_revision_period_count,
        "missing_half_hour_actual_period_count": len(missing_actuals),
        "missing_half_hour_actual_periods": [utc_iso(value) for value in missing_actuals],
        "complete_hourly_actual_count": len(hourly_actuals),
        "hourly_actual_aggregation_warning_count": len(hourly_warnings),
        "missing_hourly_forecast_target_counts_by_decision": {
            key: len(value) for key, value in missing_forecast_by_decision.items()
        },
        "missing_hourly_forecast_targets_by_decision": missing_forecast_by_decision,
        "selected_forecast_target_counts_by_decision": selected_counts,
        "selected_forecast_publications_by_decision": selected_publications,
        "matched_hour_counts_by_decision": matched_hour_counts,
        "negative_lead_time_count": negative_leads,
        "lookback_oldest_24h_relevant_record_counts": lookback_boundary_counts,
        "failed_api_requests": failed,
        "incomplete_batches": incomplete,
        "unresolved_data_quality_concerns": concerns,
        "manifest_path": _relative_or_absolute(manifest.path),
    }


def run_ingestion(
    config: IngestionConfig,
    client: ElexonClient,
    *,
    clock: Callable[[], datetime] = now_utc,
) -> dict[str, Any]:
    """Run the requested bounded ingestion and write its validation report."""
    config.validate()
    manifest = Manifest(config.data_root / "manifest.json", clock=clock)
    results: list[dict[str, Any]] = []
    delivery_start = config.decision_start + timedelta(days=1)
    delivery_end = config.decision_end + timedelta(days=1)
    for delivery in dates_between(delivery_start, delivery_end):
        results.append(
            ingest_batch(
                dataset="FUELHH",
                batch_date=delivery,
                config=config,
                client=client,
                manifest=manifest,
                clock=clock,
            )
        )

    first_cutoff = cutoff_for(config.decision_start, config.cutoff_time)
    publication_start = (first_cutoff - timedelta(hours=config.forecast_lookback_hours)).date()
    publication_end = cutoff_for(config.decision_end, config.cutoff_time).date()
    for publication_date in dates_between(publication_start, publication_end):
        results.append(
            ingest_batch(
                dataset="WINDFOR",
                batch_date=publication_date,
                config=config,
                client=client,
                manifest=manifest,
                clock=clock,
            )
        )

    report = build_validation_report(config, results, manifest)
    report_name = f"validation_{config.decision_start.isoformat()}_{config.decision_end.isoformat()}.json"
    report_path = config.data_root / "processed" / "reports" / report_name
    atomic_write_json(report_path, report)
    return {"report": report, "report_path": report_path, "batches": results}


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc


def parse_cutoff_time(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid cutoff {value!r}; expected HH:MM[:SS]") from exc
    if parsed.tzinfo is not None:
        raise argparse.ArgumentTypeError("cutoff must be a local wall-clock time without an offset")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-start", required=True, type=parse_date)
    parser.add_argument("--decision-end", required=True, type=parse_date)
    parser.add_argument(
        "--decision-cutoff",
        required=True,
        type=parse_cutoff_time,
        help="Europe/London wall-clock cutoff, e.g. 12:00",
    )
    parser.add_argument(
        "--forecast-lookback-hours",
        type=int,
        default=DEFAULT_LOOKBACK_HOURS,
        help="bounded publication lookback before each decision cutoff (default: 72)",
    )
    parser.add_argument("--data-root", type=Path, default=BACKEND_ROOT / "data")
    parser.add_argument("--refresh", action="store_true", help="download successful batches again")
    parser.add_argument("--connect-timeout", type=float, default=5.0)
    parser.add_argument("--read-timeout", type=float, default=30.0)
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")
    config = IngestionConfig(
        decision_start=args.decision_start,
        decision_end=args.decision_end,
        cutoff_time=args.decision_cutoff,
        data_root=args.data_root,
        forecast_lookback_hours=args.forecast_lookback_hours,
        refresh=args.refresh,
    )
    try:
        config.validate()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    with ElexonClient(
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
        max_attempts=args.max_attempts,
    ) as client:
        result = run_ingestion(config, client)
    report = result["report"]
    print(f"Validation report: {result['report_path']}")
    print(
        f"Actual records: {report['total_actual_records']}; "
        f"forecast records: {report['total_forecast_records']}; "
        f"failed batches: {len(report['failed_api_requests'])}; "
        f"incomplete batches: {len(report['incomplete_batches'])}; "
        f"quality concerns: {len(report['unresolved_data_quality_concerns'])}"
    )
    return 1 if report["failed_api_requests"] or report["incomplete_batches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
