"""Read-only integration check against ingested January 2026 Elexon data."""

from __future__ import annotations

from pathlib import Path

from backend.app.services.data_store import HistoricalDataStore
from backend.app.services.forecast_service import ForecastAnalysisService


PROCESSED_ROOT = Path(__file__).resolve().parents[1] / "data" / "processed"


def test_january_14_real_data_matches_phase_2a_reference() -> None:
    store = HistoricalDataStore.from_processed_directory(PROCESSED_ROOT)
    result = ForecastAnalysisService(store).analyse_day("2026-01-14", "12:00")
    assert result["delivery_date"] == "2026-01-15"
    assert result["coverage"] == {
        "expected_periods": 24,
        "matched_periods": 24,
        "missing_forecast_periods": 0,
        "missing_actual_periods": 0,
        "forecast_coverage_percentage": 100.0,
    }
    assert result["selected_forecast_publication_times"] == [
        "2026-01-14T11:30:00Z"
    ]
    assert all(
        period["forecast_publish_time"] <= result["cutoff_utc"]
        for period in result["periods"]
    )
