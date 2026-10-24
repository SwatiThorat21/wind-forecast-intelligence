"""Forecast accuracy metrics calculated over valid matched hourly periods."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping


METRIC_FLOAT_FIELDS = {
    "mae",
    "rmse",
    "bias",
    "wape",
    "mean_forecast_mw",
    "mean_actual_mw",
    "maximum_absolute_error_mw",
    "forecast_coverage_percentage",
}


def calculate_metrics(
    periods: Iterable[Mapping[str, Any]], *, expected_periods: int | None = None
) -> dict[str, int | float | None]:
    """Calculate unrounded metrics from period dictionaries.

    Missing forecast and actual counts are independent, so a period missing
    both contributes to both counts. Only rows with two non-null values enter
    error calculations. Numeric zero remains a valid observation.
    """
    rows = list(periods)
    expected = len(rows) if expected_periods is None else expected_periods
    if expected < 0:
        raise ValueError("expected_periods cannot be negative")

    missing_forecast = sum(row.get("forecast_mw") is None for row in rows)
    missing_actual = sum(row.get("actual_mw") is None for row in rows)
    forecast_count = sum(row.get("forecast_mw") is not None for row in rows)
    matched = [
        (float(row["forecast_mw"]), float(row["actual_mw"]))
        for row in rows
        if row.get("forecast_mw") is not None and row.get("actual_mw") is not None
    ]

    result: dict[str, int | float | None] = {
        "mae": None,
        "rmse": None,
        "bias": None,
        "wape": None,
        "mean_forecast_mw": None,
        "mean_actual_mw": None,
        "maximum_absolute_error_mw": None,
        "overforecast_count": 0,
        "underforecast_count": 0,
        "exact_match_count": 0,
        "matched_period_count": len(matched),
        "missing_forecast_period_count": missing_forecast,
        "missing_actual_period_count": missing_actual,
        "forecast_coverage_percentage": (
            forecast_count / expected * 100 if expected else None
        ),
    }
    if not matched:
        return result

    forecasts = [forecast for forecast, _ in matched]
    actuals = [actual for _, actual in matched]
    errors = [forecast - actual for forecast, actual in matched]
    absolute_errors = [abs(error) for error in errors]
    count = len(matched)
    actual_total = sum(abs(actual) for actual in actuals)

    result.update(
        {
            "mae": sum(absolute_errors) / count,
            "rmse": math.sqrt(sum(error * error for error in errors) / count),
            "bias": sum(errors) / count,
            "wape": sum(absolute_errors) / actual_total * 100
            if actual_total != 0
            else None,
            "mean_forecast_mw": sum(forecasts) / count,
            "mean_actual_mw": sum(actuals) / count,
            "maximum_absolute_error_mw": max(absolute_errors),
            "overforecast_count": sum(error > 0 for error in errors),
            "underforecast_count": sum(error < 0 for error in errors),
            "exact_match_count": sum(error == 0 for error in errors),
        }
    )
    return result


def rounded_metrics(
    metrics: Mapping[str, int | float | None], *, digits: int = 3
) -> dict[str, int | float | None]:
    """Round only API-presented floating metrics, never calculation inputs."""
    return {
        key: round(value, digits)
        if key in METRIC_FLOAT_FIELDS and isinstance(value, float)
        else value
        for key, value in metrics.items()
    }
