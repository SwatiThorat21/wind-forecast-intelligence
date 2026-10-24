"""Synthetic transport tests for the Elexon client."""

from __future__ import annotations

from datetime import date

import pytest
import requests

from backend.app.services.elexon_client import (
    ElexonClient,
    ElexonRequestError,
    ElexonResponseError,
)


class FakeResponse:
    def __init__(self, status: int, payload=None, *, text: str = "", headers=None):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.headers = headers or {}
        self.url = "https://example.test/request"

    def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_invalid_json_shape_raises_instead_of_returning_empty() -> None:
    session = FakeSession([FakeResponse(200, {"unexpected": []})])
    client = ElexonClient(session=session, max_attempts=1)
    with pytest.raises(ElexonResponseError, match="expected a list"):
        client.fetch_fuelhh(date(2026, 1, 15), date(2026, 1, 15))


def test_successful_empty_response_is_distinguishable() -> None:
    client = ElexonClient(session=FakeSession([FakeResponse(200, [])]), max_attempts=1)
    assert client.fetch_fuelhh(date(2026, 1, 15), date(2026, 1, 15)) == []


def test_429_retries_with_retry_after_then_succeeds() -> None:
    delays = []
    session = FakeSession(
        [FakeResponse(429, {}, headers={"Retry-After": "0"}), FakeResponse(200, [{"ok": True}])]
    )
    client = ElexonClient(session=session, max_attempts=2, sleep=delays.append)
    assert client.fetch_fuelhh(date(2026, 1, 15), date(2026, 1, 15)) == [{"ok": True}]
    assert delays == [0.0]
    assert len(session.calls) == 2


def test_connection_failure_is_bounded_and_raises() -> None:
    session = FakeSession([requests.ConnectionError("offline"), requests.ConnectionError("offline")])
    client = ElexonClient(
        session=session, max_attempts=2, backoff_seconds=0, sleep=lambda _: None, jitter=lambda: 0
    )
    with pytest.raises(ElexonRequestError, match="after 2 attempts"):
        client.fetch_fuelhh(date(2026, 1, 15), date(2026, 1, 15))
    assert len(session.calls) == 2


def test_non_retryable_http_error_raises_immediately() -> None:
    session = FakeSession([FakeResponse(400, {"error": "bad"}, text="bad request")])
    client = ElexonClient(session=session, max_attempts=4)
    with pytest.raises(ElexonRequestError, match="HTTP 400"):
        client.fetch_fuelhh(date(2026, 1, 15), date(2026, 1, 15))
    assert len(session.calls) == 1
