"""Shared helpers for the ``poi`` test suite."""

from __future__ import annotations

from pathlib import Path

#: Directory holding the committed sample files. The tests read these real
#: files rather than mocking the parsers' I/O, so a change in parsing
#: behaviour is actually caught.
FIXTURES = Path(__file__).resolve().parent.parent / "test_files"


def fixture(name: str) -> str:
    """Return the absolute path to a committed fixture file."""
    path = FIXTURES / name
    if not path.exists():
        raise FileNotFoundError(f"missing test fixture: {path}")
    return str(path)
