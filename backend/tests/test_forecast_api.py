"""Flask API tests using an isolated synthetic in-memory data store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app import create_app
from backend.app.services.data_store import (
    HistoricalDataStore,
    HistoricalDataUnavailableError,
)


UTC = timezone.utc


@pytest.fixture()
def client():
    target = datetime(2026, 1, 15, 0, tzinfo=UTC)
    actuals = [
        {
            "start_time": start.isoformat().replace("+00:00", "Z"),
            "publish_time": (start + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
            "generation_mw": value,
        }
        for start, value in ((target, 10), (target + timedelta(minutes=30), 14))
    ]
    forecasts = [
        {
            "start_time": target.isoformat().replace("+00:00", "Z"),
            "publish_time": "2026-01-14T11:30:00Z",
            "generation_mw": 13,
        }
    ]
    app = create_app(
        {"TESTING": True, "DATA_STORE": HistoricalDataStore(actuals, forecasts)}
    )
    return app.test_client()


def test_health_response(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert body["historicalDataset"]["available"] is True


def test_cors_is_limited_to_configured_local_origin(client) -> None:
    allowed = client.get(
        "/api/health", headers={"Origin": "http://127.0.0.1:5173"}
    )
    blocked = client.get(
        "/api/health", headers={"Origin": "https://untrusted.example"}
    )
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
    assert "Access-Control-Allow-Origin" not in blocked.headers


def test_forecast_response_schema(client) -> None:
    response = client.get("/api/forecast?decision_date=2026-01-14&cutoff=12:00")
    assert response.status_code == 200
    body = response.get_json()
    assert body["decisionDate"] == "2026-01-14"
    assert body["deliveryDate"] == "2026-01-15"
    assert body["coverage"]["expectedPeriods"] == 24
    assert len(body["periods"]) == 24
    assert body["periods"][0]["errorMw"] == 1.0
    assert "documented assumption" in body["methodology"]


@pytest.mark.parametrize(
    "query",
    [
        "cutoff=12:00",
        "decision_date=not-a-date&cutoff=12:00",
        "decision_date=2025-12-31&cutoff=12:00",
        "decision_date=2026-01-14&cutoff=25:00",
        "decision_date=2026-01-14",
    ],
)
def test_invalid_forecast_query_parameters(client, query) -> None:
    response = client.get(f"/api/forecast?{query}")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_request"


def test_summary_response_is_period_weighted(client) -> None:
    response = client.get("/api/summary?cutoff=12:00")
    assert response.status_code == 200
    body = response.get_json()
    assert body["totalDecisionDates"] == 31
    assert body["coverage"]["expectedPeriods"] == 744
    assert len(body["dailyAccuracyStatistics"]) == 31
    assert "periods" not in body["dailyAccuracyStatistics"][0]


def test_missing_data_returns_503() -> None:
    app = create_app({"TESTING": True, "LOAD_HISTORICAL_DATA": False})
    response = app.test_client().get(
        "/api/forecast?decision_date=2026-01-14&cutoff=12:00"
    )
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "historical_data_unavailable"


def test_production_startup_fails_when_required_data_is_missing(tmp_path) -> None:
    with pytest.raises(HistoricalDataUnavailableError, match="directory is missing"):
        create_app(
            {
                "DATA_ROOT": str(tmp_path),
                "FAIL_ON_DATA_LOAD_ERROR": True,
            }
        )
