from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from filmzwilling.db import MIGRATIONS, Database, connect, migrate, schema_version

EXPECTED_TABLES = {
    "films",
    "film_offers",
    "providers",
    "ratings",
    "film_status",
    "deferred",
    "actions",
    "watch_events",
    "unmatched",
    "settings",
    "recommendations",
    "twins",
    "tmdb_cache",
    "new_releases",
}


def tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_schema(tmp_path: Path) -> None:
    db = Database(tmp_path / "a.sqlite")
    version = db.initialize()
    assert version == MIGRATIONS[-1][0]
    with db.connection() as conn:
        assert tables(conn) >= EXPECTED_TABLES
        cols = {r[1] for r in conn.execute("PRAGMA table_info(watch_events)")}
        assert {
            "source",
            "profile",
            "raw_title",
            "tmdb_id",
            "movielens_id",
            "first_seen",
            "last_seen",
            "total_watch_seconds",
            "max_position_seconds",
            "sessions",
            "hints",
        } <= cols
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_migrations_are_versioned_and_increasing() -> None:
    versions = [v for v, _ in MIGRATIONS]
    assert versions == sorted(versions)
    assert len(set(versions)) == len(versions)
    assert versions[0] == 1


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    db = Database(tmp_path / "b.sqlite")
    db.initialize()
    with db.connection() as conn:
        conn.execute("INSERT INTO settings(key, value) VALUES ('x', '1')")
    assert db.initialize() == MIGRATIONS[-1][0]
    with db.connection() as conn:
        assert migrate(conn) == MIGRATIONS[-1][0]
        assert conn.execute("SELECT value FROM settings WHERE key='x'").fetchone()[0] == "1"


def test_partial_migration_is_completed(tmp_path: Path) -> None:
    path = tmp_path / "c.sqlite"
    conn = connect(path)
    conn.executescript(MIGRATIONS[0][1])
    conn.execute(f"PRAGMA user_version = {MIGRATIONS[0][0]}")
    conn.commit()
    assert schema_version(conn) == MIGRATIONS[0][0]
    assert migrate(conn) == MIGRATIONS[-1][0]
    assert tables(conn) >= EXPECTED_TABLES
    conn.close()


def test_connection_rolls_back_on_error(tmp_path: Path) -> None:
    db = Database(tmp_path / "d.sqlite")
    db.initialize()
    try:
        with db.connection() as conn:
            conn.execute("INSERT INTO settings(key, value) VALUES ('y', '2')")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM settings WHERE key='y'").fetchone()[0] == 0


def test_creates_parent_directory(tmp_path: Path) -> None:
    db = Database(tmp_path / "nested" / "dir" / "e.sqlite")
    db.initialize()
    assert db.path.exists()


def test_threads_can_use_database(tmp_path: Path) -> None:
    db = Database(tmp_path / "f.sqlite")
    db.initialize()
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            with db.connection() as conn:
                conn.execute("INSERT INTO settings(key, value) VALUES (?, ?)", (f"k{i}", str(i)))
        except BaseException as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 8
