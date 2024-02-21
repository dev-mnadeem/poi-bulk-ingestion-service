"""Parser tests.

These read the committed fixture files directly. The previous suite mocked
``pandas.read_csv``, ``builtins.open``, ``json.load`` and
``ElementTree.parse``, which meant the fixture files were never opened and the
parsers' actual field mapping was never checked.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from poi.parsers import UnsupportedFormat, get_parser, supported_extensions
from poi.parsers.base import ParseError, PoIRecord, RecordError, SkippedRecord
from poi.parsers.csv_parser import CsvParser, parse_ratings
from poi.parsers.json_parser import JsonParser
from poi.parsers.xml_parser import XmlParser

from .support import fixture


def collect(parser, name: str) -> tuple[list[PoIRecord], list[SkippedRecord]]:
    """Run ``parser`` over a fixture, separating good records from skips.

    Note that this consumes the *whole* stream. A per-record failure must not
    end it early: an earlier implementation raised out of the generator, which
    truncated the import at the first bad row.
    """
    records: list[PoIRecord] = []
    skipped: list[SkippedRecord] = []
    for outcome in parser.parse(fixture(name)):
        (skipped if isinstance(outcome, SkippedRecord) else records).append(outcome)
    return records, skipped


class CsvParserTests(SimpleTestCase):
    """The CSV parser against real comma-separated fixtures."""

    def test_maps_every_column_to_the_right_field(self):
        """Each source column must land in its own field, not a neighbour's.

        The old XML test asserted only a row count, which let a completely
        scrambled mapping pass. This checks the values themselves.
        """
        records, skipped = collect(CsvParser(), "dummy.csv")
        self.assertEqual(skipped, [])
        self.assertEqual(len(records), 10)
        # Independently read off row 1 of poi/test_files/dummy.csv.
        self.assertEqual(
            records[0],
            PoIRecord(
                external_id="1806848972",
                name="ちぬまん",
                category="restaurant",
                latitude=26.2155192001422,
                longitude=127.6854314,
                # {3,4,3,5,2,3,2,2,2,2} -> 28/10
                avg_rating=2.8,
            ),
        )
        self.assertEqual(records[1].external_id, "428667258")
        self.assertEqual(records[1].name, "Otter Creek State Forest")
        self.assertEqual(records[1].category, "nature-reserve")

    def test_non_ascii_names_survive_parsing(self):
        records, _ = collect(CsvParser(), "dummy.csv")
        names = {record.name for record in records}
        self.assertIn("Солдатский пляж", names)
        self.assertIn("76-р цэцэрлэг", names)

    def test_extra_columns_are_ignored(self):
        records, skipped = collect(CsvParser(), "extra_column.csv")
        self.assertEqual(skipped, [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].external_id, "4")
        self.assertEqual(records[0].avg_rating, 2.0)

    def test_empty_file_yields_nothing_rather_than_raising(self):
        """A header-less, contentless CSV is an import of zero rows.

        The previous implementation let pandas' ``EmptyDataError`` escape, so
        an empty file aborted the run.
        """
        records, skipped = collect(CsvParser(), "empty_data.csv")
        self.assertEqual((records, skipped), ([], []))

    def test_row_with_a_blank_required_value_is_rejected(self):
        records, skipped = collect(CsvParser(), "incomplete_data.csv")
        self.assertEqual(records, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("poi_longitude", skipped[0].reason)
        self.assertEqual(skipped[0].location, "line 2")

    def test_row_with_non_numeric_coordinates_is_rejected(self):
        records, skipped = collect(CsvParser(), "invalid_data.csv")
        self.assertEqual(records, [])
        self.assertIn("poi_latitude", skipped[0].reason)

    def test_malformed_ratings_are_rejected(self):
        records, skipped = collect(CsvParser(), "malformed_ratings.csv")
        self.assertEqual(records, [])
        self.assertIn("brace-delimited", skipped[0].reason)

    def test_missing_required_column_fails_the_whole_file(self):
        """A structural problem aborts the file rather than skipping rows."""
        with self.assertRaises(ParseError) as caught:
            collect(CsvParser(), "missing_column.csv")
        self.assertIn("poi_category", str(caught.exception))

    def test_unrated_poi_is_kept_with_a_zero_average(self):
        """``{}`` means nobody has rated it yet, which is data, not an error."""
        records, skipped = collect(CsvParser(), "unrated_and_duplicate.csv")
        self.assertEqual(skipped, [])
        self.assertEqual(records[0].external_id, "7")
        self.assertEqual(records[0].avg_rating, 0.0)

    def test_parse_ratings_table(self):
        """Ratings parsing against an independently derived expectation."""
        for raw, expected in [
            ("{5,4,3}", [5.0, 4.0, 3.0]),
            ("{2.5}", [2.5]),
            ("{}", []),
            ("{ 1 , 2 }", [1.0, 2.0]),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(parse_ratings(raw), expected)
        for raw in ["5,4,3", "{a,b}", "", "   "]:
            with self.subTest(raw=raw), self.assertRaises(RecordError):
                parse_ratings(raw)


class JsonParserTests(SimpleTestCase):
    """The JSON parser against real JSON fixtures."""

    def test_maps_every_field_including_nested_coordinates(self):
        records, skipped = collect(JsonParser(), "valid_data.json")
        self.assertEqual(skipped, [])
        self.assertEqual(
            records,
            [
                PoIRecord("1", "POI 1", "Category 1", 10.0, 20.0, 4.0),
                PoIRecord("2", "POI 2", "Category 2", 15.0, 25.0, 3.0),
            ],
        )

    def test_empty_array_yields_nothing(self):
        self.assertEqual(collect(JsonParser(), "empty_data.json"), ([], []))

    def test_a_bad_item_does_not_truncate_the_stream(self):
        """Regression: one unusable item must not end the whole file."""
        records, skipped = collect(JsonParser(), "edge_cases.json")
        # id 30 has an empty ratings list -> kept with avg 0.0.
        self.assertEqual([record.external_id for record in records], ["30"])
        self.assertEqual(records[0].avg_rating, 0.0)
        # id 31 has no coordinates; id 32 has a non-list ratings value. Both
        # are reported, and crucially item 32 is still reached after item 31
        # failed.
        self.assertEqual([skip.location for skip in skipped], ["item 1", "item 2"])
        self.assertIn("coordinates", skipped[0].reason)
        self.assertIn("ratings", skipped[1].reason)


class XmlParserTests(SimpleTestCase):
    """The XML parser against real XML fixtures."""

    def test_maps_every_tag_to_the_right_field(self):
        """Regression test for a scrambled tag-to-field mapping.

        The replaced test fed a ``MagicMock`` whose ``find`` returned values in
        a fixed sequence, so it silently stored the name in ``category`` and
        the ratings string in ``category`` too, and still passed because it
        only counted rows.
        """
        records, skipped = collect(XmlParser(), "valid_data.xml")
        self.assertEqual(skipped, [])
        self.assertEqual(
            records,
            [
                PoIRecord("1", "POI 1", "Category 1", 10.0, 20.0, 4.0),
                PoIRecord("2", "POI 2", "Category 2", 15.0, 25.0, 3.0),
            ],
        )

    def test_empty_document_yields_nothing(self):
        self.assertEqual(collect(XmlParser(), "empty_data.xml"), ([], []))

    def test_edge_cases(self):
        records, skipped = collect(XmlParser(), "edge_cases.xml")
        # pid 20 has an empty <pratings/> -> kept with avg 0.0.
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].external_id, "20")
        self.assertEqual(records[0].avg_rating, 0.0)
        # pid 21 has a non-numeric latitude.
        self.assertEqual(len(skipped), 1)
        self.assertIn("platitude", skipped[0].reason)

    def test_malformed_document_raises(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as handle:
            handle.write("<PointsOfInterest><POI></PointsOfInterest>")
        with self.assertRaises(ParseError):
            list(XmlParser().parse(handle.name))


class RegistryTests(SimpleTestCase):
    """The parser registry — the project's format-extension seam."""

    def test_known_extensions_resolve_to_their_parser(self):
        self.assertIsInstance(get_parser("a.csv"), CsvParser)
        self.assertIsInstance(get_parser("a.JSON"), JsonParser)
        self.assertIsInstance(get_parser("/tmp/b.xml"), XmlParser)

    def test_unknown_extension_is_rejected_with_a_useful_message(self):
        with self.assertRaises(UnsupportedFormat) as caught:
            get_parser("places.geojson")
        self.assertIn(".csv", str(caught.exception))

    def test_supported_extensions_are_reported(self):
        self.assertEqual(list(supported_extensions()), [".csv", ".json", ".xml"])
