"""Synthetic end-to-end batch tests; no values are historical Elexon data."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone

from backend.app.services.elexon_client import ElexonRequestError
from backend.scripts.ingest_data import IngestionConfig, cutoff_for, run_ingestion


class SyntheticClient:
    def __init__(self):
        self.fuel_calls = 0
        self.forecast_calls = 0

    def fetch_fuelhh(self, start, end):
        self.fuel_calls += 1
        records = []
        for hour in range(24):
            for minute in (0, 30):
                records.append(
                    {
                        "dataset": "FUELHH",
                        "publishTime": f"2026-01-15T{hour:02d}:{30 if minute == 0 else 59:02d}:00Z",
                        "startTime": f"2026-01-15T{hour:02d}:{minute:02d}:00Z",
                        "settlementDate": "2026-01-15",
                        "settlementPeriod": hour * 2 + (1 if minute == 0 else 2),
                        "fuelType": "WIND",
                        "generation": 100 + hour,
                    }
                )
        return records

    def fetch_windfor(self, start, end):
        self.forecast_calls += 1
        if start.date() != date(2026, 1, 14):
            return []
        return [
            {
                "dataset": "WINDFOR",
                "publishTime": "2026-01-14T11:30:00Z",
                "startTime": f"2026-01-15T{hour:02d}:00:00Z",
                "generation": 200 + hour,
            }
            for hour in range(24)
        ]


def config(tmp_path, *, refresh=False):
    return IngestionConfig(
        decision_start=date(2026, 1, 14),
        decision_end=date(2026, 1, 14),
        cutoff_time=time(12, 0),
        data_root=tmp_path / "data",
        forecast_lookback_hours=72,
        refresh=refresh,
    )


def test_london_date_boundary_is_timezone_aware() -> None:
    winter = cutoff_for(date(2026, 1, 14), time(12, 0))
    summer = cutoff_for(date(2026, 7, 14), time(12, 0))
    assert winter == datetime(2026, 1, 14, 12, tzinfo=timezone.utc)
    assert summer == datetime(2026, 7, 14, 11, tzinfo=timezone.utc)


def test_sample_ingestion_and_idempotent_reuse(tmp_path) -> None:
    client = SyntheticClient()
    first = run_ingestion(config(tmp_path), client)
    assert first["report"]["total_actual_records"] == 48
    assert first["report"]["total_forecast_records"] == 24
    assert first["report"]["missing_half_hour_actual_period_count"] == 0
    assert first["report"]["missing_hourly_forecast_target_counts_by_decision"]["2026-01-14"] == 0
    assert first["report"]["selected_forecast_target_counts_by_decision"]["2026-01-14"] == 24
    assert first["report"]["matched_hour_counts_by_decision"]["2026-01-14"] == 24
    assert first["report"]["selected_forecast_publications_by_decision"]["2026-01-14"] == [
        "2026-01-14T11:30:00Z"
    ]
    assert client.fuel_calls == 1
    assert client.forecast_calls == 4  # Jan 11 through Jan 14 for the 72-hour lookback.

    second = run_ingestion(config(tmp_path), client)
    assert second["report"]["total_actual_records"] == 48
    assert client.fuel_calls == 1
    assert client.forecast_calls == 4

    raw = json.loads((tmp_path / "data/raw/fuelhh/2026-01-15.json").read_text())
    assert raw["records"][0]["generation"] == 100
    assert (tmp_path / "data/manifest.json").is_file()


class FailingClient(SyntheticClient):
    def fetch_fuelhh(self, start, end):
        raise ElexonRequestError("synthetic outage")

    def fetch_windfor(self, start, end):
        raise ElexonRequestError("synthetic outage")


def test_failed_refresh_does_not_overwrite_valid_files(tmp_path) -> None:
    run_ingestion(config(tmp_path), SyntheticClient())
    raw_path = tmp_path / "data/raw/fuelhh/2026-01-15.json"
    before = raw_path.read_bytes()
    failed = run_ingestion(config(tmp_path, refresh=True), FailingClient())
    assert raw_path.read_bytes() == before
    assert failed["report"]["failed_api_requests"]


def test_successful_empty_and_failed_batches_have_different_manifest_status(tmp_path) -> None:
    result = run_ingestion(config(tmp_path), SyntheticClient())
    manifest = json.loads((tmp_path / "data/manifest.json").read_text())
    statuses = {(row["dataset_name"], row["batch_id"]): row["request_status"] for row in manifest["batches"]}
    assert statuses[("WINDFOR", "2026-01-11")] == "empty"
    assert result["report"]["failed_api_requests"] == []
