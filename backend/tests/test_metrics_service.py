"""Synthetic metric tests; values are not historical Elexon observations."""

from __future__ import annotations

import math

from backend.app.services.metrics_service import calculate_metrics


def periods(*pairs):
    return [{"forecast_mw": forecast, "actual_mw": actual} for forecast, actual in pairs]


def test_mae_rmse_bias_and_classification_counts() -> None:
    result = calculate_metrics(periods((12, 10), (7, 10), (5, 5)))
    assert result["mae"] == 5 / 3
    assert result["rmse"] == math.sqrt(13 / 3)
    assert result["bias"] == -1 / 3
    assert result["maximum_absolute_error_mw"] == 3
    assert result["overforecast_count"] == 1
    assert result["underforecast_count"] == 1
    assert result["exact_match_count"] == 1


def test_wape_and_means() -> None:
    result = calculate_metrics(periods((12, 10), (7, 10)))
    assert result["wape"] == 25.0
    assert result["mean_forecast_mw"] == 9.5
    assert result["mean_actual_mw"] == 10.0


def test_zero_actual_is_matched_but_wape_is_undefined() -> None:
    result = calculate_metrics(periods((2, 0), (0, 0)))
    assert result["matched_period_count"] == 2
    assert result["mae"] == 1.0
    assert result["wape"] is None


def test_empty_matched_dataset_returns_null_metrics() -> None:
    result = calculate_metrics(periods((None, 10), (5, None)), expected_periods=2)
    assert result["matched_period_count"] == 0
    assert result["mae"] is None
    assert result["rmse"] is None
    assert result["bias"] is None
    assert result["wape"] is None
    assert result["missing_forecast_period_count"] == 1
    assert result["missing_actual_period_count"] == 1


def test_forecast_coverage_is_not_matched_coverage() -> None:
    result = calculate_metrics(periods((5, None), (None, 4)), expected_periods=2)
    assert result["forecast_coverage_percentage"] == 50.0
    assert result["matched_period_count"] == 0
