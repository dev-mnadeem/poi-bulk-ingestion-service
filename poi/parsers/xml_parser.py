"""XML parser for PoI files."""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator

from .base import (
    ParseError,
    ParseOutcome,
    PoIRecord,
    RecordError,
    SkippedRecord,
    mean_rating,
    require,
    to_float,
)


class XmlParser:
    """Streams PoI records out of an XML document.

    Uses ``iterparse`` and clears each element once it has been read, so peak
    memory stays flat no matter how large the document is. The previous
    implementation called ``ElementTree.parse``, which builds the entire tree
    in memory before the first record is available.
    """

    extensions = (".xml",)

    #: Child tags read from each PoI element.
    TAGS = (
        "pid",
        "pname",
        "pcategory",
        "platitude",
        "plongitude",
        "pratings",
    )

    def parse(self, file_path: str) -> Iterator[ParseOutcome]:
        root: ElementTree.Element | None = None
        depth = 0
        index = 0
        try:
            for event, element in ElementTree.iterparse(file_path, events=("start", "end")):
                if event == "start":
                    if root is None:
                        root = element
                    depth += 1
                    continue

                depth -= 1
                # Only direct children of the document root are PoI records;
                # `end` also fires for every nested field element.
                if depth != 1:
                    continue

                index += 1
                try:
                    yield self._to_record(element)
                except RecordError as exc:
                    yield SkippedRecord(f"<{element.tag}> #{index}", str(exc))
                finally:
                    # Release the element and detach it from the root so the
                    # document does not accumulate in memory as we walk it.
                    element.clear()
                    if root is not None:
                        root.remove(element)
        except ElementTree.ParseError as exc:
            raise ParseError(f"malformed XML: {exc}") from exc

    @classmethod
    def _to_record(cls, element: ElementTree.Element) -> PoIRecord:
        values = {tag: cls._text(element, tag) for tag in cls.TAGS}
        return PoIRecord(
            external_id=require(values["pid"], "pid"),
            name=require(values["pname"], "pname"),
            category=require(values["pcategory"], "pcategory"),
            latitude=to_float(values["platitude"], "platitude"),
            longitude=to_float(values["plongitude"], "plongitude"),
            avg_rating=mean_rating(cls._parse_ratings(values["pratings"])),
        )

    @staticmethod
    def _text(element: ElementTree.Element, tag: str) -> str | None:
        child = element.find(tag)
        return None if child is None else child.text

    @staticmethod
    def _parse_ratings(raw: str | None) -> list[float]:
        """Parse the comma-separated ``<pratings>`` text.

        An absent or empty element means "not yet rated" and yields no values,
        rather than raising.
        """
        if raw is None or not raw.strip():
            return []
        try:
            return [float(part) for part in raw.split(",") if part.strip()]
        except ValueError as exc:
            raise RecordError(f"ratings element holds a non-number: {raw!r}") from exc
