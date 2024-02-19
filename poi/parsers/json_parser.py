"""JSON parser for PoI files."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from .base import (
    ParseError,
    ParseOutcome,
    PoIRecord,
    RecordError,
    SkippedRecord,
    mean_rating,
    require,
    to_float,
)


class JsonParser:
    """Streams PoI records out of a JSON array of objects.

    The file is read with ``json.load``, so the document is held in memory
    once. The standard library has no incremental array reader and pulling in
    a streaming JSON dependency was not worth it for the file sizes this tool
    targets; see the README's Limitations section.
    """

    extensions = (".json",)

    def parse(self, file_path: str) -> Iterator[ParseOutcome]:
        with open(file_path, encoding="utf-8") as handle:
            try:
                payload = json.load(handle)
            except json.JSONDecodeError as exc:
                raise ParseError(f"invalid JSON: {exc}") from exc
        if not isinstance(payload, list):
            raise ParseError("expected a JSON array of objects")
        for index, item in enumerate(payload):
            try:
                yield self._to_record(item)
            except RecordError as exc:
                yield SkippedRecord(f"item {index}", str(exc))

    @staticmethod
    def _to_record(item: Any) -> PoIRecord:
        if not isinstance(item, dict):
            raise RecordError(f"expected a JSON object, got {type(item).__name__}")
        coordinates = item.get("coordinates")
        if not isinstance(coordinates, dict):
            raise RecordError("missing or malformed 'coordinates' object")
        ratings = item.get("ratings") or []
        if not isinstance(ratings, list):
            raise RecordError(f"'ratings' must be a list, got {type(ratings).__name__}")
        try:
            values = [float(value) for value in ratings]
        except (TypeError, ValueError) as exc:
            raise RecordError(f"'ratings' holds a non-number: {ratings!r}") from exc
        return PoIRecord(
            external_id=require(item.get("id"), "id"),
            name=require(item.get("name"), "name"),
            category=require(item.get("category"), "category"),
            latitude=to_float(coordinates.get("latitude"), "coordinates.latitude"),
            longitude=to_float(coordinates.get("longitude"), "coordinates.longitude"),
            avg_rating=mean_rating(values),
        )
