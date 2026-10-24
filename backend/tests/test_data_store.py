"""Processed-file availability and corruption tests using synthetic JSON."""

from __future__ import annotations

import json

import pytest

from backend.app.services.data_store import (
    HistoricalDataCorruptionError,
    HistoricalDataStore,
    HistoricalDataUnavailableError,
)


def test_missing_processed_directories_are_explicit(tmp_path) -> None:
    with pytest.raises(HistoricalDataUnavailableError, match="directory is missing"):
        HistoricalDataStore.from_processed_directory(tmp_path)


def test_corrupted_processed_json_is_explicit(tmp_path) -> None:
    fuel = tmp_path / "fuelhh"
    wind = tmp_path / "windfor"
    fuel.mkdir()
    wind.mkdir()
    (fuel / "2026-01-02.json").write_text("{broken", encoding="utf-8")
    (wind / "2026-01-01.json").write_text(
        json.dumps({"dataset": "WINDFOR", "record_count": 0, "records": []}),
        encoding="utf-8",
    )
    with pytest.raises(HistoricalDataCorruptionError, match="malformed"):
        HistoricalDataStore.from_processed_directory(tmp_path)


def test_declared_record_count_must_match(tmp_path) -> None:
    for directory, dataset in (("fuelhh", "FUELHH"), ("windfor", "WINDFOR")):
        path = tmp_path / directory
        path.mkdir()
        (path / "batch.json").write_text(
            json.dumps({"dataset": dataset, "record_count": 1, "records": []}),
            encoding="utf-8",
        )
    with pytest.raises(HistoricalDataCorruptionError, match="record_count mismatch"):
        HistoricalDataStore.from_processed_directory(tmp_path)
