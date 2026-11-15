"""Async TMDB v3 client with rate limiting, retries and SQLite-backed caching."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

import httpx

TMDB_BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/"
AUTH_ERROR_MESSAGE = "TMDB-Token fehlt oder ist ungültig, siehe README"
OFFER_CATEGORIES = ("flatrate", "free", "ads", "rent", "buy")
META_TTL = timedelta(days=30)
PROVIDER_TTL = timedelta(days=7)
SEARCH_TTL = timedelta(days=30)


class TMDBError(Exception):
    pass


class TMDBAuthError(TMDBError):
    def __init__(self, message: str = AUTH_ERROR_MESSAGE) -> None:
        super().__init__(message)


class Cache(Protocol):
    def cache_get(self, key: str) -> tuple[Any, datetime] | None: ...

    def cache_put(self, key: str, payload: Any, fetched_at: datetime | None = None) -> None: ...


@dataclass(frozen=True)
class ProviderOffer:
    provider_id: int
    provider_name: str
    logo_path: str | None
    category: str
    display_priority: int = 0


@dataclass(frozen=True)
class Provider:
    provider_id: int
    name: str
    logo_path: str | None = None
    display_priority: int = 0


@dataclass(frozen=True)
class SearchResult:
    tmdb_id: int
    title: str
    original_title: str
    release_date: str | None
    popularity: float = 0.0
    vote_count: int = 0
    vote_average: float = 0.0
    poster_path: str | None = None
    media_type: str = "movie"
    genre_ids: tuple[int, ...] = ()

    @property
    def year(self) -> int | None:
        raise NotImplementedError


@dataclass(frozen=True)
class MovieDetails:
    tmdb_id: int
    title: str
    original_title: str
    runtime: int | None
    genres: list[str]
    poster_path: str | None
    vote_average: float | None
    vote_count: int | None
    release_date: str | None
    popularity: float | None = None
    imdb_id: str | None = None
    offers: list[ProviderOffer] | None = field(default=None)

    @property
    def year(self) -> int | None:
        raise NotImplementedError


def poster_url(poster_path: str | None, size: str = "w342") -> str | None:
    raise NotImplementedError


def parse_offers(payload: dict[str, Any] | None, region: str = "DE") -> list[ProviderOffer]:
    """Parse a watch/providers payload ({"results": {"DE": {...}}})."""
    raise NotImplementedError


def parse_movie(payload: dict[str, Any], region: str = "DE") -> MovieDetails:
    raise NotImplementedError


def parse_search_results(payload: dict[str, Any]) -> list[SearchResult]:
    raise NotImplementedError


def parse_provider_list(payload: dict[str, Any]) -> list[Provider]:
    raise NotImplementedError


class TMDBClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = TMDB_BASE_URL,
        cache: Cache | None = None,
        max_rps: int = 20,
        max_retries: int = 5,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], datetime] | None = None,
        timeout: float = 15.0,
    ) -> None:
        raise NotImplementedError

    async def __aenter__(self) -> TMDBClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        raise NotImplementedError

    @property
    def request_count(self) -> int:
        raise NotImplementedError

    def headers(self) -> dict[str, str]:
        raise NotImplementedError

    async def get_json(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """GET with rate limit and retries. Returns None on 404, raises TMDBAuthError on 401."""
        raise NotImplementedError

    async def configuration(self) -> dict[str, Any] | None:
        raise NotImplementedError

    async def movie(self, tmdb_id: int, *, force: bool = False) -> MovieDetails | None:
        raise NotImplementedError

    async def movies(
        self, tmdb_ids: Iterable[int], *, force: bool = False
    ) -> dict[int, MovieDetails]:
        raise NotImplementedError

    async def movie_offers(self, tmdb_id: int, *, force: bool = False) -> list[ProviderOffer]:
        raise NotImplementedError

    async def search_movie(self, query: str, year: int | None = None) -> list[SearchResult]:
        raise NotImplementedError

    async def provider_list(self) -> list[Provider]:
        raise NotImplementedError

    async def discover_new(
        self,
        provider_ids: Sequence[int],
        *,
        since: str = "2023-10-01",
        min_votes: int = 100,
        pages: int = 3,
    ) -> list[SearchResult]:
        raise NotImplementedError
