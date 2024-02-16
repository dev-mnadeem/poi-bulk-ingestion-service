"""Django admin configuration for browsing imported PoI data."""

from __future__ import annotations

from django.contrib import admin
from django.db.models import Q, QuerySet
from django.http import HttpRequest

from .models import PointOfInterest


@admin.register(PointOfInterest)
class PointOfInterestAdmin(admin.ModelAdmin):
    """Read-oriented admin for PoI records.

    Search is an **exact** identifier lookup, not a substring match. Django's
    default ``search_fields`` behaviour is ``icontains``, which for an ID field
    is actively wrong: searching for external ID ``1`` would also return
    ``1806848972``, ``813164026`` and every other ID that happens to contain
    the digit. Identifiers are looked up, not fuzzily matched, so
    :meth:`get_search_results` is overridden below.
    """

    #: internal_id is a BigAutoField; anything outside this range cannot be a
    #: primary key and must not reach the database, where SQLite raises
    #: OverflowError and Postgres raises a numeric-out-of-range error.
    _BIGINT_MAX = 2**63 - 1

    list_display = ("internal_id", "external_id", "name", "category", "avg_rating")
    list_filter = ("category",)
    ordering = ("internal_id",)
    list_per_page = 50
    search_help_text = "Exact match on internal ID or external ID."

    # Declared so the admin renders the search box; the actual lookup is
    # performed by get_search_results().
    search_fields = ("external_id",)

    def get_search_results(
        self, request: HttpRequest, queryset: QuerySet, search_term: str
    ) -> tuple[QuerySet, bool]:
        term = search_term.strip()
        if not term:
            return queryset, False

        criteria = Q(external_id__exact=term)
        # internal_id is an integer primary key. Only compare against it when
        # the term is an integer the column could actually hold: otherwise the
        # ORM either raises on the cast or overflows the backend.
        if term.isdigit() and int(term) <= self._BIGINT_MAX:
            criteria |= Q(internal_id=int(term))

        # No duplicates are possible: both branches match at most one row and
        # neither joins across a relation.
        return queryset.filter(criteria), False

    def has_add_permission(self, request: HttpRequest) -> bool:
        """PoI rows arrive through ``manage.py import_poi``, not by hand."""
        return False
