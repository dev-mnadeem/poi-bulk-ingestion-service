"""``manage.py import_poi`` — load PoI data from CSV, JSON or XML files."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from poi.parsers import ParseError, UnsupportedFormat, supported_extensions
from poi.services import DEFAULT_BATCH_SIZE, import_file
from poi.tasks import import_poi_file


class Command(BaseCommand):
    """Import Point of Interest data files.

    Runs in-process by default, which is what you want for a one-off load and
    for anything you need an exit code from. Pass ``--async`` to hand each
    file to a Celery worker instead.
    """

    help = "Import PoI data from CSV, JSON and XML files."

    def add_arguments(self, parser):
        parser.add_argument(
            "files",
            nargs="+",
            metavar="FILE",
            help=f"Paths to import. Supported: {', '.join(supported_extensions())}",
        )
        parser.add_argument(
            "--async",
            dest="run_async",
            action="store_true",
            help="Queue each file on Celery instead of importing in-process.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Rows per bulk insert (default: {DEFAULT_BATCH_SIZE}).",
        )

    def handle(self, *args, **options):
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1")

        if options["run_async"]:
            for file_path in options["files"]:
                import_poi_file.delay(file_path)
                self.stdout.write(f"queued {file_path}")
            self.stdout.write(
                self.style.SUCCESS(f"Queued {len(options['files'])} file(s) for import.")
            )
            return

        totals = {"created": 0, "updated": 0, "skipped": 0}
        failures = 0
        for file_path in options["files"]:
            try:
                result = import_file(file_path, batch_size=options["batch_size"])
            except (UnsupportedFormat, ParseError, OSError) as exc:
                failures += 1
                self.stderr.write(self.style.ERROR(f"{file_path}: {exc}"))
                continue
            for key in totals:
                totals[key] += getattr(result, key)
            style = self.style.WARNING if result.skipped else self.style.SUCCESS
            self.stdout.write(style(str(result)))

        summary = (
            f"Imported {totals['created']} new and {totals['updated']} updated "
            f"PoI records, skipped {totals['skipped']}."
        )
        if failures:
            raise CommandError(f"{summary} {failures} file(s) could not be read.")
        self.stdout.write(self.style.SUCCESS(summary))
