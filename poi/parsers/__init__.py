"""Registry of file-format parsers.

Adding a format is the one extension this project was most likely to need, so
it is a single, explicit seam: write a class satisfying
:class:`~poi.parsers.base.Parser` and register it here (or call
:func:`register` from your own code). Nothing in the importer, the management
command or the Celery tasks needs to change.

    >>> from poi.parsers import register, get_parser
    >>> register(MyGeoJsonParser())        # doctest: +SKIP
    >>> get_parser("places.geojson")       # doctest: +SKIP
"""

from __future__ import annotations

import os
from collections.abc import Iterable

from .base import ParseError, ParseOutcome, Parser, PoIRecord, SkippedRecord
from .csv_parser import CsvParser
from .json_parser import JsonParser
from .xml_parser import XmlParser

__all__ = [
    "ParseError",
    "ParseOutcome",
    "Parser",
    "PoIRecord",
    "SkippedRecord",
    "UnsupportedFormat",
    "get_parser",
    "register",
    "supported_extensions",
]


class UnsupportedFormat(ValueError):
    """Raised when no registered parser claims a file's extension."""


_REGISTRY: dict[str, Parser] = {}


def register(parser: Parser) -> Parser:
    """Register ``parser`` for each extension it claims.

    Re-registering an extension replaces the previous parser, which lets a
    deployment override a built-in format without editing this module.
    """
    for extension in parser.extensions:
        _REGISTRY[extension.lower()] = parser
    return parser


def get_parser(file_path: str) -> Parser:
    """Return the parser registered for ``file_path``'s extension."""
    extension = os.path.splitext(file_path)[1].lower()
    try:
        return _REGISTRY[extension]
    except KeyError:
        raise UnsupportedFormat(
            f"no parser registered for {extension or 'files without an extension'!r}; "
            f"supported: {', '.join(supported_extensions())}"
        ) from None


def supported_extensions() -> Iterable[str]:
    """Return the sorted extensions that currently have a parser."""
    return sorted(_REGISTRY)


register(CsvParser())
register(JsonParser())
register(XmlParser())
