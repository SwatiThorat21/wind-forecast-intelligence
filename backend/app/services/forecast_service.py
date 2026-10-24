"""Cutoff-aware forecast selection, actual alignment, and monthly analysis."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .data_normalization import parse_timestamp, utc_iso
from .data_store import HistoricalDataStore
from .metrics_service import calculate_metrics


LONDON = ZoneInfo("Europe/London")
UTC = timezone.utc
FIRST_DECISION_DATE = date(2026, 1, 1)
LAST_DECISION_DATE = date(2026, 1, 31)
CUTOFF_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
METHODOLOGY_NOTE = (
    "Hourly actual generation is the arithmetic mean of two complete FUELHH "
    "half-hour average-MW observations at HH:00 and HH:30. Missing halves are "
    "not filled. Comparing that hourly mean with a WINDFOR target assumes the "
    "forecast timestamp represents the same hourly interval; this interval "
    "interpretation remains a documented assumption."
)


class ForecastInputError(ValueError):
    """Raised for an invalid decision date or cutoff."""


def parse_decision_date(value: str | date) -> date:
    if isinstance(value, datetime):
        raise ForecastInputError("decision_date must be a calendar date")
    if isinstance(value, date):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ForecastInputError(
                "decision_date must use YYYY-MM-DD format"
            ) from exc
    else:
        raise ForecastInputError("decision_date must use YYYY-MM-DD format")
    if not FIRST_DECISION_DATE <= parsed <= LAST_DECISION_DATE:
        raise ForecastInputError(
            "decision_date must be between 2026-01-01 and 2026-01-31"
        )
    return parsed


def parse_cutoff(value: str) -> time:
    if not isinstance(value, str) or not CUTOFF_PATTERN.fullmatch(value):
        raise ForecastInputError("cutoff must use 24-hour HH:MM format")
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour, minute)


def decision_cutoff_utc(decision_date: date, cutoff: time) -> datetime:
    return datetime.combine(decision_date, cutoff, tzinfo=LONDON).astimezone(UTC)


def expected_hour_starts(delivery_date: date) -> list[datetime]:
    start = datetime.combine(delivery_date, time.min, tzinfo=LONDON).astimezone(UTC)
    end = datetime.combine(
        delivery_date + timedelta(days=1), time.min, tzinfo=LONDON
    ).astimezone(UTC)
    values: list[datetime] = []
    current = start
    while current < end:
        values.append(current)
        current += timedelta(hours=1)
    return values


class ForecastAnalysisService:
    def __init__(self, store: HistoricalDataStore) -> None:
        self.store = store

    def analyse_day(
        self, decision_date: str | date, cutoff: str
    ) -> dict[str, Any]:
        decision = parse_decision_date(decision_date)
        cutoff_time = parse_cutoff(cutoff)
        cutoff_utc = decision_cutoff_utc(decision, cutoff_time)
        delivery = decision + timedelta(days=1)
        expected_starts = expected_hour_starts(delivery)

        periods: list[dict[str, Any]] = []
        warnings: list[str] = []
        selected_publications: set[str] = set()
        for target in expected_starts:
            selected, conflict = self._select_forecast(target, cutoff_utc)
            actual = self.store.hourly_actual_by_start.get(target)
            forecast_value = (
                selected.get("generation_mw") if selected is not None else None
            )
            actual_value = actual.get("generation_mw") if actual is not None else None
            missing_forecast = selected is None or forecast_value is None or conflict
            missing_actual = actual is None or actual_value is None
            if selected is not None:
                selected_publications.add(utc_iso(selected["_publish"]))
            if conflict:
                warnings.append(
                    f"Conflicting forecast rows at {utc_iso(target)} were rejected."
                )
            periods.append(
                {
                    "target_time": utc_iso(target),
                    "target_time_local": target.astimezone(LONDON).isoformat(),
                    "forecast_mw": None if missing_forecast else forecast_value,
                    "actual_mw": None if missing_actual else actual_value,
                    "error_mw": (
                        float(forecast_value) - float(actual_value)
                        if not missing_forecast and not missing_actual
                        else None
                    ),
                    "forecast_publish_time": (
                        utc_iso(selected["_publish"])
                        if selected is not None
                        else None
                    ),
                    "missing_forecast": missing_forecast,
                    "missing_actual": missing_actual,
                    "forecast_conflict": conflict,
                    "actual_method": actual.get("method") if actual else None,
                    "actual_component_start_times": (
                        actual.get("component_start_times") if actual else []
                    ),
                }
            )

        metrics = calculate_metrics(periods, expected_periods=len(expected_starts))
        coverage = {
            "expected_periods": len(expected_starts),
            "matched_periods": metrics["matched_period_count"],
            "missing_forecast_periods": metrics[
                "missing_forecast_period_count"
            ],
            "missing_actual_periods": metrics["missing_actual_period_count"],
            "forecast_coverage_percentage": metrics[
                "forecast_coverage_percentage"
            ],
        }
        return {
            "decision_date": decision.isoformat(),
            "delivery_date": delivery.isoformat(),
            "cutoff": cutoff,
            "cutoff_utc": utc_iso(cutoff_utc),
            "timezone": "Europe/London",
            "selected_forecast_publication_times": sorted(selected_publications),
            "metrics": metrics,
            "coverage": coverage,
            "periods": periods,
            "warnings": warnings,
            "methodology": METHODOLOGY_NOTE,
        }

    def analyse_month(self, cutoff: str) -> dict[str, Any]:
        parse_cutoff(cutoff)
        daily = [
            self.analyse_day(decision, cutoff)
            for decision in _dates_between(FIRST_DECISION_DATE, LAST_DECISION_DATE)
        ]
        all_periods = [period for day in daily for period in day["periods"]]
        expected = sum(day["coverage"]["expected_periods"] for day in daily)
        metrics = calculate_metrics(all_periods, expected_periods=expected)
        return {
            "analysis_period": {
                "decision_start": FIRST_DECISION_DATE.isoformat(),
                "decision_end": LAST_DECISION_DATE.isoformat(),
            },
            "cutoff": cutoff,
            "timezone": "Europe/London",
            "total_decision_dates": len(daily),
            "metrics": metrics,
            "coverage": {
                "expected_periods": expected,
                "matched_periods": metrics["matched_period_count"],
                "missing_forecast_periods": metrics[
                    "missing_forecast_period_count"
                ],
                "missing_actual_periods": metrics["missing_actual_period_count"],
                "forecast_coverage_percentage": metrics[
                    "forecast_coverage_percentage"
                ],
            },
            "daily_accuracy_statistics": daily,
            "methodology": METHODOLOGY_NOTE,
        }

    def _select_forecast(
        self, target: datetime, cutoff: datetime
    ) -> tuple[dict[str, Any] | None, bool]:
        return select_latest_eligible_forecast(
            self.store.forecast_history_by_target.get(target, ()), target, cutoff
        )


def select_latest_eligible_forecast(
    records: Iterable[dict[str, Any]], target: datetime, cutoff: datetime
) -> tuple[dict[str, Any] | None, bool]:
    """Select one target's latest eligible row and reject latest conflicts."""
    candidates: list[tuple[dict[str, Any], datetime]] = []
    for row in records:
        start = row.get("_start") or parse_timestamp(row.get("start_time"), "start_time")
        publish = row.get("_publish") or parse_timestamp(
            row.get("publish_time"), "publish_time"
        )
        if start == target and publish <= cutoff and publish <= target:
            candidates.append((row, publish))
    if not candidates:
        return None, False
    latest_publish = max(publish for _, publish in candidates)
    latest = [row for row, publish in candidates if publish == latest_publish]
    values = {
        None if row.get("generation_mw") is None else float(row["generation_mw"])
        for row in latest
    }
    if len(values) > 1:
        # Preserve the publication timestamp for diagnostics, but never select
        # an arbitrary generation value.
        selected = dict(latest[0])
        selected["_publish"] = latest_publish
        return selected, True
    selected = dict(latest[0])
    selected["_publish"] = latest_publish
    return selected, False


def _dates_between(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)
