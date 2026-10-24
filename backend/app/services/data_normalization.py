"""Deterministic normalization and resolution-alignment utilities."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence


def parse_timestamp(value: Any, field_name: str) -> datetime:
    """Parse an ISO-8601 timestamp, require an offset, and return UTC."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} is not a valid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware: {value!r}")
    return parsed.astimezone(timezone.utc)


def utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def numeric_generation(value: Any) -> float | int | None:
    """Validate MW while preserving integers and missing values."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"generation must be numeric or null, received {value!r}")
    if not math.isfinite(float(value)):
        raise ValueError(f"generation must be finite, received {value!r}")
    return value


@dataclass
class NormalizationResult:
    records: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    exact_duplicate_count: int = 0
    conflicting_duplicate_count: int = 0
    invalid_record_count: int = 0
    null_generation_count: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "record_count": len(self.records),
            "exact_duplicate_count": self.exact_duplicate_count,
            "conflicting_duplicate_count": self.conflicting_duplicate_count,
            "invalid_record_count": self.invalid_record_count,
            "null_generation_count": self.null_generation_count,
            "warning_count": len(self.warnings),
        }


def _fingerprint(record: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, repr(value)) for key, value in record.items()))


def normalize_fuelhh(
    records: Sequence[dict[str, Any]], *, provenance: dict[str, Any]
) -> NormalizationResult:
    """Normalize WIND FUELHH rows without making an arbitrary revision choice."""
    result = NormalizationResult()
    seen_exact: dict[tuple[tuple[str, str], ...], int] = {}
    conflict_values: dict[tuple[str, str, str | None], set[str]] = defaultdict(set)

    for index, source in enumerate(records):
        if source.get("fuelType") != "WIND":
            result.warnings.append(f"record {index}: ignored non-WIND fuelType {source.get('fuelType')!r}")
            continue
        try:
            start = parse_timestamp(source.get("startTime"), "startTime")
            publish_raw = source.get("publishTime")
            publish = parse_timestamp(publish_raw, "publishTime") if publish_raw is not None else None
            generation = numeric_generation(source.get("generation"))
        except ValueError as exc:
            result.invalid_record_count += 1
            result.warnings.append(f"record {index}: {exc}")
            continue
        if generation is None:
            result.null_generation_count += 1
            result.warnings.append(f"record {index}: generation is null")

        fingerprint = _fingerprint(source)
        if fingerprint in seen_exact:
            result.exact_duplicate_count += 1
            prior = result.records[seen_exact[fingerprint]]
            prior["source_indices"].append(index)
            prior["duplicate_count"] += 1
            continue

        normalized = {
            "dataset": "FUELHH",
            "start_time": utc_iso(start),
            "publish_time": utc_iso(publish) if publish else None,
            "settlement_date": source.get("settlementDate"),
            "settlement_period": source.get("settlementPeriod"),
            "fuel_type": source.get("fuelType"),
            "generation_mw": generation,
            "source": dict(provenance),
            "source_indices": [index],
            "duplicate_count": 1,
            "original": dict(source),
        }
        seen_exact[fingerprint] = len(result.records)
        result.records.append(normalized)
        key = (normalized["start_time"], normalized["fuel_type"], normalized["publish_time"])
        conflict_values[key].add(repr(generation))

    for key, values in conflict_values.items():
        if len(values) > 1:
            result.conflicting_duplicate_count += len(values) - 1
            result.warnings.append(f"conflicting FUELHH key {key}: generation values {sorted(values)}")
    return result


def normalize_windfor(
    records: Sequence[dict[str, Any]], *, provenance: dict[str, Any]
) -> NormalizationResult:
    """Normalize WINDFOR while preserving distinct historical publications."""
    result = NormalizationResult()
    seen_exact: dict[tuple[tuple[str, str], ...], int] = {}
    conflict_values: dict[tuple[str, str], set[str]] = defaultdict(set)

    for index, source in enumerate(records):
        try:
            start = parse_timestamp(source.get("startTime"), "startTime")
            publish = parse_timestamp(source.get("publishTime"), "publishTime")
            generation = numeric_generation(source.get("generation"))
        except ValueError as exc:
            result.invalid_record_count += 1
            result.warnings.append(f"record {index}: {exc}")
            continue
        if generation is None:
            result.null_generation_count += 1
            result.warnings.append(f"record {index}: generation is null")

        fingerprint = _fingerprint(source)
        if fingerprint in seen_exact:
            result.exact_duplicate_count += 1
            prior = result.records[seen_exact[fingerprint]]
            prior["source_indices"].append(index)
            prior["duplicate_count"] += 1
            continue
        normalized = {
            "dataset": "WINDFOR",
            "start_time": utc_iso(start),
            "publish_time": utc_iso(publish),
            "generation_mw": generation,
            "lead_time_minutes": (start - publish).total_seconds() / 60,
            "source": dict(provenance),
            "source_indices": [index],
            "duplicate_count": 1,
            "original": dict(source),
        }
        seen_exact[fingerprint] = len(result.records)
        result.records.append(normalized)
        conflict_values[(normalized["publish_time"], normalized["start_time"])].add(repr(generation))

    for key, values in conflict_values.items():
        if len(values) > 1:
            result.conflicting_duplicate_count += len(values) - 1
            result.warnings.append(f"conflicting WINDFOR key {key}: generation values {sorted(values)}")
    return result


def select_latest_actual_revisions(
    records: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Select latest published actual per start time, rejecting latest conflicts.

    FUELHH has no finality flag in the verified schema.  Latest ``publish_time``
    is therefore the explicit proxy for final available actual. Rows without a
    publication timestamp are used only when they are the sole version.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["start_time"]].append(record)
    selected: list[dict[str, Any]] = []
    warnings: list[str] = []
    for start, versions in sorted(grouped.items()):
        dated = [row for row in versions if row.get("publish_time") is not None]
        if dated:
            latest_time = max(row["publish_time"] for row in dated)
            candidates = [row for row in dated if row["publish_time"] == latest_time]
        elif len(versions) == 1:
            candidates = versions
        else:
            warnings.append(f"{start}: multiple actual versions have no publish_time")
            continue
        values = {repr(row.get("generation_mw")) for row in candidates}
        if len(values) != 1:
            warnings.append(f"{start}: conflicting latest actual revisions {sorted(values)}")
            continue
        selected.append(candidates[0])
    return selected, warnings


def aggregate_complete_actual_hours(
    records: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Average only complete, aligned pairs of normalized half-hour actuals."""
    revised, warnings = select_latest_actual_revisions(records)
    by_start = {parse_timestamp(row["start_time"], "start_time"): row for row in revised}
    hourly: list[dict[str, Any]] = []
    for start, first in sorted(by_start.items()):
        if start.minute != 0 or start.second != 0 or start.microsecond != 0:
            continue
        second_start = start + timedelta(minutes=30)
        second = by_start.get(second_start)
        if second is None:
            warnings.append(f"{utc_iso(start)}: missing second half-hour")
            continue
        first_value = first.get("generation_mw")
        second_value = second.get("generation_mw")
        if first_value is None or second_value is None:
            warnings.append(f"{utc_iso(start)}: null generation in half-hour pair")
            continue
        if second_start.replace(minute=0) != start:
            warnings.append(f"{utc_iso(start)}: records do not share one hourly window")
            continue
        hourly.append(
            {
                "start_time": utc_iso(start),
                "generation_mw": (float(first_value) + float(second_value)) / 2,
                "method": "mean_of_two_complete_half_hour_average_mw_values",
                "provisional": True,
                "component_start_times": [utc_iso(start), utc_iso(second_start)],
            }
        )
    return hourly, warnings


def count_duplicate_keys(
    records: Iterable[dict[str, Any]], key_fields: tuple[str, ...]
) -> int:
    counts = Counter(tuple(row.get(field) for field in key_fields) for row in records)
    return sum(count - 1 for count in counts.values() if count > 1)
