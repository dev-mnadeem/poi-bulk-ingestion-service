"""CSV parser for PoI files.

Uses the standard library ``csv`` module rather than pandas. The importer
consumes records one at a time, so a DataFrame buys nothing here and costs a
pandas + numpy dependency (~60 MB installed) plus the memory of a whole chunk.
``csv.DictReader`` streams row by row in constant memory.
"""

from __future__ import annotations

import csv
import sys
from collections.abc import Iterator

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

# Some published PoI exports carry a single very long ratings field. Raise the
# field-size ceiling so those rows parse instead of blowing up mid-file.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def parse_ratings(raw: str) -> list[float]:
    """Parse the CSV ratings column, which looks like ``{3.0,4.0,5.0}``.

    Returns an empty list for ``{}`` so an unrated PoI is kept with an average
    of 0.0 rather than discarded.
    """
    text = require(raw, "poi_ratings")
    if not (text.startswith("{") and text.endswith("}")):
        raise RecordError(f"ratings field is not brace-delimited: {raw!r}")
    inner = text[1:-1].strip()
    if not inner:
        return []
    try:
        return [float(part) for part in inner.split(",")]
    except ValueError as exc:
        raise RecordError(f"ratings field holds a non-number: {raw!r}") from exc


class CsvParser:
    """Streams PoI records out of a comma-separated file."""

    extensions = (".csv",)

    #: Columns that must be present for the file to be usable at all.
    REQUIRED_COLUMNS = frozenset(
        {
            "poi_id",
            "poi_name",
            "poi_category",
            "poi_latitude",
            "poi_longitude",
            "poi_ratings",
        }
    )

    def parse(self, file_path: str) -> Iterator[ParseOutcome]:
        with open(file_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                # Genuinely empty file. An import of nothing is not an error.
                return
            missing = self.REQUIRED_COLUMNS - set(reader.fieldnames)
            if missing:
                raise ParseError("missing required column(s): " + ", ".join(sorted(missing)))
            for line_number, row in enumerate(reader, start=2):
                try:
                    yield self._to_record(row)
                except RecordError as exc:
                    yield SkippedRecord(f"line {line_number}", str(exc))

    @staticmethod
    def _to_record(row: dict[str, str | None]) -> PoIRecord:
        return PoIRecord(
            external_id=require(row.get("poi_id"), "poi_id"),
            name=require(row.get("poi_name"), "poi_name"),
            category=require(row.get("poi_category"), "poi_category"),
            latitude=to_float(row.get("poi_latitude"), "poi_latitude"),
            longitude=to_float(row.get("poi_longitude"), "poi_longitude"),
            avg_rating=mean_rating(parse_ratings(row.get("poi_ratings") or "")),
        )
