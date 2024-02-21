"""Test package for the ``poi`` app.

Importing this package installs a process-wide network guard. Nothing in this
project should reach the network during a test: the importer reads local
files, and Celery runs eagerly under ``manage.py test``. If a future change
introduces an outbound call, the suite fails loudly here instead of turning
green only on a machine with connectivity.
"""

from __future__ import annotations

import socket

_REAL_SOCKET = socket.socket


class NetworkAccessDuringTest(RuntimeError):
    """Raised when test code attempts to open a network socket."""


class _BlockedSocket(_REAL_SOCKET):  # type: ignore[misc,valid-type]
    def connect(self, *args, **kwargs):
        raise NetworkAccessDuringTest(
            f"network access is disabled during tests (connect to {args[0]!r})"
        )

    def connect_ex(self, *args, **kwargs):
        raise NetworkAccessDuringTest(
            f"network access is disabled during tests (connect to {args[0]!r})"
        )


socket.socket = _BlockedSocket  # type: ignore[assignment]
