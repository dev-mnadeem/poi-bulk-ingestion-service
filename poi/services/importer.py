"""Import orchestration: parse a file, validate it, persist it in batches.

This is the only layer that talks to both the parsers and the ORM. The
management command, the Celery tasks and the tests all go through
:func:`import_file`, so there is exactly one definition of what "importing a
PoI file" means.
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from django.db import transaction

from poi.models import PointOfInterest
from poi.parsers import ParseOutcome, PoIRecord, SkippedRecord, get_parser

logger = logging.getLogger(__name__)

#: Rows sent to the database per INSERT. Large enough that per-statement
#: overhead stops mattering, small enough to stay well inside SQLite's
#: 999-variable limit at 6 columns per row and to bound memory.
DEFAULT_BATCH_SIZE = 500

#: Rejected rows are logged individually up to this many per file, then
#: summarised. Prevents a pathological file from producing gigabytes of logs.
MAX_REPORTED_ERRORS = 20


@dataclass
class ImportResult:
    """What one call to :func:`import_file` did."""

    file_path: str
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def written(self) -> int:
        """Total rows persisted, whether inserted or refreshed."""
        return self.created + self.updated

    def __str__(self) -> str:
        return (
            f"{self.file_path}: {self.created} created, {self.updated} updated, "
            f"{self.skipped} skipped"
        )


def _batched(iterable: Iterable[PoIRecord], size: int) -> Iterator[list[PoIRecord]]:
    """Yield successive lists of at most ``size`` items."""
    iterator = iter(iterable)
    while batch := list(itertools.islice(iterator, size)):
        yield batch


def _usable(outcomes: Iterable[ParseOutcome], result: ImportResult) -> Iterator[PoIRecord]:
    """Yield the records from a parser stream, tallying the skipped ones."""
    for outcome in outcomes:
        if isinstance(outcome, SkippedRecord):
            result.skipped += 1
            if len(result.errors) < MAX_REPORTED_ERRORS:
                result.errors.append(str(outcome))
            logger.warning("%s: %s", result.file_path, outcome)
            continue
        yield outcome


def _deduplicate(batch: list[PoIRecord], result: ImportResult) -> list[PoIRecord]:
    """Collapse repeated ``external_id`` values in one batch, keeping the last.

    A single INSERT may not name the same ON CONFLICT target twice, so a batch
    holding an ID twice would be rejected outright. Keeping the *last*
    occurrence matches what the upsert does across batches, which makes the
    result "last occurrence in the file wins" regardless of batch size.

    Deduplicating per batch rather than per file is deliberate: a file-wide
    ``seen`` set is O(rows) in memory and was the largest allocation in the
    importer at 200k rows.
    """
    collapsed: dict[str, PoIRecord] = {}
    for record in batch:
        if record.external_id in collapsed:
            result.skipped += 1
            if len(result.errors) < MAX_REPORTED_ERRORS:
                result.errors.append(
                    f"duplicate external_id {record.external_id!r}; kept the later row"
                )
        collapsed[record.external_id] = record
    return list(collapsed.values())


def import_file(file_path: str, batch_size: int = DEFAULT_BATCH_SIZE) -> ImportResult:
    """Import one PoI file and return a summary of what happened.

    Records are streamed from the parser and written with ``bulk_create`` in
    batches of ``batch_size``, upserting on ``external_id`` so re-importing a
    file refreshes rows instead of duplicating them. Memory stays bounded by
    ``batch_size`` rather than by the size of the file.

    Raises:
        UnsupportedFormat: the extension has no registered parser.
        ParseError: the file as a whole is unusable (e.g. a missing column).
            Individual bad rows do not raise; they land in ``result.skipped``.
        OSError: the file cannot be read.
    """
    result = ImportResult(file_path=file_path)
    parser = get_parser(file_path)
    records = _usable(parser.parse(file_path), result)

    for raw_batch in _batched(records, batch_size):
        batch = _deduplicate(raw_batch, result)
        external_ids = [record.external_id for record in batch]
        with transaction.atomic():
            existing = set(
                PointOfInterest.objects.filter(external_id__in=external_ids).values_list(
                    "external_id", flat=True
                )
            )
            PointOfInterest.objects.bulk_create(
                [
                    PointOfInterest(
                        external_id=record.external_id,
                        name=record.name,
                        category=record.category,
                        latitude=record.latitude,
                        longitude=record.longitude,
                        avg_rating=record.avg_rating,
                    )
                    for record in batch
                ],
                update_conflicts=True,
                unique_fields=["external_id"],
                update_fields=["name", "category", "latitude", "longitude", "avg_rating"],
            )
        result.updated += len(existing)
        result.created += len(batch) - len(existing)

    return result
