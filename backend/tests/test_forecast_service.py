"""Synthetic forecast-selection tests; no fixture is historical Elexon data."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from backend.app.services.data_store import HistoricalDataStore
from backend.app.services.forecast_service import ForecastAnalysisService


UTC = timezone.utc


def actual_half(start: datetime, value: float) -> dict:
    return {
        "dataset": "FUELHH",
        "start_time": start.isoformat().replace("+00:00", "Z"),
        "publish_time": (start + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
        "generation_mw": value,
    }


def actual_hour(start: datetime, first: float = 10, second: float = 14) -> list[dict]:
    return [actual_half(start, first), actual_half(start + timedelta(minutes=30), second)]


def forecast(target: datetime, publish: datetime, value: float | None) -> dict:
    return {
        "dataset": "WINDFOR",
        "start_time": target.isoformat().replace("+00:00", "Z"),
        "publish_time": publish.isoformat().replace("+00:00", "Z"),
        "generation_mw": value,
    }


def service(actuals, forecasts) -> ForecastAnalysisService:
    return ForecastAnalysisService(HistoricalDataStore(actuals, forecasts))


def jan15(hour: int = 0) -> datetime:
    return datetime(2026, 1, 15, hour, tzinfo=UTC)


def test_latest_eligible_revision_is_selected() -> None:
    target = jan15()
    rows = [
        forecast(target, datetime(2026, 1, 13, 23, 30, tzinfo=UTC), 9),
        forecast(target, datetime(2026, 1, 14, 5, 30, tzinfo=UTC), 11),
        forecast(target, datetime(2026, 1, 14, 11, 30, tzinfo=UTC), 13),
    ]
    result = service(actual_hour(target), rows).analyse_day("2026-01-14", "12:00")
    assert result["periods"][0]["forecast_mw"] == 13
    assert result["periods"][0]["forecast_publish_time"] == "2026-01-14T11:30:00Z"


def test_future_publication_is_excluded() -> None:
    target = jan15()
    rows = [
        forecast(target, datetime(2026, 1, 14, 11, 30, tzinfo=UTC), 13),
        forecast(target, datetime(2026, 1, 14, 12, 30, tzinfo=UTC), 99),
    ]
    result = service(actual_hour(target), rows).analyse_day("2026-01-14", "12:00")
    assert result["periods"][0]["forecast_mw"] == 13


def test_changing_cutoff_changes_selected_forecast() -> None:
    target = jan15()
    rows = [
        forecast(target, datetime(2026, 1, 14, 5, 30, tzinfo=UTC), 11),
        forecast(target, datetime(2026, 1, 14, 11, 30, tzinfo=UTC), 13),
    ]
    analysis = service(actual_hour(target), rows)
    assert analysis.analyse_day("2026-01-14", "06:00")["periods"][0]["forecast_mw"] == 11
    assert analysis.analyse_day("2026-01-14", "12:00")["periods"][0]["forecast_mw"] == 13


def test_conflicting_latest_duplicate_is_rejected() -> None:
    target = jan15()
    publish = datetime(2026, 1, 14, 11, 30, tzinfo=UTC)
    result = service(
        actual_hour(target),
        [forecast(target, publish, 13), forecast(target, publish, 14)],
    ).analyse_day("2026-01-14", "12:00")
    period = result["periods"][0]
    assert period["forecast_mw"] is None
    assert period["forecast_conflict"] is True
    assert result["coverage"]["missing_forecast_periods"] == 24


def test_identical_latest_duplicate_is_not_a_conflict() -> None:
    target = jan15()
    publish = datetime(2026, 1, 14, 11, 30, tzinfo=UTC)
    result = service(
        actual_hour(target),
        [forecast(target, publish, 13), forecast(target, publish, 13.0)],
    ).analyse_day("2026-01-14", "12:00")
    assert result["periods"][0]["forecast_mw"] == 13
    assert result["periods"][0]["forecast_conflict"] is False


def test_wrong_delivery_date_forecast_is_excluded() -> None:
    wrong_target = datetime(2026, 1, 16, 0, tzinfo=UTC)
    result = service(
        [],
        [forecast(wrong_target, datetime(2026, 1, 14, 11, 30, tzinfo=UTC), 13)],
    ).analyse_day("2026-01-14", "12:00")
    assert result["coverage"]["missing_forecast_periods"] == 24


def test_missing_forecast_and_actual_periods_are_counted() -> None:
    target = jan15()
    no_forecast = service(actual_hour(target), []).analyse_day("2026-01-14", "12:00")
    assert no_forecast["coverage"]["missing_forecast_periods"] == 24
    assert no_forecast["coverage"]["missing_actual_periods"] == 23
    no_actual = service([], [forecast(target, datetime(2026, 1, 14, 11, 30, tzinfo=UTC), 13)]).analyse_day(
        "2026-01-14", "12:00"
    )
    assert no_actual["coverage"]["missing_actual_periods"] == 24
    assert no_actual["coverage"]["missing_forecast_periods"] == 23


def test_zero_actual_generation_is_preserved() -> None:
    target = jan15()
    result = service(
        actual_hour(target, 0, 0),
        [forecast(target, datetime(2026, 1, 14, 11, 30, tzinfo=UTC), 0)],
    ).analyse_day("2026-01-14", "12:00")
    assert result["periods"][0]["actual_mw"] == 0.0
    assert result["metrics"]["matched_period_count"] == 1
    assert result["metrics"]["wape"] is None


def test_january_31_maps_to_february_1() -> None:
    target = datetime(2026, 2, 1, 0, tzinfo=UTC)
    result = service(
        actual_hour(target),
        [forecast(target, datetime(2026, 1, 31, 11, 30, tzinfo=UTC), 13)],
    ).analyse_day(date(2026, 1, 31), "12:00")
    assert result["delivery_date"] == "2026-02-01"
    assert result["periods"][0]["target_time"] == "2026-02-01T00:00:00Z"


def test_monthly_metrics_weight_periods_not_daily_means() -> None:
    actuals = []
    forecasts = []
    first = datetime(2026, 1, 2, 0, tzinfo=UTC)
    actuals.extend(actual_hour(first, 10, 10))
    forecasts.append(forecast(first, datetime(2026, 1, 1, 11, 30, tzinfo=UTC), 10))
    for hour in range(3):
        target = datetime(2026, 1, 3, hour, tzinfo=UTC)
        actuals.extend(actual_hour(target, 10, 10))
        forecasts.append(forecast(target, datetime(2026, 1, 2, 11, 30, tzinfo=UTC), 20))
    result = service(actuals, forecasts).analyse_month("12:00")
    assert result["metrics"]["matched_period_count"] == 4
    assert result["metrics"]["mae"] == 7.5
    assert result["coverage"]["expected_periods"] == 744
