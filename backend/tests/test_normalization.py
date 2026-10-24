"""Tests use synthetic records only; they are not historical Elexon values."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.services.data_normalization import (
    aggregate_complete_actual_hours,
    normalize_fuelhh,
    normalize_windfor,
    parse_timestamp,
    select_latest_actual_revisions,
)


PROVENANCE = {"endpoint": "/synthetic", "batch_id": "test"}


def fuelhh(start: str, generation: int | float | None, publish: str = "2026-01-15T00:30:00Z") -> dict:
    return {
        "dataset": "FUELHH",
        "publishTime": publish,
        "startTime": start,
        "settlementDate": "2026-01-15",
        "settlementPeriod": 1,
        "fuelType": "WIND",
        "generation": generation,
    }


def windfor(start: str, publish: str, generation: int | float | None) -> dict:
    return {
        "dataset": "WINDFOR",
        "publishTime": publish,
        "startTime": start,
        "generation": generation,
    }


def test_timestamp_parsing_requires_timezone_and_canonicalizes_utc() -> None:
    parsed = parse_timestamp("2026-07-01T13:00:00+01:00", "startTime")
    assert parsed == datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_timestamp("2026-01-01T12:00:00", "startTime")


def test_missing_generation_remains_null_and_is_warned() -> None:
    result = normalize_fuelhh(
        [fuelhh("2026-01-15T00:00:00Z", None)], provenance=PROVENANCE
    )
    assert result.records[0]["generation_mw"] is None
    assert result.null_generation_count == 1
    assert any("generation is null" in warning for warning in result.warnings)


def test_exact_and_conflicting_duplicates_are_reported() -> None:
    first = fuelhh("2026-01-15T00:00:00Z", 100)
    conflict = {**first, "generation": 101}
    result = normalize_fuelhh([first, dict(first), conflict], provenance=PROVENANCE)
    assert result.exact_duplicate_count == 1
    assert result.conflicting_duplicate_count == 1
    assert len(result.records) == 2
    assert result.records[0]["duplicate_count"] == 2


def test_forecast_revisions_are_preserved() -> None:
    records = [
        windfor("2026-01-15T12:00:00Z", "2026-01-14T05:30:00Z", 200),
        windfor("2026-01-15T12:00:00Z", "2026-01-14T11:30:00Z", 210),
    ]
    result = normalize_windfor(records, provenance=PROVENANCE)
    assert len(result.records) == 2
    assert {row["publish_time"] for row in result.records} == {
        "2026-01-14T05:30:00Z",
        "2026-01-14T11:30:00Z",
    }


def test_negative_lead_forecast_is_preserved() -> None:
    result = normalize_windfor(
        [windfor("2026-01-13T21:00:00Z", "2026-01-14T22:30:00Z", 200)],
        provenance=PROVENANCE,
    )
    assert result.records[0]["lead_time_minutes"] < 0


def test_hourly_actual_aggregation_requires_two_half_hours() -> None:
    normalized = normalize_fuelhh(
        [
            fuelhh("2026-01-15T00:00:00Z", 100),
            fuelhh("2026-01-15T00:30:00Z", 120, "2026-01-15T01:00:00Z"),
        ],
        provenance=PROVENANCE,
    )
    hourly, warnings = aggregate_complete_actual_hours(normalized.records)
    assert warnings == []
    assert hourly[0]["generation_mw"] == 110.0
    assert hourly[0]["provisional"] is True


def test_missing_second_half_hour_does_not_create_hour() -> None:
    normalized = normalize_fuelhh(
        [fuelhh("2026-01-15T00:00:00Z", 100)], provenance=PROVENANCE
    )
    hourly, warnings = aggregate_complete_actual_hours(normalized.records)
    assert hourly == []
    assert any("missing second half-hour" in warning for warning in warnings)


def test_actual_revision_policy_selects_latest_publication() -> None:
    normalized = normalize_fuelhh(
        [
            fuelhh("2026-01-15T00:00:00Z", 100, "2026-01-15T00:30:00Z"),
            fuelhh("2026-01-15T00:00:00Z", 105, "2026-01-16T10:00:00Z"),
        ],
        provenance=PROVENANCE,
    )
    selected, warnings = select_latest_actual_revisions(normalized.records)
    assert warnings == []
    assert selected[0]["generation_mw"] == 105


def test_conflicting_latest_actual_is_not_chosen() -> None:
    first = fuelhh("2026-01-15T00:00:00Z", 100, "2026-01-16T10:00:00Z")
    normalized = normalize_fuelhh(
        [first, {**first, "generation": 105}], provenance=PROVENANCE
    )
    selected, warnings = select_latest_actual_revisions(normalized.records)
    assert selected == []
    assert any("conflicting latest" in warning for warning in warnings)
