"""REST endpoints for historical forecast analysis."""

from __future__ import annotations

from typing import Any, Mapping

from flask import Blueprint, current_app, jsonify, request

from ..services.data_store import HistoricalDataError, HistoricalDataUnavailableError
from ..services.forecast_service import ForecastAnalysisService, ForecastInputError
from ..services.metrics_service import rounded_metrics


forecast_api = Blueprint("forecast_api", __name__)


@forecast_api.route("/health", methods=["GET"])
def health():
    store = current_app.extensions.get("historical_data_store")
    load_error = current_app.extensions.get("historical_data_error")
    available = store is not None
    return jsonify(
        {
            "status": "ok" if available else "degraded",
            "historicalDataset": {
                "available": available,
                "details": store.availability if available else None,
                "error": str(load_error) if load_error else None,
            },
            "analysisPeriod": {
                "decisionStart": "2026-01-01",
                "decisionEnd": "2026-01-31",
                "deliveryStart": "2026-01-02",
                "deliveryEnd": "2026-02-01",
            },
        }
    )


@forecast_api.route("/forecast", methods=["GET"])
def daily_forecast():
    decision_date = request.args.get("decision_date")
    cutoff = request.args.get("cutoff")
    if decision_date is None or not decision_date.strip():
        raise ForecastInputError("decision_date query parameter is required")
    if cutoff is None or not cutoff.strip():
        raise ForecastInputError("cutoff query parameter is required")
    result = _service().analyse_day(decision_date, cutoff)
    return jsonify(_present_day(result, include_periods=True))


@forecast_api.route("/summary", methods=["GET"])
def monthly_summary():
    cutoff = request.args.get("cutoff")
    if cutoff is None or not cutoff.strip():
        raise ForecastInputError("cutoff query parameter is required")
    result = _service().analyse_month(cutoff)
    return jsonify(_present_summary(result))


def _service() -> ForecastAnalysisService:
    service = current_app.extensions.get("forecast_analysis_service")
    if service is None:
        load_error = current_app.extensions.get("historical_data_error")
        if isinstance(load_error, HistoricalDataError):
            raise load_error
        raise HistoricalDataUnavailableError("historical analysis data is not loaded")
    return service


def _present_day(result: Mapping[str, Any], *, include_periods: bool) -> dict[str, Any]:
    response: dict[str, Any] = {
        "decisionDate": result["decision_date"],
        "deliveryDate": result["delivery_date"],
        "cutoff": result["cutoff"],
        "cutoffUtc": result["cutoff_utc"],
        "timezone": result["timezone"],
        "selectedForecastPublicationTimes": result[
            "selected_forecast_publication_times"
        ],
        "metrics": _camel_metrics(result["metrics"]),
        "coverage": _camel_coverage(result["coverage"]),
        "warnings": result["warnings"],
        "methodology": result["methodology"],
    }
    if include_periods:
        response["periods"] = [_present_period(row) for row in result["periods"]]
    return response


def _present_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "analysisPeriod": {
            "decisionStart": result["analysis_period"]["decision_start"],
            "decisionEnd": result["analysis_period"]["decision_end"],
        },
        "cutoff": result["cutoff"],
        "timezone": result["timezone"],
        "totalDecisionDates": result["total_decision_dates"],
        "metrics": _camel_metrics(result["metrics"]),
        "coverage": _camel_coverage(result["coverage"]),
        "dailyAccuracyStatistics": [
            _present_day(day, include_periods=False)
            for day in result["daily_accuracy_statistics"]
        ],
        "methodology": result["methodology"],
    }


def _present_period(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "targetTime": row["target_time"],
        "targetTimeLocal": row["target_time_local"],
        "forecastMw": _round_value(row["forecast_mw"]),
        "actualMw": _round_value(row["actual_mw"]),
        "errorMw": _round_value(row["error_mw"]),
        "forecastPublishTime": row["forecast_publish_time"],
        "missingForecast": row["missing_forecast"],
        "missingActual": row["missing_actual"],
        "forecastConflict": row["forecast_conflict"],
        "actualMethod": row["actual_method"],
        "actualComponentStartTimes": row["actual_component_start_times"],
    }


def _camel_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    values = rounded_metrics(metrics)
    return {
        "mae": values["mae"],
        "rmse": values["rmse"],
        "bias": values["bias"],
        "wape": values["wape"],
        "meanForecastMw": values["mean_forecast_mw"],
        "meanActualMw": values["mean_actual_mw"],
        "maximumAbsoluteErrorMw": values["maximum_absolute_error_mw"],
        "overforecastCount": values["overforecast_count"],
        "underforecastCount": values["underforecast_count"],
        "exactMatchCount": values["exact_match_count"],
        "matchedPeriodCount": values["matched_period_count"],
        "missingForecastPeriodCount": values["missing_forecast_period_count"],
        "missingActualPeriodCount": values["missing_actual_period_count"],
        "forecastCoveragePercentage": values["forecast_coverage_percentage"],
    }


def _camel_coverage(coverage: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "expectedPeriods": coverage["expected_periods"],
        "matchedPeriods": coverage["matched_periods"],
        "missingForecastPeriods": coverage["missing_forecast_periods"],
        "missingActualPeriods": coverage["missing_actual_periods"],
        "forecastCoveragePercentage": _round_value(
            coverage["forecast_coverage_percentage"]
        ),
    }


def _round_value(value: Any, digits: int = 3) -> Any:
    return round(value, digits) if isinstance(value, float) else value
