"""Celery entry points for PoI imports.

Deliberately thin. All of the import logic lives in
:mod:`poi.services.importer` so it can be exercised — and reasoned about —
without a broker, and so the management command and the task cannot drift
apart.
"""

from __future__ import annotations

import logging

from celery import shared_task

from poi.services import import_file

logger = logging.getLogger(__name__)


@shared_task(name="poi.import_file")
def import_poi_file(file_path: str) -> dict[str, object]:
    """Import one PoI file of any registered format.

    Returns a JSON-serialisable summary so the result is useful in a Celery
    result backend.
    """
    result = import_file(file_path)
    # A worker has no stdout for the caller to read, so the summary goes to the
    # log. The management command prints its own summary instead.
    logger.info("%s", result)
    return {
        "file_path": result.file_path,
        "created": result.created,
        "updated": result.updated,
        "skipped": result.skipped,
        "errors": result.errors,
    }
