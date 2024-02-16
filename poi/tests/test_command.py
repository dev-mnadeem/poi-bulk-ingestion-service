"""Tests for ``manage.py import_poi``."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from poi.models import PointOfInterest

from .support import fixture


class ImportPoiCommandTests(TestCase):
    def run_command(self, *args, **kwargs) -> tuple[str, str]:
        out, err = StringIO(), StringIO()
        call_command("import_poi", *args, stdout=out, stderr=err, **kwargs)
        return out.getvalue(), err.getvalue()

    def test_imports_several_files_of_different_formats_in_one_call(self):
        out, err = self.run_command(
            fixture("dummy.csv"), fixture("valid_data.json"), fixture("edge_cases.xml")
        )
        self.assertEqual(err, "")
        self.assertEqual(PointOfInterest.objects.count(), 13)
        self.assertIn("Imported 13 new and 0 updated", out)

    def test_reports_skipped_rows_without_failing(self):
        out, _ = self.run_command(fixture("edge_cases.json"))
        self.assertIn("skipped 2", out)
        self.assertEqual(PointOfInterest.objects.count(), 1)

    def test_an_unreadable_file_is_reported_and_fails_the_command(self):
        with self.assertRaises(CommandError):
            self.run_command(fixture("dummy.csv"), "/nonexistent/file.csv")
        # The good file still imported before the bad one was reported.
        self.assertEqual(PointOfInterest.objects.count(), 10)

    def test_unsupported_extension_is_reported(self):
        with self.assertRaises(CommandError):
            self.run_command("places.geojson")

    def test_rejects_a_nonsensical_batch_size(self):
        with self.assertRaises(CommandError):
            self.run_command(fixture("dummy.csv"), "--batch-size", "0")

    def test_async_mode_queues_instead_of_importing(self):
        with patch("poi.tasks.import_poi_file.delay") as delay:
            out, _ = self.run_command(fixture("dummy.csv"), "--async")
        delay.assert_called_once_with(fixture("dummy.csv"))
        self.assertIn("Queued 1 file(s)", out)
        self.assertEqual(PointOfInterest.objects.count(), 0)


class CeleryTaskTests(TestCase):
    def test_task_returns_a_serialisable_summary(self):
        from poi.tasks import import_poi_file

        result = import_poi_file.apply(args=[fixture("valid_data.json")]).get()
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(PointOfInterest.objects.count(), 2)
