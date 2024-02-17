"""Database model for a Point of Interest (PoI)."""

from django.db import models


class PointOfInterest(models.Model):
    """A single point of interest imported from an upstream data file.

    Two identifiers are deliberately kept apart:

    ``internal_id``
        This service's own surrogate key. It is assigned by the database and
        has no meaning outside this system.
    ``external_id``
        The identifier the record carried in the source file (``poi_id`` in
        CSV, ``id`` in JSON, ``pid`` in XML). It is the stable handle used to
        recognise a record on re-import, so it is unique and indexed.

    ``avg_rating`` stores the mean of the per-visit ratings found in the
    source file; the individual ratings are not retained.
    """

    internal_id = models.BigAutoField(primary_key=True)
    external_id = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100, db_index=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    avg_rating = models.FloatField()

    class Meta:
        verbose_name = "point of interest"
        verbose_name_plural = "points of interest"
        # A deterministic default ordering. Without one, LIMIT/OFFSET paging
        # over this table is not stable and rows can repeat or vanish between
        # pages (Django raises UnorderedObjectListWarning).
        ordering = ("internal_id",)
        indexes = [
            models.Index(fields=("category", "internal_id"), name="poi_category_id_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.external_id})"
