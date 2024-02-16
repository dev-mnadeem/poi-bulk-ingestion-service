"""Benchmark: per-row ``objects.create`` vs batched ``bulk_create``.

Generates a synthetic PoI CSV, imports it both ways against the same SQLite
database, and reports wall time, peak Python memory and SQL statement count.
Run with:

    python docs/benchmark_import.py [ROWS ...]
"""

from __future__ import annotations

import os
import random
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "SearchSmartly.settings")
# DEBUG must be off: with it on, Django retains the SQL text of every query in
# connection.queries, and a batched import's few very large INSERT statements
# dominate the memory reading, measuring the query log rather than the importer.
os.environ["DJANGO_DEBUG"] = "0"
os.environ.setdefault("DJANGO_SECRET_KEY", "benchmark-only-not-a-real-key")
os.environ.setdefault("DJANGO_LOG_LEVEL", "WARNING")

import django

django.setup()

from django.db import connection  # noqa: E402
from django.test.utils import setup_test_environment  # noqa: E402

from poi.models import PointOfInterest  # noqa: E402
from poi.parsers.csv_parser import CsvParser  # noqa: E402
from poi.services import import_file  # noqa: E402

CATEGORIES = ["restaurant", "bus-stop", "beach", "cafe", "kindergarten", "fast-food"]


def make_csv(rows: int) -> str:
    """Write a synthetic PoI CSV and return its path."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="")
    handle.write("poi_id,poi_name,poi_category,poi_latitude,poi_longitude,poi_ratings\n")
    rng = random.Random(1234)
    for index in range(rows):
        ratings = ",".join(f"{rng.uniform(1, 5):.1f}" for _ in range(10))
        handle.write(
            f"{index},PoI number {index},{CATEGORIES[index % len(CATEGORIES)]},"
            f"{rng.uniform(-90, 90):.6f},{rng.uniform(-180, 180):.6f},"
            f'"{{{ratings}}}"\n'
        )
    handle.close()
    return handle.name


def make_xml(rows: int) -> str:
    """Write a synthetic PoI XML document and return its path."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False)
    handle.write("<PointsOfInterest>\n")
    rng = random.Random(1234)
    for index in range(rows):
        ratings = ",".join(f"{rng.uniform(1, 5):.1f}" for _ in range(10))
        handle.write(
            f"  <POI><pid>{index}</pid><pname>PoI number {index}</pname>"
            f"<pcategory>{CATEGORIES[index % len(CATEGORIES)]}</pcategory>"
            f"<platitude>{rng.uniform(-90, 90):.6f}</platitude>"
            f"<plongitude>{rng.uniform(-180, 180):.6f}</plongitude>"
            f"<pratings>{ratings}</pratings></POI>\n"
        )
    handle.write("</PointsOfInterest>\n")
    handle.close()
    return handle.name


def legacy_xml_parse(file_path: str) -> int:
    """The original XML strategy: build the whole tree, then walk it."""
    import xml.etree.ElementTree as ElementTree

    tree = ElementTree.parse(file_path)
    return sum(1 for _ in tree.getroot())


def streaming_xml_parse(file_path: str) -> int:
    """The current strategy: iterparse, clearing each element as it is read."""
    from poi.parsers.xml_parser import XmlParser

    return sum(1 for _ in XmlParser().parse(file_path))


def measure_parse(label: str, function, path: str) -> None:
    """Time a parser and report its peak allocation (no database involved)."""
    tracemalloc.start()
    started = time.perf_counter()
    count = function(path)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        f"{label:<34} {elapsed:8.2f}s  {count:>7} rows  "
        f"{'':>7}          {peak / 1024 / 1024:>7.1f} MB peak"
    )


def legacy_import(file_path: str) -> None:
    """The original strategy: one INSERT per row, no batching, no upsert."""
    for outcome in CsvParser().parse(file_path):
        if not hasattr(outcome, "external_id"):
            continue
        PointOfInterest.objects.create(
            external_id=outcome.external_id,
            name=outcome.name,
            category=outcome.category,
            latitude=outcome.latitude,
            longitude=outcome.longitude,
            avg_rating=outcome.avg_rating,
        )


class InsertCounter:
    """Counts INSERT statements via execute_wrapper.

    ``connection.queries`` caps at 9000 entries, which would silently
    under-report the legacy path's one-INSERT-per-row behaviour.
    """

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, execute, sql, params, many, context):
        if sql.lstrip().upper().startswith("INSERT"):
            self.count += 1
        return execute(sql, params, many, context)


def measure(label: str, function, *args) -> None:
    PointOfInterest.objects.all().delete()
    counter = InsertCounter()
    tracemalloc.start()
    started = time.perf_counter()
    with connection.execute_wrapper(counter):
        function(*args)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        f"{label:<34} {elapsed:8.2f}s  {PointOfInterest.objects.count():>7} rows  "
        f"{counter.count:>7} INSERTs  {peak / 1024 / 1024:>7.1f} MB peak"
    )


def main() -> None:
    sizes = [int(arg) for arg in sys.argv[1:]] or [50_000]
    setup_test_environment()
    connection.creation.create_test_db(verbosity=0)
    print(f"Python {sys.version.split()[0]}, SQLite {connection.Database.sqlite_version}")
    try:
        for rows in sizes:
            path = make_csv(rows)
            size_mb = os.path.getsize(path) / 1024 / 1024
            print(f"\n--- {rows:,} rows ({size_mb:.1f} MB CSV) ---")
            try:
                measure("legacy: objects.create per row", legacy_import, path)
                measure("current: bulk_create batch=500", import_file, path, 500)
                measure("current: bulk_create batch=1000", import_file, path, 1000)
            finally:
                os.unlink(path)

            xml_path = make_xml(rows)
            xml_mb = os.path.getsize(xml_path) / 1024 / 1024
            print(f"  XML parsing only ({xml_mb:.1f} MB document):")
            try:
                measure_parse("  legacy: ElementTree.parse", legacy_xml_parse, xml_path)
                measure_parse("  current: iterparse + clear", streaming_xml_parse, xml_path)
            finally:
                os.unlink(xml_path)
    finally:
        connection.creation.destroy_test_db(":memory:", verbosity=0)


if __name__ == "__main__":
    main()
