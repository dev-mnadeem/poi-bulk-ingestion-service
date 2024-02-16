"""Parser contract shared by every supported PoI file format."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol


class RecordError(ValueError):
    """Internal signal that one record is unusable.

    Parsers raise this from their per-record conversion helpers and convert it
    to a :class:`SkippedRecord` at the loop boundary; it never escapes a
    parser.
    """


class ParseError(ValueError):
    """Raised when a file as a whole cannot be read as PoI data.

    Examples: a required column is absent, the JSON document is not an array,
    the XML is not well formed. These abort the file, because importing a
    fraction of a misunderstood file is worse than importing none of it.

    A *single* bad record is not this. Parsers report those as
    :class:`SkippedRecord` values in the stream, so one bad row never kills
    the generator and the rest of the file still loads.
    """


@dataclass(frozen=True, slots=True)
class PoIRecord:
    """One validated point of interest, independent of its source format.

    Parsers yield these; the importer is the only thing that knows about the
    database. That keeps format handling free of ORM concerns and makes each
    parser testable on its own.
    """

    external_id: str
    name: str
    category: str
    latitude: float
    longitude: float
    avg_rating: float


@dataclass(frozen=True, slots=True)
class SkippedRecord:
    """One source entry that could not be understood, and why.

    Carried in the stream rather than raised. A generator that raises is
    finished, so raising per record would silently truncate the import at the
    first bad row.
    """

    location: str
    reason: str

    def __str__(self) -> str:
        return f"{self.location}: {self.reason}"


#: What a parser yields: a usable record, or a note about one that was not.
ParseOutcome = PoIRecord | SkippedRecord


class Parser(Protocol):
    """Reads a file and yields :class:`ParseOutcome` values lazily.

    Implementations MUST stream. Returning a fully materialised list defeats
    the importer's batching and reintroduces whole-file memory use.
    """

    #: Lower-case file extensions this parser claims, e.g. ``(".csv",)``.
    extensions: tuple[str, ...]

    def parse(self, file_path: str) -> Iterator[ParseOutcome]:
        """Yield one outcome per entry in ``file_path``."""
        ...


def mean_rating(values: Sequence[float]) -> float:
    """Average a list of ratings, treating an empty list as ``0.0``.

    Source files legitimately contain PoIs that nobody has rated yet, so an
    empty rating list is data rather than an error. ``float()`` happily reads
    ``"nan"`` and ``"inf"``, and one of those would poison the average, so
    non-finite ratings reject the record.
    """
    if not values:
        return 0.0
    if not all(math.isfinite(value) for value in values):
        raise RecordError(f"ratings must be finite numbers, got {list(values)!r}")
    return float(statistics.fmean(values))


def require(value: object, field: str) -> str:
    """Return ``value`` as a stripped string, or raise :class:`RecordError`.

    Used for fields that must be present and non-empty for a record to mean
    anything at all.
    """
    if value is None:
        raise RecordError(f"missing required field {field!r}")
    text = str(value).strip()
    if not text:
        raise RecordError(f"empty required field {field!r}")
    return text


def to_float(value: object, field: str) -> float:
    """Coerce ``value`` to a finite ``float`` or raise :class:`RecordError`.

    NaN and infinity are rejected here rather than at the database: SQLite
    stores NaN as NULL, so a single ``nan`` cell used to fail the NOT NULL
    constraint and abort the whole import with an IntegrityError.
    """
    try:
        number = float(require(value, field))
    except RecordError:
        raise
    except (TypeError, ValueError) as exc:
        raise RecordError(f"field {field!r} is not a number: {value!r}") from exc
    if not math.isfinite(number):
        raise RecordError(f"field {field!r} is not a finite number: {value!r}")
    return number


def to_coordinate(value: object, field: str, limit: float) -> float:
    """Coerce ``value`` to a float within ``[-limit, limit]`` degrees.

    ``limit`` is 90 for a latitude and 180 for a longitude. A value outside
    that range is a broken record, not a place, so it is skipped.
    """
    number = to_float(value, field)
    if not -limit <= number <= limit:
        raise RecordError(f"field {field!r} is outside -{limit:g}..{limit:g}: {value!r}")
    return number
