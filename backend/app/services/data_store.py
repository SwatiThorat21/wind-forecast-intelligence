"""Validated in-memory access to processed Phase 2B historical JSON."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .data_normalization import (
    aggregate_complete_actual_hours,
    numeric_generation,
    parse_timestamp,
)


class HistoricalDataError(RuntimeError):
    """Base class for processed historical-data failures."""


class HistoricalDataUnavailableError(HistoricalDataError):
    """Raised when required processed files are absent."""


class HistoricalDataCorruptionError(HistoricalDataError):
    """Raised when a processed file does not match the Phase 2B schema."""


class HistoricalDataStore:
    """Immutable indexes built once from normalized actual and forecast rows."""

    def __init__(
        self,
        actual_records: Iterable[dict[str, Any]],
        forecast_records: Iterable[dict[str, Any]],
        *,
        source_files: Iterable[str] = (),
    ) -> None:
        self.actual_records = tuple(actual_records)
        self.forecast_records = tuple(forecast_records)
        self.source_files = tuple(source_files)

        for index, record in enumerate(self.actual_records):
            try:
                parse_timestamp(record.get("start_time"), "start_time")
                publish_time = record.get("publish_time")
                if publish_time is not None:
                    parse_timestamp(publish_time, "publish_time")
                numeric_generation(record.get("generation_mw"))
            except ValueError as exc:
                raise HistoricalDataCorruptionError(
                    f"actual record {index} is invalid: {exc}"
                ) from exc

        hourly_actuals, actual_warnings = aggregate_complete_actual_hours(
            self.actual_records
        )
        self.actual_warnings = tuple(actual_warnings)
        self.hourly_actual_by_start = {
            parse_timestamp(row["start_time"], "start_time"): row
            for row in hourly_actuals
        }

        forecast_index: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for index, record in enumerate(self.forecast_records):
            try:
                start = parse_timestamp(record.get("start_time"), "start_time")
                publish = parse_timestamp(record.get("publish_time"), "publish_time")
                generation = numeric_generation(record.get("generation_mw"))
            except ValueError as exc:
                raise HistoricalDataCorruptionError(
                    f"forecast record {index} is invalid: {exc}"
                ) from exc
            indexed = dict(record)
            indexed["_start"] = start
            indexed["_publish"] = publish
            indexed["generation_mw"] = generation
            forecast_index[start].append(indexed)
        self.forecast_history_by_target = {
            target: tuple(sorted(rows, key=lambda row: row["_publish"]))
            for target, rows in forecast_index.items()
        }

    @classmethod
    def from_processed_directory(cls, processed_root: Path | str) -> "HistoricalDataStore":
        root = Path(processed_root)
        actual_records, actual_files = _load_dataset(root / "fuelhh", "FUELHH")
        forecast_records, forecast_files = _load_dataset(
            root / "windfor", "WINDFOR"
        )
        return cls(
            actual_records,
            forecast_records,
            source_files=(*actual_files, *forecast_files),
        )

    @property
    def availability(self) -> dict[str, Any]:
        return {
            "actualRecords": len(self.actual_records),
            "forecastRecords": len(self.forecast_records),
            "completeHourlyActuals": len(self.hourly_actual_by_start),
            "forecastTargets": len(self.forecast_history_by_target),
            "sourceFiles": len(self.source_files),
            "actualAggregationWarnings": len(self.actual_warnings),
        }


def _load_dataset(
    directory: Path, expected_dataset: str
) -> tuple[list[dict[str, Any]], list[str]]:
    if not directory.is_dir():
        raise HistoricalDataUnavailableError(
            f"processed {expected_dataset} directory is missing: {directory}"
        )
    files = sorted(directory.glob("*.json"))
    if not files:
        raise HistoricalDataUnavailableError(
            f"no processed {expected_dataset} JSON files found in {directory}"
        )

    records: list[dict[str, Any]] = []
    loaded_files: list[str] = []
    for path in files:
        try:
            with path.open(encoding="utf-8") as handle:
                envelope = json.load(handle)
        except json.JSONDecodeError as exc:
            raise HistoricalDataCorruptionError(
                f"processed JSON is malformed: {path}: {exc}"
            ) from exc
        except OSError as exc:
            raise HistoricalDataUnavailableError(
                f"could not read processed file {path}: {exc}"
            ) from exc

        if not isinstance(envelope, dict):
            raise HistoricalDataCorruptionError(f"expected JSON object in {path}")
        if envelope.get("dataset") != expected_dataset:
            raise HistoricalDataCorruptionError(
                f"expected dataset {expected_dataset} in {path}, "
                f"received {envelope.get('dataset')!r}"
            )
        batch_records = envelope.get("records")
        if not isinstance(batch_records, list) or any(
            not isinstance(record, dict) for record in batch_records
        ):
            raise HistoricalDataCorruptionError(
                f"records must be a list of objects in {path}"
            )
        declared_count = envelope.get("record_count")
        if declared_count != len(batch_records):
            raise HistoricalDataCorruptionError(
                f"record_count mismatch in {path}: declared {declared_count!r}, "
                f"found {len(batch_records)}"
            )
        records.extend(batch_records)
        loaded_files.append(str(path))

    return records, loaded_files
