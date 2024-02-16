"""Importer service tests: parsing, batching, upserting and error tolerance."""

from __future__ import annotations

from django.test import TestCase

from poi.models import PointOfInterest
from poi.parsers import UnsupportedFormat
from poi.parsers.base import ParseError
from poi.services import import_file

from .support import fixture


class ImportFileTests(TestCase):
    def test_csv_import_persists_every_field_correctly(self):
        result = import_file(fixture("dummy.csv"))

        self.assertEqual((result.created, result.updated, result.skipped), (10, 0, 0))
        self.assertEqual(PointOfInterest.objects.count(), 10)

        poi = PointOfInterest.objects.get(external_id="1806848972")
        self.assertEqual(poi.name, "ちぬまん")
        self.assertEqual(poi.category, "restaurant")
        self.assertAlmostEqual(poi.latitude, 26.2155192001422)
        self.assertAlmostEqual(poi.longitude, 127.6854314)
        self.assertEqual(poi.avg_rating, 2.8)

    def test_external_id_holds_the_source_id_and_internal_id_is_ours(self):
        """The two identifiers must not be swapped.

        ``external_id`` is the ID the record carried in the file;
        ``internal_id`` is this database's own key. The original model had
        these the wrong way round, which made "search by external ID" search
        the row number.
        """
        import_file(fixture("dummy.csv"))
        poi = PointOfInterest.objects.get(external_id="428667258")
        self.assertEqual(poi.external_id, "428667258")
        self.assertNotEqual(str(poi.internal_id), poi.external_id)
        self.assertEqual(
            sorted(PointOfInterest.objects.values_list("internal_id", flat=True)),
            list(range(1, 11)),
        )

    def test_reimporting_the_same_file_updates_instead_of_duplicating(self):
        first = import_file(fixture("dummy.csv"))
        second = import_file(fixture("dummy.csv"))

        self.assertEqual(first.created, 10)
        self.assertEqual((second.created, second.updated), (0, 10))
        self.assertEqual(PointOfInterest.objects.count(), 10)

    def test_a_bad_row_does_not_abort_the_file(self):
        result = import_file(fixture("edge_cases.xml"))
        self.assertEqual(result.created, 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(PointOfInterest.objects.count(), 1)
        self.assertIn("platitude", result.errors[0])

    def test_rows_after_a_bad_row_are_still_imported(self):
        """The bad item is in the middle, so truncation would be visible."""
        result = import_file(fixture("edge_cases.json"))
        self.assertEqual(result.skipped, 2)
        self.assertEqual(len(result.errors), 2)

    def test_duplicate_external_id_within_one_file_keeps_the_last(self):
        """Last occurrence wins, matching what a re-import would do."""
        result = import_file(fixture("unrated_and_duplicate.csv"))
        self.assertEqual(result.created, 2)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(PointOfInterest.objects.get(external_id="8").name, "Duplicate Again")

    def test_duplicate_handling_is_independent_of_batch_size(self):
        """A duplicate split across two batches resolves the same way."""
        for batch_size in (1, 2, 500):
            with self.subTest(batch_size=batch_size):
                PointOfInterest.objects.all().delete()
                import_file(fixture("unrated_and_duplicate.csv"), batch_size=batch_size)
                self.assertEqual(PointOfInterest.objects.count(), 2)
                self.assertEqual(
                    PointOfInterest.objects.get(external_id="8").name, "Duplicate Again"
                )

    def test_json_and_xml_produce_identical_records(self):
        """The two fixtures describe the same PoIs, so the rows must match."""
        import_file(fixture("valid_data.json"))
        from_json = list(
            PointOfInterest.objects.values("external_id", "name", "category", "avg_rating")
        )
        PointOfInterest.objects.all().delete()
        import_file(fixture("valid_data.xml"))
        from_xml = list(
            PointOfInterest.objects.values("external_id", "name", "category", "avg_rating")
        )
        self.assertEqual(from_json, from_xml)

    def test_empty_sources_import_zero_rows(self):
        for name in ["empty_data.csv", "empty_data.json", "empty_data.xml"]:
            with self.subTest(fixture=name):
                result = import_file(fixture(name))
                self.assertEqual(result.written, 0)
        self.assertEqual(PointOfInterest.objects.count(), 0)

    def test_batch_size_does_not_change_the_result(self):
        """Batching is an efficiency concern, never a correctness one."""
        import_file(fixture("dummy.csv"), batch_size=1)
        one_at_a_time = list(PointOfInterest.objects.values_list("external_id", "avg_rating"))
        PointOfInterest.objects.all().delete()
        import_file(fixture("dummy.csv"), batch_size=500)
        in_one_batch = list(PointOfInterest.objects.values_list("external_id", "avg_rating"))
        self.assertEqual(one_at_a_time, in_one_batch)

    def test_unsupported_extension_is_rejected(self):
        with self.assertRaises(UnsupportedFormat):
            import_file(fixture("dummy.csv").replace(".csv", ".geojson"))

    def test_missing_column_raises_rather_than_importing_garbage(self):
        with self.assertRaises(ParseError):
            import_file(fixture("missing_column.csv"))
        self.assertEqual(PointOfInterest.objects.count(), 0)

    def test_missing_file_raises_oserror(self):
        with self.assertRaises(OSError):
            import_file("/nonexistent/path/to/data.csv")


class ImportQueryCountTests(TestCase):
    """Guards the batching that replaced one INSERT per row."""

    @staticmethod
    def count_inserts(batch_size: int) -> int:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as captured:
            import_file(fixture("dummy.csv"), batch_size=batch_size)
        return sum(
            1
            for query in captured.captured_queries
            if query["sql"].lstrip().upper().startswith("INSERT")
        )

    def test_a_ten_row_file_is_one_insert_not_ten(self):
        """The original implementation issued one INSERT per row."""
        self.assertEqual(self.count_inserts(batch_size=500), 1)

    def test_batch_size_controls_the_number_of_inserts(self):
        self.assertEqual(self.count_inserts(batch_size=5), 2)

    def test_worst_case_batch_size_of_one_is_still_correct(self):
        self.assertEqual(self.count_inserts(batch_size=1), 10)
