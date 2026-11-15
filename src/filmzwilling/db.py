"""SQLite connection handling and versioned migrations (standard library sqlite3)."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS films (
    id INTEGER PRIMARY KEY,
    tmdb_id INTEGER UNIQUE,
    movielens_id INTEGER UNIQUE,
    ml_title TEXT,
    ml_year INTEGER,
    ml_genres TEXT NOT NULL DEFAULT '[]',
    ml_count INTEGER,
    ml_mean REAL,
    popularity_rank INTEGER,
    title TEXT,
    original_title TEXT,
    year INTEGER,
    runtime INTEGER,
    genres TEXT NOT NULL DEFAULT '[]',
    poster_path TEXT,
    vote_average REAL,
    vote_count INTEGER,
    release_date TEXT,
    popularity REAL,
    meta_fetched_at TEXT,
    providers_fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS providers (
    provider_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    logo_path TEXT,
    display_priority INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS film_offers (
    film_id INTEGER NOT NULL REFERENCES films(id) ON DELETE CASCADE,
    provider_id INTEGER NOT NULL,
    provider_name TEXT NOT NULL,
    logo_path TEXT,
    category TEXT NOT NULL,
    display_priority INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (film_id, provider_id, category)
);

CREATE TABLE IF NOT EXISTS ratings (
    film_id INTEGER PRIMARY KEY REFERENCES films(id) ON DELETE CASCADE,
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 10),
    rated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS film_status (
    film_id INTEGER PRIMARY KEY REFERENCES films(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('not_seen', 'not_interested')),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deferred (
    film_id INTEGER PRIMARY KEY REFERENCES films(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    film_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    prev TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watch_events (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    profile TEXT NOT NULL,
    raw_title TEXT NOT NULL,
    tmdb_id INTEGER,
    movielens_id INTEGER,
    first_seen TEXT,
    last_seen TEXT,
    total_watch_seconds INTEGER,
    max_position_seconds INTEGER,
    sessions INTEGER NOT NULL DEFAULT 0,
    hints TEXT NOT NULL DEFAULT '{}',
    year INTEGER,
    kind TEXT NOT NULL DEFAULT 'movie',
    match_status TEXT NOT NULL DEFAULT 'pending',
    UNIQUE (source, profile, raw_title)
);

CREATE TABLE IF NOT EXISTS unmatched (
    id INTEGER PRIMARY KEY,
    raw_title TEXT NOT NULL UNIQUE,
    year INTEGER,
    source TEXT NOT NULL,
    best_score REAL,
    best_title TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    resolved_tmdb_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tmdb_cache (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
"""

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS recommendations (
    movielens_id INTEGER PRIMARY KEY,
    film_id INTEGER,
    score REAL NOT NULL,
    support INTEGER NOT NULL,
    twin_mean REAL NOT NULL,
    rank INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS twins (
    rank INTEGER PRIMARY KEY,
    ml_user_id INTEGER NOT NULL,
    similarity REAL NOT NULL,
    overlap INTEGER NOT NULL,
    top_movies TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS new_releases (
    film_id INTEGER PRIMARY KEY REFERENCES films(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_films_popularity ON films(popularity_rank);
CREATE INDEX IF NOT EXISTS idx_events_tmdb ON watch_events(tmdb_id);
CREATE INDEX IF NOT EXISTS idx_events_title ON watch_events(raw_title);
CREATE INDEX IF NOT EXISTS idx_recommendations_rank ON recommendations(rank);
CREATE INDEX IF NOT EXISTS idx_offers_film ON film_offers(film_id);
"""

MIGRATIONS: list[tuple[int, str]] = [(1, SCHEMA_V1), (2, SCHEMA_V2)]


def _py_lower(value: object) -> str | None:
    return None if value is None else str(value).lower()


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with WAL, foreign keys and Row factory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.create_function("py_lower", 1, _py_lower, deterministic=True)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply all pending migrations; idempotent. Returns the resulting version."""
    current = schema_version(conn)
    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        conn.executescript(sql)
        conn.execute(f"PRAGMA user_version = {int(version)}")
        conn.commit()
        current = version
    return current


class Database:
    """Thin wrapper that opens short-lived connections (safe across threads)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._initialized = False
        self._lock = threading.Lock()

    def initialize(self) -> int:
        with self._lock:
            conn = connect(self.path)
            try:
                version = migrate(conn)
            finally:
                conn.close()
            self._initialized = True
            return version

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        if not self._initialized:
            self.initialize()
        conn = connect(self.path)
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
