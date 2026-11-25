"""Async TMDB v3 client with rate limiting, retries and SQLite-backed caching.

Without a token the requests are sent without an Authorization header, because in some
environments a proxy injects the credentials. Only an HTTP 401 produces the German error message.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx

TMDB_BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/"
AUTH_ERROR_MESSAGE = "TMDB-Token fehlt oder ist ungültig, siehe README"
OFFER_CATEGORIES = ("flatrate", "free", "ads", "rent", "buy")
META_TTL = timedelta(days=30)
PROVIDER_TTL = timedelta(days=7)
SEARCH_TTL = timedelta(days=30)
VIDEO_TTL = timedelta(days=14)
VIDEO_LANGUAGES = "de,en,null"
LANGUAGE = "de-DE"
REGION = "DE"
MAX_BACKOFF = 30.0


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


def _year(date: str | None) -> int | None:
    if not date or len(date) < 4 or not date[:4].isdigit():
        return None
    return int(date[:4])


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
        return _year(self.release_date)


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
    backdrop_path: str | None = None
    overview: str | None = None

    @property
    def year(self) -> int | None:
        return _year(self.release_date)


def poster_url(poster_path: str | None, size: str = "w342") -> str | None:
    if not poster_path:
        return None
    return f"{IMAGE_BASE_URL}{size}{poster_path}"


def parse_offers(payload: dict[str, Any] | None, region: str = REGION) -> list[ProviderOffer]:
    """Parse a watch/providers payload ({"results": {"DE": {...}}})."""
    if not payload:
        return []
    results = payload.get("results") or {}
    local = results.get(region) or {}
    offers: list[ProviderOffer] = []
    for category in OFFER_CATEGORIES:
        for entry in local.get(category) or []:
            if "provider_id" not in entry:
                continue
            offers.append(
                ProviderOffer(
                    provider_id=int(entry["provider_id"]),
                    provider_name=str(entry.get("provider_name") or ""),
                    logo_path=entry.get("logo_path"),
                    category=category,
                    display_priority=int(entry.get("display_priority") or 0),
                )
            )
    return offers


def parse_movie(payload: dict[str, Any], region: str = REGION) -> MovieDetails:
    runtime = payload.get("runtime")
    providers = payload.get("watch/providers")
    return MovieDetails(
        tmdb_id=int(payload["id"]),
        title=str(payload.get("title") or payload.get("original_title") or ""),
        original_title=str(payload.get("original_title") or payload.get("title") or ""),
        runtime=int(runtime) if runtime else None,
        genres=[str(g["name"]) for g in payload.get("genres") or [] if g.get("name")],
        poster_path=payload.get("poster_path") or None,
        vote_average=payload.get("vote_average"),
        vote_count=payload.get("vote_count"),
        release_date=payload.get("release_date") or None,
        popularity=payload.get("popularity"),
        imdb_id=payload.get("imdb_id"),
        offers=parse_offers(providers, region) if "watch/providers" in payload else None,
        backdrop_path=payload.get("backdrop_path") or None,
        overview=(str(payload.get("overview") or "").strip() or None),
    )


@dataclass(frozen=True)
class Video:
    """A YouTube trailer or teaser from /movie/{id}/videos."""

    key: str
    name: str
    language: str | None
    type: str
    official: bool = False
    size: int = 0
    published_at: str | None = None


VIDEO_TYPE_RANK = {"Trailer": 0, "Teaser": 1}


def parse_videos(payload: dict[str, Any] | None, prefer_language: str = "de") -> list[Video]:
    """YouTube trailers and teasers, best first: trailer before teaser, German before other
    languages, official before fan uploads, larger resolution and newer first."""
    videos: list[Video] = []
    for item in (payload or {}).get("results") or []:
        if str(item.get("site") or "") != "YouTube" or not item.get("key"):
            continue
        kind = str(item.get("type") or "")
        if kind not in VIDEO_TYPE_RANK:
            continue
        videos.append(
            Video(
                key=str(item["key"]),
                name=str(item.get("name") or kind),
                language=item.get("iso_639_1") or None,
                type=kind,
                official=bool(item.get("official")),
                size=int(item.get("size") or 0),
                published_at=item.get("published_at") or None,
            )
        )
    videos.sort(key=lambda v: v.published_at or "", reverse=True)
    videos.sort(
        key=lambda v: (
            VIDEO_TYPE_RANK[v.type],
            v.language != prefer_language,
            not v.official,
            -v.size,
        )
    )
    return videos


def parse_search_results(payload: dict[str, Any]) -> list[SearchResult]:
    results: list[SearchResult] = []
    for item in payload.get("results") or []:
        if "id" not in item:
            continue
        title = item.get("title") or item.get("name") or ""
        results.append(
            SearchResult(
                tmdb_id=int(item["id"]),
                title=str(title),
                original_title=str(
                    item.get("original_title") or item.get("original_name") or title
                ),
                release_date=item.get("release_date") or item.get("first_air_date") or None,
                popularity=float(item.get("popularity") or 0.0),
                vote_count=int(item.get("vote_count") or 0),
                vote_average=float(item.get("vote_average") or 0.0),
                poster_path=item.get("poster_path") or None,
                media_type=str(item.get("media_type") or "movie"),
                genre_ids=tuple(int(g) for g in item.get("genre_ids") or []),
            )
        )
    return results


def parse_provider_list(payload: dict[str, Any]) -> list[Provider]:
    providers: list[Provider] = []
    for item in payload.get("results") or []:
        priorities = item.get("display_priorities") or {}
        providers.append(
            Provider(
                provider_id=int(item["provider_id"]),
                name=str(item.get("provider_name") or ""),
                logo_path=item.get("logo_path"),
                display_priority=int(priorities.get(REGION, item.get("display_priority") or 0)),
            )
        )
    return providers


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


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
        self.token = (token or "").strip() or None
        self.cache = cache
        self.max_rps = max(1, int(max_rps))
        self.max_retries = max(1, int(max_retries))
        self._sleep = sleep or asyncio.sleep
        self._clock = clock or (lambda: datetime.now(UTC))
        self._client = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout)
        self._semaphore = asyncio.Semaphore(self.max_rps)
        self._window: deque[float] = deque()
        self._window_lock = asyncio.Lock()
        self._count = 0

    async def __aenter__(self) -> TMDBClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def request_count(self) -> int:
        return self._count

    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _throttle(self) -> None:
        """Sliding window: at most `max_rps` requests started per second."""
        async with self._window_lock:
            while True:
                now = time.monotonic()
                while self._window and now - self._window[0] >= 1.0:
                    self._window.popleft()
                if len(self._window) < self.max_rps:
                    self._window.append(now)
                    return
                await asyncio.sleep(1.0 - (now - self._window[0]) + 0.001)

    async def get_json(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """GET with rate limit and retries. Returns None on 404, raises TMDBAuthError on 401."""
        last_problem = "unbekannter Fehler"
        for attempt in range(1, self.max_retries + 1):
            delay = min(MAX_BACKOFF, 0.5 * 2 ** (attempt - 1))
            async with self._semaphore:
                await self._throttle()
                try:
                    response = await self._client.get(path, params=params, headers=self.headers())
                except httpx.TransportError as exc:
                    self._count += 1
                    last_problem = f"Netzwerkfehler: {exc}"
                    response = None
                else:
                    self._count += 1
            if response is not None:
                status = response.status_code
                if status == 401:
                    raise TMDBAuthError()
                if status == 404:
                    return None
                if status == 429:
                    wait = _retry_after(response)
                    delay = wait if wait is not None else delay
                    last_problem = "zu viele Anfragen (429)"
                elif status >= 500:
                    last_problem = f"Serverfehler {status}"
                elif status >= 400:
                    raise TMDBError(f"TMDB antwortet mit Fehler {status} für {path}")
                else:
                    data: dict[str, Any] = response.json()
                    return data
            if attempt < self.max_retries:
                await self._sleep(delay)
        raise TMDBError(f"TMDB nicht erreichbar nach {self.max_retries} Versuchen ({last_problem})")

    # --- cache helpers --------------------------------------------------------------------
    def _cached(self, key: str, ttl: timedelta) -> Any | None:
        if self.cache is None:
            return None
        hit = self.cache.cache_get(key)
        if hit is None:
            return None
        payload, fetched_at = hit
        if self._clock() - fetched_at >= ttl:
            return None
        return payload

    def _store(self, key: str, payload: Any) -> None:
        if self.cache is not None:
            self.cache.cache_put(key, payload, self._clock())

    # --- endpoints ------------------------------------------------------------------------
    async def configuration(self) -> dict[str, Any] | None:
        return await self.get_json("/configuration")

    async def movie(self, tmdb_id: int, *, force: bool = False) -> MovieDetails | None:
        meta_key, prov_key = f"movie:{tmdb_id}", f"providers:{tmdb_id}"
        meta = None if force else self._cached(meta_key, META_TTL)
        if meta is not None:
            if meta.get("__missing__"):
                return None
            providers = None if force else self._cached(prov_key, PROVIDER_TTL)
            if providers is None:
                providers = await self.get_json(f"/movie/{tmdb_id}/watch/providers") or {
                    "results": {}
                }
                self._store(prov_key, providers)
            return replace(parse_movie(meta), offers=parse_offers(providers))
        payload = await self.get_json(
            f"/movie/{tmdb_id}", {"language": LANGUAGE, "append_to_response": "watch/providers"}
        )
        if payload is None:
            self._store(meta_key, {"__missing__": True})
            return None
        providers = payload.pop("watch/providers", None) or {"results": {}}
        self._store(meta_key, payload)
        self._store(prov_key, providers)
        return replace(parse_movie(payload), offers=parse_offers(providers))

    async def movies(
        self, tmdb_ids: Iterable[int], *, force: bool = False
    ) -> dict[int, MovieDetails]:
        ids = list(dict.fromkeys(int(i) for i in tmdb_ids))
        results = await asyncio.gather(*(self.movie(i, force=force) for i in ids))
        return {i: m for i, m in zip(ids, results, strict=True) if m is not None}

    async def movie_offers(self, tmdb_id: int, *, force: bool = False) -> list[ProviderOffer]:
        key = f"providers:{tmdb_id}"
        payload = None if force else self._cached(key, PROVIDER_TTL)
        if payload is None:
            payload = await self.get_json(f"/movie/{tmdb_id}/watch/providers") or {"results": {}}
            self._store(key, payload)
        return parse_offers(payload)

    async def videos(self, tmdb_id: int, *, force: bool = False) -> list[Video]:
        key = f"videos:{tmdb_id}"
        payload = None if force else self._cached(key, VIDEO_TTL)
        if payload is None:
            payload = await self.get_json(
                f"/movie/{tmdb_id}/videos",
                {"language": LANGUAGE, "include_video_language": VIDEO_LANGUAGES},
            ) or {"results": []}
            self._store(key, payload)
        return parse_videos(payload)

    async def search_movie(self, query: str, year: int | None = None) -> list[SearchResult]:
        key = f"search:{query.strip().lower()}|{year or ''}"
        payload = self._cached(key, SEARCH_TTL)
        if payload is None:
            params: dict[str, Any] = {
                "query": query,
                "language": LANGUAGE,
                "region": REGION,
                "include_adult": "false",
            }
            if year:
                params["year"] = str(year)
            payload = await self.get_json("/search/movie", params) or {"results": []}
            self._store(key, payload)
        return parse_search_results(payload)

    async def provider_list(self) -> list[Provider]:
        payload = await self.get_json(
            "/watch/providers/movie", {"watch_region": REGION, "language": LANGUAGE}
        )
        return parse_provider_list(payload or {})

    async def discover_new(
        self,
        provider_ids: Sequence[int],
        *,
        since: str = "2023-10-01",
        min_votes: int = 100,
        pages: int = 3,
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[int] = set()
        for page in range(1, max(1, pages) + 1):
            params: dict[str, Any] = {
                "watch_region": REGION,
                "language": LANGUAGE,
                "with_watch_monetization_types": "flatrate|free|ads",
                "primary_release_date.gte": since,
                "vote_count.gte": str(min_votes),
                "sort_by": "vote_average.desc",
                "page": str(page),
            }
            if provider_ids:
                params["with_watch_providers"] = "|".join(str(p) for p in provider_ids)
            payload = await self.get_json("/discover/movie", params) or {}
            for item in parse_search_results(payload):
                if item.tmdb_id not in seen:
                    seen.add(item.tmdb_id)
                    results.append(item)
            if page >= int(payload.get("total_pages") or 0):
                break
        return results
