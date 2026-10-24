"""Small, synchronous client for the Elexon Insights dataset streams.

API transport concerns deliberately live here rather than in normalization or
decision-time business logic.  The client raises on every failed request; an
empty list is returned only when Elexon successfully returns an empty dataset.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping, Sequence

import requests


LOGGER = logging.getLogger(__name__)
BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
FUELHH_PATH = "/datasets/FUELHH/stream"
WINDFOR_PATH = "/datasets/WINDFOR/stream"
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class ElexonError(RuntimeError):
    """Base class for Elexon client failures."""


class ElexonRequestError(ElexonError):
    """Raised when a request cannot be completed successfully."""


class ElexonResponseError(ElexonError):
    """Raised when a successful response has an invalid JSON structure."""


def _utc_parameter(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("publication query timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class ElexonClient:
    """Fetch bounded FUELHH and WINDFOR stream windows with bounded retries."""

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
        max_attempts: int = 4,
        backoff_seconds: float = 0.5,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("timeouts must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds cannot be negative")
        self.base_url = base_url.rstrip("/")
        self.timeout = (connect_timeout, read_timeout)
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.session = session or requests.Session()
        self._owns_session = session is None
        self._sleep = sleep
        self._jitter = jitter
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "wind-forecast-intelligence-ingestion/2B",
            }
        )

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def __enter__(self) -> "ElexonClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_fuelhh(self, start: date, end: date) -> list[dict[str, Any]]:
        """Fetch WIND FUELHH rows for an inclusive settlement-date window."""
        if end < start:
            raise ValueError("FUELHH end date precedes start date")
        return self._get_records(
            FUELHH_PATH,
            {
                "settlementDateFrom": start.isoformat(),
                "settlementDateTo": end.isoformat(),
                "fuelType": "WIND",
            },
        )

    def fetch_windfor(
        self, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """Fetch WINDFOR rows for an inclusive publication-time window."""
        if end <= start:
            raise ValueError("WINDFOR end timestamp must be after start")
        return self._get_records(
            WINDFOR_PATH,
            {
                "publishDateTimeFrom": _utc_parameter(start),
                "publishDateTimeTo": _utc_parameter(end),
            },
        )

    def _get_records(
        self, path: str, params: Mapping[str, str] | Sequence[tuple[str, str]]
    ) -> list[dict[str, Any]]:
        url = f"{self.base_url}{path}"
        last_error: BaseException | None = None
        for attempt in range(1, self.max_attempts + 1):
            response: requests.Response | None = None
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                if response.status_code in TRANSIENT_STATUS_CODES:
                    if attempt == self.max_attempts:
                        raise ElexonRequestError(
                            self._http_message(response, url, exhausted=True)
                        )
                    delay = self._retry_delay(response, attempt)
                    LOGGER.warning(
                        "Transient Elexon HTTP %s for %s (attempt %s/%s); "
                        "retrying in %.2fs",
                        response.status_code,
                        response.url or url,
                        attempt,
                        self.max_attempts,
                        delay,
                    )
                    self._sleep(delay)
                    continue
                if not 200 <= response.status_code < 300:
                    raise ElexonRequestError(self._http_message(response, url))
                return self._validate_payload(response, url)
            except ElexonResponseError:
                LOGGER.exception("Invalid Elexon response from %s", url)
                raise
            except ElexonRequestError as exc:
                LOGGER.error("Elexon request failed: %s", exc)
                raise
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    break
                delay = self._backoff(attempt)
                LOGGER.warning(
                    "Elexon connection/read failure for %s (attempt %s/%s): %s; "
                    "retrying in %.2fs",
                    url,
                    attempt,
                    self.max_attempts,
                    exc,
                    delay,
                )
                self._sleep(delay)
            except requests.RequestException as exc:
                LOGGER.error("Non-retryable Elexon request failure for %s: %s", url, exc)
                raise ElexonRequestError(f"Request failed for {url}: {exc}") from exc

        message = (
            f"Request failed for {url} after {self.max_attempts} attempts: "
            f"{last_error}"
        )
        LOGGER.error(message)
        raise ElexonRequestError(message) from last_error

    def _validate_payload(
        self, response: requests.Response, fallback_url: str
    ) -> list[dict[str, Any]]:
        try:
            payload = response.json()
        except (ValueError, requests.JSONDecodeError) as exc:
            raise ElexonResponseError(
                f"Non-JSON response from {response.url or fallback_url}: "
                f"{response.text[:300]}"
            ) from exc
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            payload = payload["data"]
        if not isinstance(payload, list):
            raise ElexonResponseError(
                f"Unexpected response from {response.url or fallback_url}: "
                f"expected a list, received {type(payload).__name__}"
            )
        if any(not isinstance(record, dict) for record in payload):
            raise ElexonResponseError(
                f"Response from {response.url or fallback_url} contains non-object rows"
            )
        return payload

    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        if response.status_code == 429:
            value = response.headers.get("Retry-After")
            if value:
                try:
                    return min(max(float(value), 0.0), 60.0)
                except ValueError:
                    pass
        return self._backoff(attempt)

    def _backoff(self, attempt: int) -> float:
        return min(self.backoff_seconds * (2 ** (attempt - 1)) + self._jitter() * 0.1, 60.0)

    @staticmethod
    def _http_message(
        response: requests.Response, fallback_url: str, *, exhausted: bool = False
    ) -> str:
        suffix = " after retries" if exhausted else ""
        return (
            f"Elexon returned HTTP {response.status_code}{suffix} for "
            f"{response.url or fallback_url}: {response.text[:500]}"
        )
