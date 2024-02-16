"""Admin search and filtering, checked against an independent expectation table.

The admin is the product here: "browse PoI data, search by internal or
external ID, filter by category". These tests state what each query *should*
return, derived by hand from ``poi/test_files/dummy.csv``, and compare.
"""

from __future__ import annotations

from django.contrib.admin.sites import AdminSite
from django.core.paginator import Paginator
from django.test import RequestFactory, TestCase

from poi.admin import PointOfInterestAdmin
from poi.models import PointOfInterest
from poi.services import import_file

from .support import fixture

#: The ten source IDs in dummy.csv, in file order. internal_id 1..10 is
#: assigned in that same order by the import.
SOURCE_IDS = [
    "1806848972",
    "428667258",
    "813164026",
    "502595764",
    "486649349",
    "5477423259",
    "4390484395",
    "1679569885",
    "8927949261",
    "6233153785",
]


class AdminSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        import_file(fixture("dummy.csv"))

    def setUp(self):
        self.admin = PointOfInterestAdmin(PointOfInterest, AdminSite())
        self.request = RequestFactory().get("/admin/poi/pointofinterest/")

    def search(self, term: str) -> list[str]:
        queryset, _ = self.admin.get_search_results(
            self.request, PointOfInterest.objects.all(), term
        )
        return list(queryset.values_list("external_id", flat=True))

    def test_search_expectation_table(self):
        """Every case below was derived from the fixture, not from the code.

        The three ``exact`` cases are the ones the previous ``icontains``
        search got wrong: searching external ID ``1`` returned five records,
        and the partial ``180684`` matched a record whose ID merely contains
        it.
        """
        cases = [
            # (query, expected external_ids, why)
            ("1806848972", ["1806848972"], "exact source ID of row 1"),
            ("428667258", ["428667258"], "exact source ID of row 2"),
            ("6233153785", ["6233153785"], "exact source ID of the last row"),
            ("1", ["1806848972"], "internal_id 1 -> row 1 only"),
            ("10", ["6233153785"], "internal_id 10 -> row 10 only"),
            ("180684", [], "a partial ID is not an ID"),
            ("0684897", [], "an infix of a real ID is not an ID"),
            ("", SOURCE_IDS, "an empty query filters nothing"),
            ("   ", SOURCE_IDS, "a whitespace-only query filters nothing"),
            ("zzzznomatch", [], "no matches"),
            ("Cosmo", [], "a name is not an ID field"),
            ("bus-stop", [], "a category is not an ID field"),
            ("-1", [], "a negative number matches no ID"),
            ("99999999999999999999", [], "an out-of-range number matches nothing"),
        ]
        for term, expected, why in cases:
            with self.subTest(query=term, why=why):
                self.assertEqual(self.search(term), expected, why)

    def test_search_is_case_insensitive_for_non_numeric_ids(self):
        """External IDs are opaque strings, so exact means byte-exact."""
        PointOfInterest.objects.create(
            external_id="AbC-42",
            name="Mixed Case",
            category="test",
            latitude=0.0,
            longitude=0.0,
            avg_rating=1.0,
        )
        self.assertEqual(self.search("AbC-42"), ["AbC-42"])
        self.assertEqual(self.search("abc-42"), [])

    def test_a_non_numeric_term_does_not_raise_on_the_integer_key(self):
        """Regression: comparing a word against a BigAutoField must not error."""
        self.assertEqual(self.search("not-a-number"), [])

    def test_category_filter_returns_only_that_category(self):
        queryset = PointOfInterest.objects.filter(category="bus-stop")
        self.assertEqual(
            sorted(queryset.values_list("external_id", flat=True)),
            sorted(["502595764", "4390484395", "8927949261"]),
        )

    def test_list_display_shows_both_identifiers(self):
        self.assertIn("internal_id", self.admin.list_display)
        self.assertIn("external_id", self.admin.list_display)
        self.assertIn("avg_rating", self.admin.list_display)

    def test_records_cannot_be_added_by_hand(self):
        self.assertFalse(self.admin.has_add_permission(self.request))


class PaginationTests(TestCase):
    """Paging must be stable: the model carries a deterministic ordering."""

    @classmethod
    def setUpTestData(cls):
        import_file(fixture("dummy.csv"))

    def test_pages_partition_the_rows_with_no_gaps_or_repeats(self):
        paginator = Paginator(PointOfInterest.objects.all(), 3)
        self.assertEqual(paginator.num_pages, 4)
        seen: list[int] = []
        for number in paginator.page_range:
            page = paginator.page(number)
            seen.extend(page.object_list.values_list("internal_id", flat=True))
        self.assertEqual(seen, list(range(1, 11)))

    def test_paging_does_not_warn_about_an_unordered_queryset(self):
        """The original model had no ordering, so Django warned here."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            list(Paginator(PointOfInterest.objects.all(), 3).page(1).object_list)

    def test_boundary_pages(self):
        paginator = Paginator(PointOfInterest.objects.all(), 4)
        first = list(paginator.page(1).object_list.values_list("internal_id", flat=True))
        last = list(paginator.page(3).object_list.values_list("internal_id", flat=True))
        self.assertEqual(first, [1, 2, 3, 4])
        self.assertEqual(last, [9, 10])
