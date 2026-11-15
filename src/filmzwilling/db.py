"""SQLite connection handling and versioned migrations (standard library sqlite3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS: list[tuple[int, str]] = []


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with WAL, foreign keys and Row factory."""
    raise NotImplementedError


def schema_version(conn: sqlite3.Connection) -> int:
    raise NotImplementedError


def migrate(conn: sqlite3.Connection) -> int:
    """Apply all pending migrations; idempotent. Returns the resulting version."""
    raise NotImplementedError


class Database:
    """Thin wrapper that opens short-lived connections (safe across threads)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def initialize(self) -> int:
        raise NotImplementedError

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        raise NotImplementedError
        yield  # pragma: no cover
