"""Repository layer over the SQLite app database."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from filmzwilling.db import Database
from filmzwilling.genres import german_genres
from filmzwilling.movielens import clean_ml_title
from filmzwilling.scale import validate_note
from filmzwilling.tmdb import Provider

ACTION_RATE = "rate"
ACTION_NOT_SEEN = "not_seen"
ACTION_LATER = "later"
STATUS_NOT_SEEN = "not_seen"
STATUS_NOT_INTERESTED = "not_interested"
DEFAULT_QUEUE_SIZE = 1000
MAX_QUEUE_SIZE = 100_000

FILM_COLUMNS = (
    "id, tmdb_id, movielens_id, ml_title, ml_year, ml_genres, ml_count, ml_mean, popularity_rank, "
    "title, original_title, year, runtime, genres, poster_path, vote_average, vote_count, "
    "release_date, popularity, meta_fetched_at, providers_fetched_at"
)


@dataclass
class Film:
    id: int
    tmdb_id: int | None = None
    movielens_id: int | None = None
    ml_title: str | None = None
    ml_year: int | None = None
    ml_genres: list[str] = field(default_factory=list)
    ml_count: int | None = None
    ml_mean: float | None = None
    popularity_rank: int | None = None
    title: str | None = None
    original_title: str | None = None
    year: int | None = None
    runtime: int | None = None
    genres: list[str] = field(default_factory=list)
    poster_path: str | None = None
    vote_average: float | None = None
    vote_count: int | None = None
    release_date: str | None = None
    popularity: float | None = None
    meta_fetched_at: str | None = None
    providers_fetched_at: str | None = None

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.ml_title:
            return clean_ml_title(self.ml_title)
        return f"Film {self.id}"

    @property
    def display_year(self) -> int | None:
        return self.year if self.year is not None else self.ml_year

    @property
    def display_genres(self) -> list[str]:
        """German genres from TMDB, else MovieLens genres mapped to German."""
        if self.genres:
            return list(self.genres)
        return german_genres(self.ml_genres)


@dataclass(frozen=True)
class MovieLensFilm:
    movielens_id: int
    tmdb_id: int | None
    title: str
    year: int | None
    genres: list[str]
    count: int
    mean: float | None
    popularity_rank: int


@dataclass(frozen=True)
class Offer:
    provider_id: int
    provider_name: str
    logo_path: str | None
    category: str
    display_priority: int = 0


@dataclass(frozen=True)
class UserSettings:
    my_profiles: list[str]
    my_providers: list[int] | None
    queue_size: int = DEFAULT_QUEUE_SIZE


@dataclass(frozen=True)
class StoredEvent:
    id: int
    source: str
    profile: str
    raw_title: str
    tmdb_id: int | None
    movielens_id: int | None
    first_seen: str | None
    last_seen: str | None
    total_watch_seconds: int | None
    max_position_seconds: int | None
    sessions: int
    hints: dict[str, Any]
    year: int | None
    kind: str


@dataclass(frozen=True)
class UnmatchedTitle:
    id: int
    raw_title: str
    year: int | None
    source: str
    best_score: float | None
    best_title: str | None
    status: str
    profiles: list[str]


@dataclass(frozen=True)
class StoredRecommendation:
    movielens_id: int
    film_id: int | None
    score: float
    support: int
    twin_mean: float
    rank: int


@dataclass(frozen=True)
class StoredTwin:
    rank: int
    ml_user_id: int
    similarity: float
    overlap: int
    top_movies: list[dict[str, Any]]


def utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(sep=" ", timespec="seconds")


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _film(row: sqlite3.Row) -> Film:
    return Film(
        id=row["id"],
        tmdb_id=row["tmdb_id"],
        movielens_id=row["movielens_id"],
        ml_title=row["ml_title"],
        ml_year=row["ml_year"],
        ml_genres=json.loads(row["ml_genres"] or "[]"),
        ml_count=row["ml_count"],
        ml_mean=row["ml_mean"],
        popularity_rank=row["popularity_rank"],
        title=row["title"],
        original_title=row["original_title"],
        year=row["year"],
        runtime=row["runtime"],
        genres=json.loads(row["genres"] or "[]"),
        poster_path=row["poster_path"],
        vote_average=row["vote_average"],
        vote_count=row["vote_count"],
        release_date=row["release_date"],
        popularity=row["popularity"],
        meta_fetched_at=row["meta_fetched_at"],
        providers_fetched_at=row["providers_fetched_at"],
    )


def _event(row: sqlite3.Row) -> StoredEvent:
    return StoredEvent(
        id=row["id"],
        source=row["source"],
        profile=row["profile"],
        raw_title=row["raw_title"],
        tmdb_id=row["tmdb_id"],
        movielens_id=row["movielens_id"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        total_watch_seconds=row["total_watch_seconds"],
        max_position_seconds=row["max_position_seconds"],
        sessions=row["sessions"],
        hints=json.loads(row["hints"] or "{}"),
        year=row["year"],
        kind=row["kind"],
    )


def _chunks(values: Sequence[int], size: int = 900) -> Iterable[Sequence[int]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


class Repository:
    def __init__(self, db: Database, clock: Callable[[], datetime] = utcnow) -> None:
        self.db = db
        self.clock = clock

    def _now(self) -> str:
        return _iso(self.clock()) or ""

    # --- settings -------------------------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.db.connection() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return default if row is None else json.loads(row["value"])

    def set_setting(self, key: str, value: Any) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    def get_user_settings(self) -> UserSettings:
        return UserSettings(
            my_profiles=list(self.get_setting("my_profiles", [])),
            my_providers=self.get_setting("my_providers", None),
            queue_size=int(self.get_setting("queue_size", DEFAULT_QUEUE_SIZE)),
        )

    def update_user_settings(
        self,
        *,
        my_profiles: list[str] | None = None,
        my_providers: list[int] | None = None,
        queue_size: int | None = None,
    ) -> UserSettings:
        if queue_size is not None and not 0 <= int(queue_size) <= MAX_QUEUE_SIZE:
            raise ValueError(f"Größe der Warteschlange muss zwischen 0 und {MAX_QUEUE_SIZE} liegen")
        if my_profiles is not None:
            self.set_setting("my_profiles", list(my_profiles))
        if my_providers is not None:
            self.set_setting("my_providers", [int(p) for p in my_providers])
        if queue_size is not None:
            self.set_setting("queue_size", int(queue_size))
        return self.get_user_settings()

    # --- films ----------------------------------------------------------------------------
    def upsert_movielens_films(self, films: Iterable[MovieLensFilm]) -> int:
        items = list(films)
        with self.db.connection() as conn:
            by_ml = {
                r[0]: r[1]
                for r in conn.execute(
                    "SELECT movielens_id, id FROM films WHERE movielens_id IS NOT NULL"
                )
            }
            by_tmdb = {
                r[0]: (r[1], r[2])
                for r in conn.execute(
                    "SELECT tmdb_id, id, movielens_id FROM films WHERE tmdb_id IS NOT NULL"
                )
            }
            updates: list[tuple[Any, ...]] = []
            inserts: list[tuple[Any, ...]] = []
            for f in items:
                ml_fields = (
                    f.title,
                    f.year,
                    json.dumps(list(f.genres), ensure_ascii=False),
                    int(f.count),
                    None if f.mean is None else float(f.mean),
                    int(f.popularity_rank),
                )
                tmdb = int(f.tmdb_id) if f.tmdb_id is not None else None
                if f.movielens_id in by_ml:
                    film_id = by_ml[f.movielens_id]
                    owner = by_tmdb.get(tmdb) if tmdb is not None else None
                    tmdb_ok = tmdb if owner is None or owner[0] == film_id else None
                    updates.append((*ml_fields, f.movielens_id, tmdb_ok, film_id))
                elif tmdb is not None and tmdb in by_tmdb and by_tmdb[tmdb][1] is None:
                    film_id = by_tmdb[tmdb][0]
                    updates.append((*ml_fields, f.movielens_id, tmdb, film_id))
                    by_tmdb[tmdb] = (film_id, f.movielens_id)
                    by_ml[f.movielens_id] = film_id
                else:
                    tmdb_ok = tmdb if tmdb is not None and tmdb not in by_tmdb else None
                    inserts.append((f.movielens_id, tmdb_ok, *ml_fields))
                    if tmdb_ok is not None:
                        by_tmdb[tmdb_ok] = (-1, f.movielens_id)
            conn.executemany(
                "UPDATE films SET ml_title = ?, ml_year = ?, ml_genres = ?, ml_count = ?, "
                "ml_mean = ?, "
                "popularity_rank = ?, movielens_id = ?, tmdb_id = COALESCE(tmdb_id, ?) WHERE id "
                "= ?",
                updates,
            )
            conn.executemany(
                "INSERT INTO films (movielens_id, tmdb_id, ml_title, ml_year, ml_genres, ml_count, "
                "ml_mean, popularity_rank) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                inserts,
            )
        return len(items)

    def upsert_tmdb_details(self, details: Any, fetched_at: datetime | None = None) -> int:
        """Store TMDB metadata (a `tmdb.MovieDetails`); returns the film id."""
        fetched = _iso(fetched_at) if fetched_at is not None else self._now()
        values = (
            details.title,
            details.original_title,
            details.year,
            details.runtime,
            json.dumps(list(details.genres), ensure_ascii=False),
            details.poster_path,
            details.vote_average,
            details.vote_count,
            details.release_date,
            details.popularity,
            fetched,
        )
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT id FROM films WHERE tmdb_id = ?", (details.tmdb_id,)
            ).fetchone()
            if row is None:
                cur = conn.execute(
                    "INSERT INTO films (title, original_title, year, runtime, genres, poster_path, "
                    "vote_average, vote_count, release_date, popularity, meta_fetched_at, tmdb_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (*values, details.tmdb_id),
                )
                return int(cur.lastrowid or 0)
            conn.execute(
                "UPDATE films SET title = ?, original_title = ?, year = ?, runtime = ?, genres "
                "= ?, "
                "poster_path = ?, vote_average = ?, vote_count = ?, release_date = ?, "
                "popularity = ?, meta_fetched_at = ? WHERE id = ?",
                (*values, row["id"]),
            )
            return int(row["id"])

    def set_film_offers(
        self, film_id: int, offers: Sequence[Any], fetched_at: datetime | None = None
    ) -> None:
        fetched = _iso(fetched_at) if fetched_at is not None else self._now()
        with self.db.connection() as conn:
            conn.execute("DELETE FROM film_offers WHERE film_id = ?", (film_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO film_offers (film_id, provider_id, provider_name, "
                "logo_path, "
                "category, display_priority) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        film_id,
                        o.provider_id,
                        o.provider_name,
                        o.logo_path,
                        o.category,
                        o.display_priority,
                    )
                    for o in offers
                ],
            )
            conn.execute(
                "UPDATE films SET providers_fetched_at = ? WHERE id = ?", (fetched, film_id)
            )

    def ensure_film(self, tmdb_id: int, title: str | None = None, year: int | None = None) -> int:
        with self.db.connection() as conn:
            row = conn.execute("SELECT id FROM films WHERE tmdb_id = ?", (tmdb_id,)).fetchone()
            if row is not None:
                return int(row["id"])
            cur = conn.execute(
                "INSERT INTO films (tmdb_id, title, year) VALUES (?, ?, ?)", (tmdb_id, title, year)
            )
            return int(cur.lastrowid or 0)

    def get_film(self, film_id: int) -> Film | None:
        with self.db.connection() as conn:
            row = conn.execute(
                f"SELECT {FILM_COLUMNS} FROM films WHERE id = ?", (film_id,)
            ).fetchone()
        return None if row is None else _film(row)

    def get_films(self, film_ids: Iterable[int]) -> dict[int, Film]:
        ids = list(dict.fromkeys(int(i) for i in film_ids))
        result: dict[int, Film] = {}
        with self.db.connection() as conn:
            for chunk in _chunks(ids):
                marks = ",".join("?" * len(chunk))
                for row in conn.execute(
                    f"SELECT {FILM_COLUMNS} FROM films WHERE id IN ({marks})", chunk
                ):
                    result[row["id"]] = _film(row)
        return result

    def film_id_for_tmdb(self, tmdb_id: int) -> int | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT id FROM films WHERE tmdb_id = ?", (tmdb_id,)).fetchone()
        return None if row is None else int(row["id"])

    def film_ids_for_tmdb(self, tmdb_ids: Iterable[int]) -> dict[int, int]:
        """tmdb_id -> film_id for the given TMDB ids (unknown ids are left out)."""
        ids = list(dict.fromkeys(int(i) for i in tmdb_ids))
        result: dict[int, int] = {}
        with self.db.connection() as conn:
            for chunk in _chunks(ids):
                marks = ",".join("?" * len(chunk))
                for row in conn.execute(
                    f"SELECT tmdb_id, id FROM films WHERE tmdb_id IN ({marks})", chunk
                ):
                    result[int(row[0])] = int(row[1])
        return result

    def film_id_for_movielens(self, movielens_id: int) -> int | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT id FROM films WHERE movielens_id = ?", (int(movielens_id),)
            ).fetchone()
        return None if row is None else int(row["id"])

    def movielens_film_map(self) -> dict[int, int]:
        """movielens_id -> film_id for all films."""
        with self.db.connection() as conn:
            rows = conn.execute("SELECT movielens_id, id FROM films WHERE movielens_id IS NOT NULL")
            return {int(r[0]): int(r[1]) for r in rows}

    def film_offers(self, film_ids: Iterable[int]) -> dict[int, list[Offer]]:
        ids = list(dict.fromkeys(int(i) for i in film_ids))
        result: dict[int, list[Offer]] = {}
        with self.db.connection() as conn:
            for chunk in _chunks(ids):
                marks = ",".join("?" * len(chunk))
                rows = conn.execute(
                    "SELECT film_id, provider_id, provider_name, logo_path, category, "
                    "display_priority "
                    f"FROM film_offers WHERE film_id IN ({marks}) "
                    "ORDER BY display_priority, provider_name",
                    chunk,
                )
                for r in rows:
                    result.setdefault(r["film_id"], []).append(
                        Offer(
                            r["provider_id"],
                            r["provider_name"],
                            r["logo_path"],
                            r["category"],
                            r["display_priority"],
                        )
                    )
        return result

    def all_offers(self) -> dict[int, list[Offer]]:
        result: dict[int, list[Offer]] = {}
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT film_id, provider_id, provider_name, logo_path, category, display_priority "
                "FROM film_offers ORDER BY display_priority, provider_name"
            )
            for r in rows:
                result.setdefault(r["film_id"], []).append(
                    Offer(
                        r["provider_id"],
                        r["provider_name"],
                        r["logo_path"],
                        r["category"],
                        r["display_priority"],
                    )
                )
        return result

    def _stale(self, film_ids: Iterable[int], column: str, max_age_days: int) -> list[int]:
        ids = list(dict.fromkeys(int(i) for i in film_ids))
        cutoff = _iso(self.clock() - timedelta(days=max_age_days))
        stale: set[int] = set()
        with self.db.connection() as conn:
            for chunk in _chunks(ids):
                marks = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT id FROM films WHERE id IN ({marks}) AND tmdb_id IS NOT NULL "
                    f"AND ({column} IS NULL OR {column} < ?)",
                    (*chunk, cutoff),
                )
                stale.update(int(r[0]) for r in rows)
        return [i for i in ids if i in stale]

    def films_missing_metadata(self, film_ids: Iterable[int], max_age_days: int = 30) -> list[int]:
        return self._stale(film_ids, "meta_fetched_at", max_age_days)

    def films_missing_offers(self, film_ids: Iterable[int], max_age_days: int = 7) -> list[int]:
        return self._stale(film_ids, "providers_fetched_at", max_age_days)

    def popular_film_ids(self, limit: int) -> list[int]:
        """Films with movielens_id and tmdb_id ordered by popularity rank."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM films WHERE movielens_id IS NOT NULL AND tmdb_id IS NOT NULL "
                "ORDER BY popularity_rank, id LIMIT ?",
                (int(limit),),
            )
            return [int(r[0]) for r in rows]

    def search_films(self, query: str, limit: int = 20) -> list[Film]:
        pattern = f"%{query.strip().lower()}%"
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT {FILM_COLUMNS} FROM films WHERE py_lower(title) LIKE ? "
                "OR py_lower(original_title) LIKE ? OR py_lower(ml_title) LIKE ? "
                "ORDER BY popularity_rank IS NULL, popularity_rank, id LIMIT ?",
                (pattern, pattern, pattern, int(limit)),
            ).fetchall()
        return [_film(r) for r in rows]

    def count_films(self) -> int:
        with self.db.connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM films").fetchone()[0])

    def genres(self) -> list[str]:
        names: set[str] = set()
        with self.db.connection() as conn:
            for row in conn.execute("SELECT genres, ml_genres FROM films"):
                tmdb = json.loads(row["genres"] or "[]")
                names.update(tmdb or german_genres(json.loads(row["ml_genres"] or "[]")))
        return sorted(n for n in names if n)

    # --- providers ------------------------------------------------------------------------
    def upsert_providers(self, providers: Sequence[Any]) -> None:
        with self.db.connection() as conn:
            conn.executemany(
                "INSERT INTO providers (provider_id, name, logo_path, display_priority) VALUES "
                "(?, ?, ?, ?) "
                "ON CONFLICT(provider_id) DO UPDATE SET name = excluded.name, "
                "logo_path = excluded.logo_path, display_priority = excluded.display_priority",
                [(p.provider_id, p.name, p.logo_path, p.display_priority) for p in providers],
            )

    def list_providers(self) -> list[Provider]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT provider_id, name, logo_path, display_priority FROM providers "
                "ORDER BY display_priority, name"
            )
            return [Provider(r[0], r[1], r[2], r[3]) for r in rows]

    # --- ratings and statuses -------------------------------------------------------------
    def _require_film(self, conn: sqlite3.Connection, film_id: int) -> None:
        if conn.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
            raise KeyError(f"Film {film_id} nicht gefunden")

    def _state(self, conn: sqlite3.Connection, film_id: int) -> dict[str, Any]:
        rating = conn.execute(
            "SELECT score, rated_at FROM ratings WHERE film_id = ?", (film_id,)
        ).fetchone()
        status = conn.execute(
            "SELECT status FROM film_status WHERE film_id = ?", (film_id,)
        ).fetchone()
        deferred = conn.execute("SELECT seq FROM deferred WHERE film_id = ?", (film_id,)).fetchone()
        return {
            "score": None if rating is None else rating["score"],
            "rated_at": None if rating is None else rating["rated_at"],
            "status": None if status is None else status["status"],
            "deferred": None if deferred is None else deferred["seq"],
        }

    def _log(self, conn: sqlite3.Connection, film_id: int, action: str) -> None:
        conn.execute(
            "INSERT INTO actions (film_id, action, prev, created_at) VALUES (?, ?, ?, ?)",
            (film_id, action, json.dumps(self._state(conn, film_id)), self._now()),
        )

    def set_rating(self, film_id: int, score: int, *, log_action: bool = True) -> None:
        note = validate_note(score)
        with self.db.connection() as conn:
            self._require_film(conn, film_id)
            if log_action:
                self._log(conn, film_id, ACTION_RATE)
            conn.execute(
                "INSERT INTO ratings (film_id, score, rated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(film_id) DO UPDATE SET score = excluded.score, rated_at = "
                "excluded.rated_at",
                (film_id, note, self._now()),
            )
            conn.execute("DELETE FROM film_status WHERE film_id = ?", (film_id,))

    def delete_rating(self, film_id: int) -> bool:
        with self.db.connection() as conn:
            cur = conn.execute("DELETE FROM ratings WHERE film_id = ?", (film_id,))
            return cur.rowcount > 0

    def get_rating(self, film_id: int) -> int | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT score FROM ratings WHERE film_id = ?", (film_id,)).fetchone()
        return None if row is None else int(row["score"])

    def list_ratings(self, query: str | None = None) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            columns = ", ".join("f." + c.strip() for c in FILM_COLUMNS.split(","))
            rows = conn.execute(
                f"SELECT r.score, r.rated_at, {columns} "
                "FROM ratings r JOIN films f ON f.id = r.film_id ORDER BY r.rated_at DESC, "
                "r.film_id DESC"
            ).fetchall()
        needle = (query or "").strip().lower()
        result: list[dict[str, Any]] = []
        for row in rows:
            film = _film(row)
            haystack = " ".join(
                x for x in (film.display_title, film.original_title or "", film.ml_title or "") if x
            ).lower()
            if needle and needle not in haystack:
                continue
            result.append(
                {
                    "film_id": film.id,
                    "tmdb_id": film.tmdb_id,
                    "movielens_id": film.movielens_id,
                    "title": film.display_title,
                    "original_title": film.original_title,
                    "year": film.display_year,
                    "score": int(row["score"]),
                    "rated_at": row["rated_at"],
                    "poster_path": film.poster_path,
                }
            )
        return result

    def count_ratings(self) -> int:
        with self.db.connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM ratings").fetchone()[0])

    def ratings_for_cf(self) -> dict[int, int]:
        """{movielens_id: note} for all rated films with a MovieLens id."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT f.movielens_id, r.score FROM ratings r JOIN films f ON f.id = r.film_id "
                "WHERE f.movielens_id IS NOT NULL"
            )
            return {int(r[0]): int(r[1]) for r in rows}

    def _set_status(self, film_id: int, status: str, log_action: str | None) -> None:
        with self.db.connection() as conn:
            self._require_film(conn, film_id)
            if log_action:
                self._log(conn, film_id, log_action)
            conn.execute(
                "INSERT INTO film_status (film_id, status, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(film_id) DO UPDATE SET status = excluded.status, updated_at = "
                "excluded.updated_at",
                (film_id, status, self._now()),
            )

    def mark_not_seen(self, film_id: int, *, log_action: bool = True) -> None:
        self._set_status(film_id, STATUS_NOT_SEEN, ACTION_NOT_SEEN if log_action else None)

    def mark_not_interested(self, film_id: int) -> None:
        self._set_status(film_id, STATUS_NOT_INTERESTED, None)

    def defer(self, film_id: int, *, log_action: bool = True) -> None:
        with self.db.connection() as conn:
            self._require_film(conn, film_id)
            if log_action:
                self._log(conn, film_id, ACTION_LATER)
            seq = int(conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM deferred").fetchone()[0])
            conn.execute(
                "INSERT INTO deferred (film_id, seq) VALUES (?, ?) "
                "ON CONFLICT(film_id) DO UPDATE SET seq = excluded.seq",
                (film_id, seq),
            )

    def undo_last(self) -> dict[str, Any] | None:
        """Revert the most recent queue action; returns {"action", "film_id"} or None."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT id, film_id, action, prev FROM actions ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            film_id = int(row["film_id"])
            prev = json.loads(row["prev"])
            if prev.get("score") is None:
                conn.execute("DELETE FROM ratings WHERE film_id = ?", (film_id,))
            else:
                conn.execute(
                    "INSERT INTO ratings (film_id, score, rated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(film_id) DO UPDATE SET score = excluded.score, rated_at = "
                    "excluded.rated_at",
                    (film_id, prev["score"], prev.get("rated_at") or self._now()),
                )
            if prev.get("status") is None:
                conn.execute("DELETE FROM film_status WHERE film_id = ?", (film_id,))
            else:
                conn.execute(
                    "INSERT INTO film_status (film_id, status, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(film_id) DO UPDATE SET status = excluded.status",
                    (film_id, prev["status"], self._now()),
                )
            if prev.get("deferred") is None:
                conn.execute("DELETE FROM deferred WHERE film_id = ?", (film_id,))
            else:
                conn.execute(
                    "INSERT INTO deferred (film_id, seq) VALUES (?, ?) "
                    "ON CONFLICT(film_id) DO UPDATE SET seq = excluded.seq",
                    (film_id, prev["deferred"]),
                )
            conn.execute("DELETE FROM actions WHERE id = ?", (row["id"],))
            return {"action": row["action"], "film_id": film_id}

    def statuses(self) -> dict[int, str]:
        with self.db.connection() as conn:
            return {
                int(r[0]): str(r[1])
                for r in conn.execute("SELECT film_id, status FROM film_status")
            }

    def rated_film_ids(self) -> set[int]:
        with self.db.connection() as conn:
            return {int(r[0]) for r in conn.execute("SELECT film_id FROM ratings")}

    def deferred_order(self) -> dict[int, int]:
        """film_id -> defer sequence number (higher = deferred later)."""
        with self.db.connection() as conn:
            return {int(r[0]): int(r[1]) for r in conn.execute("SELECT film_id, seq FROM deferred")}

    def count_status(self, status: str) -> int:
        with self.db.connection() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM film_status WHERE status = ?", (status,)
                ).fetchone()[0]
            )

    # --- watch events and matching --------------------------------------------------------
    def upsert_watch_event(self, event: Any) -> str:
        """Insert or update by (source, profile, raw_title). Returns inserted/updated/unchanged."""
        values = {
            "first_seen": _iso(event.first_seen),
            "last_seen": _iso(event.last_seen),
            "total_watch_seconds": event.total_watch_seconds,
            "max_position_seconds": event.max_position_seconds,
            "sessions": int(event.sessions),
            "year": event.year,
            "kind": event.kind,
        }
        key = (event.source, event.profile, event.raw_title)
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM watch_events WHERE source = ? AND profile = ? AND raw_title = ?", key
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO watch_events (source, profile, raw_title, tmdb_id, movielens_id, "
                    "first_seen, last_seen, total_watch_seconds, max_position_seconds, "
                    "sessions, hints, "
                    "year, kind, match_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        *key,
                        event.tmdb_id,
                        event.movielens_id,
                        values["first_seen"],
                        values["last_seen"],
                        values["total_watch_seconds"],
                        values["max_position_seconds"],
                        values["sessions"],
                        json.dumps(event.hints, ensure_ascii=False),
                        values["year"],
                        values["kind"],
                        "matched" if event.tmdb_id else "pending",
                    ),
                )
                return "inserted"
            hints = json.loads(row["hints"] or "{}")
            merged = {**hints, **event.hints}
            changed = any(row[k] != v for k, v in values.items()) or merged != hints
            if not changed:
                return "unchanged"
            conn.execute(
                "UPDATE watch_events SET first_seen = ?, last_seen = ?, total_watch_seconds = ?, "
                "max_position_seconds = ?, sessions = ?, year = ?, kind = ?, hints = ?, "
                "tmdb_id = COALESCE(tmdb_id, ?), movielens_id = COALESCE(movielens_id, ?) WHERE "
                "id = ?",
                (
                    values["first_seen"],
                    values["last_seen"],
                    values["total_watch_seconds"],
                    values["max_position_seconds"],
                    values["sessions"],
                    values["year"],
                    values["kind"],
                    json.dumps(merged, ensure_ascii=False),
                    event.tmdb_id,
                    event.movielens_id,
                    row["id"],
                ),
            )
            return "updated"

    def merge_event_hints(
        self, source: str, profile: str, raw_title: str, hints: dict[str, Any]
    ) -> bool:
        """Merge hints into an event; creates a hint-only event if needed (returns True then)."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT id, hints FROM watch_events WHERE source = ? AND profile = ? AND "
                "raw_title = ?",
                (source, profile, raw_title),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO watch_events (source, profile, raw_title, sessions, hints) "
                    "VALUES (?, ?, ?, 0, ?)",
                    (source, profile, raw_title, json.dumps(hints, ensure_ascii=False)),
                )
                return True
            merged = {**json.loads(row["hints"] or "{}"), **hints}
            conn.execute(
                "UPDATE watch_events SET hints = ? WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), row["id"]),
            )
            return False

    def list_watch_events(self) -> list[StoredEvent]:
        with self.db.connection() as conn:
            return [_event(r) for r in conn.execute("SELECT * FROM watch_events ORDER BY id")]

    def events_with_films(self) -> list[StoredEvent]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM watch_events WHERE tmdb_id IS NOT NULL ORDER BY id")
            return [_event(r) for r in rows]

    def count_watch_events(self) -> int:
        with self.db.connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM watch_events").fetchone()[0])

    def profiles(self) -> list[str]:
        with self.db.connection() as conn:
            return sorted(
                {str(r[0]) for r in conn.execute("SELECT DISTINCT profile FROM watch_events")}
            )

    def pending_titles(self) -> list[dict[str, Any]]:
        """Distinct raw titles without tmdb_id that are not ignored/unmatched."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT raw_title, MAX(year) AS year, MIN(source) AS source, MAX(last_seen) AS "
                "last_seen, "
                "MIN(CASE WHEN kind = 'movie' THEN 0 ELSE 1 END) AS ambiguous "
                "FROM watch_events WHERE tmdb_id IS NULL AND match_status = 'pending' "
                "GROUP BY raw_title ORDER BY MIN(id)"
            ).fetchall()
        return [
            {
                "raw_title": r["raw_title"],
                "year": r["year"],
                "source": r["source"],
                "last_seen": r["last_seen"],
                "kind": "ambiguous" if r["ambiguous"] else "movie",
            }
            for r in rows
        ]

    def assign_title(self, raw_title: str, tmdb_id: int) -> int:
        """Attach a TMDB id (and MovieLens id if known) to all events with this raw title."""
        film_id = self.ensure_film(tmdb_id)
        with self.db.connection() as conn:
            ml = conn.execute("SELECT movielens_id FROM films WHERE id = ?", (film_id,)).fetchone()[
                0
            ]
            cur = conn.execute(
                "UPDATE watch_events SET tmdb_id = ?, movielens_id = ?, match_status = 'matched' "
                "WHERE raw_title = ?",
                (tmdb_id, ml, raw_title),
            )
            return cur.rowcount

    def mark_title_series(self, raw_title: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE watch_events SET match_status = 'series' WHERE raw_title = ?", (raw_title,)
            )

    def relink_movielens_ids(self) -> int:
        with self.db.connection() as conn:
            cur = conn.execute(
                "UPDATE watch_events SET movielens_id = (SELECT f.movielens_id FROM films f "
                "WHERE f.tmdb_id = watch_events.tmdb_id) WHERE tmdb_id IS NOT NULL AND "
                "movielens_id IS NULL "
                "AND EXISTS (SELECT 1 FROM films f WHERE f.tmdb_id = watch_events.tmdb_id "
                "AND f.movielens_id IS NOT NULL)"
            )
            return cur.rowcount

    def add_unmatched(
        self,
        raw_title: str,
        *,
        source: str,
        year: int | None,
        best_score: float | None,
        best_title: str | None,
    ) -> int:
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO unmatched (raw_title, year, source, best_score, best_title, "
                "created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(raw_title) DO UPDATE SET "
                "best_score = excluded.best_score, best_title = excluded.best_title, year = "
                "excluded.year",
                (raw_title, year, source, best_score, best_title, self._now()),
            )
            conn.execute(
                "UPDATE watch_events SET match_status = 'unmatched' WHERE raw_title = ? AND "
                "tmdb_id IS NULL",
                (raw_title,),
            )
            return int(
                conn.execute(
                    "SELECT id FROM unmatched WHERE raw_title = ?", (raw_title,)
                ).fetchone()[0]
            )

    def _unmatched_rows(self, where: str, params: tuple[Any, ...]) -> list[UnmatchedTitle]:
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM unmatched WHERE {where} ORDER BY id", params
            ).fetchall()
            result = []
            for r in rows:
                profiles = sorted(
                    {
                        str(p[0])
                        for p in conn.execute(
                            "SELECT DISTINCT profile FROM watch_events WHERE raw_title = ?",
                            (r["raw_title"],),
                        )
                    }
                )
                result.append(
                    UnmatchedTitle(
                        id=r["id"],
                        raw_title=r["raw_title"],
                        year=r["year"],
                        source=r["source"],
                        best_score=r["best_score"],
                        best_title=r["best_title"],
                        status=r["status"],
                        profiles=profiles,
                    )
                )
            return result

    def list_unmatched(self, status: str = "open") -> list[UnmatchedTitle]:
        return self._unmatched_rows("status = ?", (status,))

    def get_unmatched(self, unmatched_id: int) -> UnmatchedTitle | None:
        rows = self._unmatched_rows("id = ?", (unmatched_id,))
        return rows[0] if rows else None

    def resolve_unmatched(self, unmatched_id: int, tmdb_id: int) -> int:
        item = self.get_unmatched(unmatched_id)
        if item is None:
            raise KeyError(f"Eintrag {unmatched_id} nicht gefunden")
        count = self.assign_title(item.raw_title, tmdb_id)
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE unmatched SET status = 'resolved', resolved_tmdb_id = ? WHERE id = ?",
                (tmdb_id, unmatched_id),
            )
        return count

    def ignore_unmatched(self, unmatched_id: int) -> None:
        item = self.get_unmatched(unmatched_id)
        if item is None:
            raise KeyError(f"Eintrag {unmatched_id} nicht gefunden")
        with self.db.connection() as conn:
            conn.execute("UPDATE unmatched SET status = 'ignored' WHERE id = ?", (unmatched_id,))
            conn.execute(
                "UPDATE watch_events SET match_status = 'ignored' WHERE raw_title = ? AND "
                "tmdb_id IS NULL",
                (item.raw_title,),
            )

    # --- recommendations, twins, new releases ---------------------------------------------
    def save_recommendations(self, recs: Sequence[Any], meta: dict[str, Any]) -> None:
        with self.db.connection() as conn:
            conn.execute("DELETE FROM recommendations")
            conn.executemany(
                "INSERT INTO recommendations (movielens_id, film_id, score, support, twin_mean, "
                "rank) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (r.movielens_id, r.film_id, r.score, r.support, r.twin_mean, r.rank)
                    for r in recs
                ],
            )
            conn.execute(
                "INSERT INTO settings(key, value) VALUES ('recs_meta', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (json.dumps(meta, ensure_ascii=False),),
            )

    def load_recommendations(self) -> list[StoredRecommendation]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT movielens_id, film_id, score, support, twin_mean, rank FROM "
                "recommendations ORDER BY rank"
            )
            return [StoredRecommendation(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]

    def save_twins(self, twins: Sequence[StoredTwin]) -> None:
        with self.db.connection() as conn:
            conn.execute("DELETE FROM twins")
            conn.executemany(
                "INSERT INTO twins (rank, ml_user_id, similarity, overlap, top_movies) VALUES "
                "(?, ?, ?, ?, ?)",
                [
                    (
                        t.rank,
                        t.ml_user_id,
                        t.similarity,
                        t.overlap,
                        json.dumps(t.top_movies, ensure_ascii=False),
                    )
                    for t in twins
                ],
            )

    def load_twins(self) -> list[StoredTwin]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT rank, ml_user_id, similarity, overlap, top_movies FROM twins ORDER BY rank"
            )
            return [StoredTwin(r[0], r[1], r[2], r[3], json.loads(r[4])) for r in rows]

    def save_new_releases(self, film_ids: Sequence[int]) -> None:
        now = self._now()
        with self.db.connection() as conn:
            conn.execute("DELETE FROM new_releases")
            conn.executemany(
                "INSERT OR IGNORE INTO new_releases (film_id, rank, fetched_at) VALUES (?, ?, ?)",
                [(fid, rank, now) for rank, fid in enumerate(film_ids, start=1)],
            )

    def list_new_releases(self) -> list[int]:
        with self.db.connection() as conn:
            return [
                int(r[0]) for r in conn.execute("SELECT film_id FROM new_releases ORDER BY rank")
            ]

    # --- TMDB response cache --------------------------------------------------------------
    def cache_get(self, key: str) -> tuple[Any, datetime] | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT payload, fetched_at FROM tmdb_cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload"]), _parse_dt(row["fetched_at"])

    def cache_put(self, key: str, payload: Any, fetched_at: datetime | None = None) -> None:
        fetched = (fetched_at or self.clock()).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO tmdb_cache (key, payload, fetched_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET payload = excluded.payload, fetched_at = "
                "excluded.fetched_at",
                (key, json.dumps(payload, ensure_ascii=False), fetched),
            )
