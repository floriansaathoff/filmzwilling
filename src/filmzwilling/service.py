"""Application service: glues repository, MovieLens data, TMDB and the recommender together."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx

from filmzwilling.config import RecommenderConfig, Settings
from filmzwilling.evaluate import EvalResult
from filmzwilling.filters import RecFilter, RecItem
from filmzwilling.importers.common import ImportReport, ParseResult
from filmzwilling.movielens import ProcessedData
from filmzwilling.rating_queue import Progress
from filmzwilling.repository import Film, Repository
from filmzwilling.tmdb import Provider, TMDBClient


class ServiceError(Exception):
    """User-facing error with a German message."""


@dataclass(frozen=True)
class CheckResult:
    query: str
    found: bool
    movielens_id: int | None = None
    title: str | None = None
    year: int | None = None
    tmdb_id: int | None = None
    rating_count: int | None = None
    mean_rating: float | None = None
    popularity_rank: int | None = None
    total_movies: int | None = None
    queue_position: int | None = None
    queue_size: int | None = None
    own_rating: int | None = None
    note: str | None = None


class FilmService:
    def __init__(
        self,
        settings: Settings,
        *,
        repo: Repository | None = None,
        data: ProcessedData | None = None,
        config: RecommenderConfig | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        raise NotImplementedError

    # --- infrastructure -------------------------------------------------------------------
    def data(self) -> ProcessedData | None:
        raise NotImplementedError

    def require_data(self) -> ProcessedData:
        raise NotImplementedError

    def tmdb(self) -> TMDBClient | None:
        raise NotImplementedError

    def sync_movielens_films(self) -> int:
        raise NotImplementedError

    # --- rating queue ---------------------------------------------------------------------
    def film_card(self, film: Film, entry: Any = None) -> dict[str, Any]:
        raise NotImplementedError

    def queue_items(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        raise NotImplementedError

    def progress(self) -> Progress:
        raise NotImplementedError

    def rate(self, film_id: int, score: int, *, from_queue: bool = True) -> bool:
        """Store a rating; returns True if a background recomputation was started."""
        raise NotImplementedError

    def not_seen(self, film_id: int) -> None:
        raise NotImplementedError

    def later(self, film_id: int) -> None:
        raise NotImplementedError

    def not_interested(self, film_id: int) -> None:
        raise NotImplementedError

    def undo(self) -> dict[str, Any] | None:
        raise NotImplementedError

    # --- recommendations ------------------------------------------------------------------
    def recompute(self) -> dict[str, Any]:
        raise NotImplementedError

    def maybe_recompute_in_background(self) -> bool:
        raise NotImplementedError

    def wait_for_background(self, timeout: float | None = None) -> None:
        raise NotImplementedError

    def recommendation_items(self) -> list[RecItem]:
        raise NotImplementedError

    def recommendations(self, flt: RecFilter, *, limit: int = 120) -> dict[str, Any]:
        raise NotImplementedError

    def new_release_items(self, flt: RecFilter, *, limit: int = 60) -> list[dict[str, Any]]:
        raise NotImplementedError

    def default_provider_ids(self) -> list[int]:
        raise NotImplementedError

    def twins(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def evaluate(self) -> EvalResult:
        raise NotImplementedError

    def top_recommendations(self, n: int = 20) -> list[dict[str, Any]]:
        raise NotImplementedError

    def check_title(self, title: str, year: int | None = None) -> CheckResult:
        raise NotImplementedError

    # --- imports --------------------------------------------------------------------------
    def store_import(
        self, result: ParseResult, thumbs: Iterable[dict[str, Any]] = ()
    ) -> ImportReport:
        raise NotImplementedError

    def import_file(self, kind: str, path: Any, **options: Any) -> ImportReport:
        """kind in netflix|prime|csv; parses, stores and (if TMDB available) matches titles."""
        raise NotImplementedError

    # --- TMDB -----------------------------------------------------------------------------
    async def match_pending(self) -> Any:
        raise NotImplementedError

    async def sync_metadata(self, film_ids: Iterable[int], *, force: bool = False) -> int:
        raise NotImplementedError

    async def sync_queue_metadata(self, limit: int | None = None) -> int:
        raise NotImplementedError

    async def refresh_providers(self) -> list[Provider]:
        raise NotImplementedError

    async def refresh_availability(self, limit: int | None = None) -> int:
        raise NotImplementedError

    async def refresh_new_releases(self) -> int:
        raise NotImplementedError

    async def search_tmdb(self, query: str, year: int | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def resolve_unmatched(self, unmatched_id: int, tmdb_id: int) -> int:
        raise NotImplementedError
