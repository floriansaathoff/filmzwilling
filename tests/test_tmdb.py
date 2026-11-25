from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from conftest import load_json
from filmzwilling.repository import Repository
from filmzwilling.tmdb import (
    AUTH_ERROR_MESSAGE,
    MovieDetails,
    TMDBAuthError,
    TMDBClient,
    TMDBError,
    parse_movie,
    parse_offers,
    parse_provider_list,
    parse_search_results,
    poster_url,
)

BASE = "https://api.themoviedb.org/3"


def run(coro):
    return asyncio.run(coro)


class FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@respx.mock
def test_header_with_token() -> None:
    route = respx.get(f"{BASE}/configuration").mock(
        return_value=httpx.Response(200, json={"images": {}})
    )

    async def go():
        async with TMDBClient("secret-token", base_url=BASE) as c:
            return await c.configuration()

    assert run(go()) == {"images": {}}
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer secret-token"
    assert request.headers["Accept"] == "application/json"


@respx.mock
def test_no_header_without_token() -> None:
    route = respx.get(f"{BASE}/configuration").mock(return_value=httpx.Response(200, json={}))

    async def go():
        async with TMDBClient(None, base_url=BASE) as c:
            await c.configuration()
        async with TMDBClient("", base_url=BASE) as c:
            await c.configuration()

    run(go())
    for call in route.calls:
        assert "Authorization" not in call.request.headers


@respx.mock
def test_401_gives_german_message() -> None:
    respx.get(f"{BASE}/configuration").mock(
        return_value=httpx.Response(
            401, json={"status_code": 7, "status_message": "Invalid API key"}
        )
    )

    async def go():
        async with TMDBClient(None, base_url=BASE) as c:
            await c.configuration()

    with pytest.raises(TMDBAuthError) as exc:
        run(go())
    assert (
        str(exc.value) == AUTH_ERROR_MESSAGE == "TMDB-Token fehlt oder ist ungültig, siehe README"
    )


@respx.mock
def test_429_respects_retry_after() -> None:
    route = respx.get(f"{BASE}/configuration").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(429, headers={"Retry-After": "1"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    sleep = FakeSleep()

    async def go():
        async with TMDBClient(None, base_url=BASE, sleep=sleep) as c:
            return await c.configuration()

    assert run(go()) == {"ok": True}
    assert route.call_count == 3
    assert sleep.calls[:2] == [2.0, 1.0]


@respx.mock
def test_exponential_backoff_and_max_attempts() -> None:
    route = respx.get(f"{BASE}/configuration").mock(return_value=httpx.Response(503))
    sleep = FakeSleep()

    async def go():
        async with TMDBClient(None, base_url=BASE, sleep=sleep, max_retries=5) as c:
            await c.configuration()

    with pytest.raises(TMDBError):
        run(go())
    assert route.call_count == 5
    backoffs = [s for s in sleep.calls if s > 0]
    assert len(backoffs) == 4
    assert backoffs == sorted(backoffs)
    assert backoffs[-1] > backoffs[0]


@respx.mock
def test_429_without_retry_after_uses_backoff() -> None:
    respx.get(f"{BASE}/configuration").mock(
        side_effect=[httpx.Response(429), httpx.Response(429), httpx.Response(200, json={})]
    )
    sleep = FakeSleep()

    async def go():
        async with TMDBClient(None, base_url=BASE, sleep=sleep) as c:
            return await c.configuration()

    run(go())
    waits = [s for s in sleep.calls if s > 0]
    assert len(waits) == 2 and waits[1] > waits[0]


@respx.mock
def test_transport_errors_are_retried() -> None:
    respx.get(f"{BASE}/configuration").mock(
        side_effect=[httpx.ConnectError("down"), httpx.Response(200, json={"x": 1})]
    )

    async def go():
        async with TMDBClient(None, base_url=BASE, sleep=FakeSleep()) as c:
            return await c.configuration()

    assert run(go()) == {"x": 1}


@respx.mock
def test_404_returns_none() -> None:
    respx.get(f"{BASE}/movie/1").mock(return_value=httpx.Response(404, json={"status_code": 34}))

    async def go():
        async with TMDBClient(None, base_url=BASE) as c:
            return await c.movie(1)

    assert run(go()) is None


def test_parse_offers_de() -> None:
    offers = parse_offers(load_json("providers_27205.json"))
    got = {(o.provider_id, o.category) for o in offers}
    assert got == {
        (8, "flatrate"),
        (219, "free"),
        (1796, "ads"),
        (10, "rent"),
        (2, "buy"),
        (10, "buy"),
    }
    netflix = next(o for o in offers if o.provider_id == 8)
    assert netflix.provider_name == "Netflix"
    assert netflix.logo_path == "/netflix.jpg"
    assert parse_offers({"results": {"US": {}}}) == []
    assert parse_offers(None) == []
    assert parse_offers({}) == []


def test_parse_movie() -> None:
    m = parse_movie(load_json("movie_27205.json"))
    assert isinstance(m, MovieDetails)
    assert (m.tmdb_id, m.title, m.original_title, m.runtime) == (
        27205,
        "Inception",
        "Inception",
        148,
    )
    assert m.genres == ["Action", "Science Fiction", "Abenteuer"]
    assert m.poster_path == "/inception.jpg"
    assert m.vote_average == pytest.approx(8.369)
    assert m.vote_count == 37000
    assert m.release_date == "2010-07-15"
    assert m.year == 2010
    assert m.offers is not None and len(m.offers) == 6
    pate = parse_movie(load_json("movie_238.json"))
    assert pate.title == "Der Pate"
    assert pate.original_title == "The Godfather"
    assert pate.poster_path is None
    assert pate.offers == []


def test_parse_movie_missing_fields() -> None:
    m = parse_movie({"id": 5, "title": "X"})
    assert m.runtime is None and m.year is None and m.genres == [] and m.offers is None
    assert parse_movie({"id": 6, "title": "Y", "release_date": "", "runtime": 0}).runtime is None


def test_parse_search_and_providers() -> None:
    results = parse_search_results(load_json("search_der_pate.json"))
    assert [r.tmdb_id for r in results] == [238, 240, 242]
    assert results[0].year == 1972
    assert results[0].original_title == "The Godfather"
    providers = parse_provider_list(load_json("providers_de.json"))
    assert providers[0].name == "Netflix" and providers[0].provider_id == 8
    assert len(providers) == 15


def test_poster_url() -> None:
    assert poster_url("/abc.jpg") == "https://image.tmdb.org/t/p/w342/abc.jpg"
    assert poster_url(None) is None
    assert poster_url("") is None


@respx.mock
def test_movie_request_params() -> None:
    route = respx.get(f"{BASE}/movie/27205").mock(
        return_value=httpx.Response(200, json=load_json("movie_27205.json"))
    )

    async def go():
        async with TMDBClient(None, base_url=BASE) as c:
            return await c.movie(27205)

    m = run(go())
    assert m is not None and m.title == "Inception"
    params = route.calls.last.request.url.params
    assert params["language"] == "de-DE"
    assert params["append_to_response"] == "watch/providers"


@respx.mock
def test_movie_cache_and_expiry(repo: Repository) -> None:
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    full = respx.get(f"{BASE}/movie/27205").mock(
        return_value=httpx.Response(200, json=load_json("movie_27205.json"))
    )
    prov = respx.get(f"{BASE}/movie/27205/watch/providers").mock(
        return_value=httpx.Response(200, json=load_json("providers_27205.json"))
    )

    async def fetch():
        async with TMDBClient(None, base_url=BASE, cache=repo, clock=lambda: now[0]) as c:
            return await c.movie(27205)

    first = run(fetch())
    second = run(fetch())
    assert first == second
    assert full.call_count == 1 and prov.call_count == 0
    now[0] += timedelta(days=8)  # providers stale, metadata fresh
    third = run(fetch())
    assert full.call_count == 1 and prov.call_count == 1
    assert third is not None and third.offers is not None and len(third.offers) == 6
    now[0] += timedelta(days=23)  # 31 days after first fetch: metadata stale
    run(fetch())
    assert full.call_count == 2


@respx.mock
def test_force_refresh(repo: Repository) -> None:
    full = respx.get(f"{BASE}/movie/27205").mock(
        return_value=httpx.Response(200, json=load_json("movie_27205.json"))
    )

    async def go():
        async with TMDBClient(None, base_url=BASE, cache=repo) as c:
            await c.movie(27205)
            await c.movie(27205, force=True)

    run(go())
    assert full.call_count == 2


@respx.mock
def test_movie_offers_only(repo: Repository) -> None:
    prov = respx.get(f"{BASE}/movie/27205/watch/providers").mock(
        return_value=httpx.Response(200, json=load_json("providers_27205.json"))
    )

    async def go():
        async with TMDBClient(None, base_url=BASE, cache=repo) as c:
            a = await c.movie_offers(27205)
            b = await c.movie_offers(27205)
            return a, b

    a, b = run(go())
    assert a == b and len(a) == 6
    assert prov.call_count == 1


@respx.mock
def test_search_params_and_cache(repo: Repository) -> None:
    route = respx.get(f"{BASE}/search/movie").mock(
        return_value=httpx.Response(200, json=load_json("search_inception.json"))
    )

    async def go():
        async with TMDBClient(None, base_url=BASE, cache=repo) as c:
            a = await c.search_movie("Inception", year=2010)
            b = await c.search_movie("Inception", year=2010)
            c2 = await c.search_movie("Inception")
            return a, b, c2

    a, b, c2 = run(go())
    assert a == b == c2
    assert route.call_count == 2
    p = route.calls[0].request.url.params
    assert (p["query"], p["language"], p["region"], p["year"]) == (
        "Inception",
        "de-DE",
        "DE",
        "2010",
    )
    assert "year" not in route.calls[1].request.url.params


@respx.mock
def test_provider_list_params() -> None:
    route = respx.get(f"{BASE}/watch/providers/movie").mock(
        return_value=httpx.Response(200, json=load_json("providers_de.json"))
    )

    async def go():
        async with TMDBClient(None, base_url=BASE) as c:
            return await c.provider_list()

    providers = run(go())
    assert len(providers) == 15
    p = route.calls.last.request.url.params
    assert p["watch_region"] == "DE" and p["language"] == "de-DE"


@respx.mock
def test_discover_params_and_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=load_json(f"discover_page{request.url.params['page']}.json")
        )

    route = respx.get(f"{BASE}/discover/movie").mock(side_effect=handler)

    async def go():
        async with TMDBClient(None, base_url=BASE) as c:
            return await c.discover_new([8, 9, 337], pages=5)

    results = run(go())
    assert [r.tmdb_id for r in results] == [1022789, 872585, 1184918]
    assert route.call_count == 2
    p = route.calls[0].request.url.params
    assert p["watch_region"] == "DE"
    assert p["with_watch_providers"] == "8|9|337"
    assert p["with_watch_monetization_types"] == "flatrate|free|ads"
    assert p["primary_release_date.gte"] == "2023-10-01"
    assert p["vote_count.gte"] == "100"
    assert p["language"] == "de-DE"
    assert p["sort_by"] == "vote_average.desc"


def test_rate_limit_spacing() -> None:
    stamps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        stamps.append(time.monotonic())
        return httpx.Response(200, json={})

    async def go():
        async with TMDBClient(
            None, base_url=BASE, transport=httpx.MockTransport(handler), max_rps=5
        ) as c:
            await asyncio.gather(*(c.configuration() for _ in range(12)))
            return c.request_count

    assert run(go()) == 12
    stamps.sort()
    for i in range(len(stamps) - 5):
        assert stamps[i + 5] - stamps[i] >= 0.95


@respx.mock
def test_movies_concurrently(repo: Repository) -> None:
    respx.get(f"{BASE}/movie/27205").mock(
        return_value=httpx.Response(200, json=load_json("movie_27205.json"))
    )
    respx.get(f"{BASE}/movie/238").mock(
        return_value=httpx.Response(200, json=load_json("movie_238.json"))
    )
    respx.get(f"{BASE}/movie/1").mock(return_value=httpx.Response(404))

    async def go():
        async with TMDBClient(None, base_url=BASE, cache=repo) as c:
            return await c.movies([27205, 238, 1])

    result = run(go())
    assert set(result) == {27205, 238}
    assert result[238].title == "Der Pate"


def test_parse_videos_order() -> None:
    from filmzwilling.tmdb import parse_videos

    videos = parse_videos(load_json("videos_27205.json"))
    # Only YouTube trailers and teasers; German official trailer first, fan upload after
    # official ones, teaser last.
    assert [v.key for v in videos] == ["u_ckVuUUeZw", "FANde000001", "YoHD9XEInc0", "TEASERde001"]
    assert videos[0].language == "de" and videos[0].official is True
    assert parse_videos(None) == []
    assert parse_videos({"results": [{"site": "YouTube", "type": "Trailer"}]}) == []


def test_parse_movie_backdrop_and_overview() -> None:
    details = parse_movie(load_json("movie_27205.json"))
    assert details.backdrop_path and details.backdrop_path.startswith("/")
    assert details.overview
    empty = parse_movie({"id": 1, "title": "X", "overview": "  "})
    assert empty.backdrop_path is None and empty.overview is None


@respx.mock
def test_videos_cached(repo: Repository) -> None:
    route = respx.get(f"{BASE}/movie/27205/videos").mock(
        return_value=httpx.Response(200, json=load_json("videos_27205.json"))
    )

    async def go():
        async with TMDBClient(None, base_url=BASE, cache=repo) as c:
            first = await c.videos(27205)
            second = await c.videos(27205)
            return first, second

    first, second = run(go())
    assert first == second and first[0].key == "u_ckVuUUeZw"
    assert route.call_count == 1
    params = route.calls.last.request.url.params
    assert params["language"] == "de-DE"
    assert params["include_video_language"] == "de,en,null"
