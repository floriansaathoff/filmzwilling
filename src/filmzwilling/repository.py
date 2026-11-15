"""Repository layer over the SQLite app database."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from filmzwilling.db import Database

ACTION_RATE = "rate"
ACTION_NOT_SEEN = "not_seen"
ACTION_LATER = "later"
STATUS_NOT_SEEN = "not_seen"
STATUS_NOT_INTERESTED = "not_interested"
DEFAULT_QUEUE_SIZE = 1000


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
        raise NotImplementedError

    @property
    def display_year(self) -> int | None:
        raise NotImplementedError

    @property
    def display_genres(self) -> list[str]:
        """German genres from TMDB, else MovieLens genres mapped to German."""
        raise NotImplementedError


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
    raise NotImplementedError


class Repository:
    def __init__(self, db: Database, clock: Callable[[], datetime] = utcnow) -> None:
        self.db = db
        self.clock = clock

    # --- settings -------------------------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        raise NotImplementedError

    def set_setting(self, key: str, value: Any) -> None:
        raise NotImplementedError

    def get_user_settings(self) -> UserSettings:
        raise NotImplementedError

    def update_user_settings(
        self,
        *,
        my_profiles: list[str] | None = None,
        my_providers: list[int] | None = None,
        queue_size: int | None = None,
    ) -> UserSettings:
        raise NotImplementedError

    # --- films ----------------------------------------------------------------------------
    def upsert_movielens_films(self, films: Iterable[MovieLensFilm]) -> int:
        raise NotImplementedError

    def upsert_tmdb_details(self, details: Any, fetched_at: datetime | None = None) -> int:
        """Store TMDB metadata (a `tmdb.MovieDetails`); returns the film id."""
        raise NotImplementedError

    def set_film_offers(
        self, film_id: int, offers: Sequence[Any], fetched_at: datetime | None = None
    ) -> None:
        raise NotImplementedError

    def ensure_film(self, tmdb_id: int, title: str | None = None, year: int | None = None) -> int:
        raise NotImplementedError

    def get_film(self, film_id: int) -> Film | None:
        raise NotImplementedError

    def get_films(self, film_ids: Iterable[int]) -> dict[int, Film]:
        raise NotImplementedError

    def film_id_for_tmdb(self, tmdb_id: int) -> int | None:
        raise NotImplementedError

    def film_id_for_movielens(self, movielens_id: int) -> int | None:
        raise NotImplementedError

    def movielens_film_map(self) -> dict[int, int]:
        """movielens_id -> film_id for all films."""
        raise NotImplementedError

    def film_offers(self, film_ids: Iterable[int]) -> dict[int, list[Offer]]:
        raise NotImplementedError

    def films_missing_metadata(self, film_ids: Iterable[int], max_age_days: int = 30) -> list[int]:
        raise NotImplementedError

    def films_missing_offers(self, film_ids: Iterable[int], max_age_days: int = 7) -> list[int]:
        raise NotImplementedError

    def popular_film_ids(self, limit: int) -> list[int]:
        """Films with movielens_id and tmdb_id ordered by popularity rank."""
        raise NotImplementedError

    def search_films(self, query: str, limit: int = 20) -> list[Film]:
        raise NotImplementedError

    def count_films(self) -> int:
        raise NotImplementedError

    # --- providers ------------------------------------------------------------------------
    def upsert_providers(self, providers: Sequence[Any]) -> None:
        raise NotImplementedError

    def list_providers(self) -> list[Any]:
        raise NotImplementedError

    # --- ratings and statuses -------------------------------------------------------------
    def set_rating(self, film_id: int, score: int, *, log_action: bool = True) -> None:
        raise NotImplementedError

    def delete_rating(self, film_id: int) -> bool:
        raise NotImplementedError

    def get_rating(self, film_id: int) -> int | None:
        raise NotImplementedError

    def list_ratings(self, query: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    def count_ratings(self) -> int:
        raise NotImplementedError

    def ratings_for_cf(self) -> dict[int, int]:
        """{movielens_id: note} for all rated films with a MovieLens id."""
        raise NotImplementedError

    def mark_not_seen(self, film_id: int, *, log_action: bool = True) -> None:
        raise NotImplementedError

    def mark_not_interested(self, film_id: int) -> None:
        raise NotImplementedError

    def defer(self, film_id: int, *, log_action: bool = True) -> None:
        raise NotImplementedError

    def undo_last(self) -> dict[str, Any] | None:
        """Revert the most recent queue action; returns {"action", "film_id"} or None."""
        raise NotImplementedError

    def statuses(self) -> dict[int, str]:
        raise NotImplementedError

    def rated_film_ids(self) -> set[int]:
        raise NotImplementedError

    def deferred_order(self) -> dict[int, int]:
        """film_id -> defer sequence number (higher = deferred later)."""
        raise NotImplementedError

    def count_status(self, status: str) -> int:
        raise NotImplementedError

    # --- watch events and matching --------------------------------------------------------
    def upsert_watch_event(self, event: Any) -> str:
        """Insert or update by (source, profile, raw_title). Returns inserted/updated/unchanged."""
        raise NotImplementedError

    def merge_event_hints(
        self, source: str, profile: str, raw_title: str, hints: dict[str, Any]
    ) -> None:
        raise NotImplementedError

    def list_watch_events(self) -> list[StoredEvent]:
        raise NotImplementedError

    def count_watch_events(self) -> int:
        raise NotImplementedError

    def profiles(self) -> list[str]:
        raise NotImplementedError

    def pending_titles(self) -> list[dict[str, Any]]:
        """Distinct raw titles without tmdb_id that are not ignored/unmatched."""
        raise NotImplementedError

    def assign_title(self, raw_title: str, tmdb_id: int) -> int:
        """Attach a TMDB id (and MovieLens id if known) to all events with this raw title."""
        raise NotImplementedError

    def mark_title_series(self, raw_title: str) -> None:
        raise NotImplementedError

    def relink_movielens_ids(self) -> int:
        raise NotImplementedError

    def add_unmatched(
        self,
        raw_title: str,
        *,
        source: str,
        year: int | None,
        best_score: float | None,
        best_title: str | None,
    ) -> int:
        raise NotImplementedError

    def list_unmatched(self, status: str = "open") -> list[UnmatchedTitle]:
        raise NotImplementedError

    def get_unmatched(self, unmatched_id: int) -> UnmatchedTitle | None:
        raise NotImplementedError

    def resolve_unmatched(self, unmatched_id: int, tmdb_id: int) -> int:
        raise NotImplementedError

    def ignore_unmatched(self, unmatched_id: int) -> None:
        raise NotImplementedError

    # --- recommendations, twins, new releases ---------------------------------------------
    def save_recommendations(self, recs: Sequence[Any], meta: dict[str, Any]) -> None:
        raise NotImplementedError

    def load_recommendations(self) -> list[StoredRecommendation]:
        raise NotImplementedError

    def save_twins(self, twins: Sequence[StoredTwin]) -> None:
        raise NotImplementedError

    def load_twins(self) -> list[StoredTwin]:
        raise NotImplementedError

    def save_new_releases(self, film_ids: Sequence[int]) -> None:
        raise NotImplementedError

    def list_new_releases(self) -> list[int]:
        raise NotImplementedError

    # --- TMDB response cache --------------------------------------------------------------
    def cache_get(self, key: str) -> tuple[Any, datetime] | None:
        raise NotImplementedError

    def cache_put(self, key: str, payload: Any, fetched_at: datetime | None = None) -> None:
        raise NotImplementedError
