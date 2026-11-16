from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
import respx

from conftest import load_json
from filmzwilling.importers.common import WatchEvent
from filmzwilling.matching import (
    choose_best,
    clean_query,
    match_pending,
    match_title,
    normalize_title,
    score_candidate,
    title_similarity,
)
from filmzwilling.movielens import load_processed, process_movielens
from filmzwilling.repository import MovieLensFilm, Repository
from filmzwilling.tmdb import SearchResult, TMDBClient

BASE = "https://api.themoviedb.org/3"
TIGER = "Tiger King: Großkatzen und Verrückte: Nicht euer Durchschnitts-Joe"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Die Eiskönigin – Völlig unverfroren", "eiskoenigin voellig unverfroren"),
        ("The Godfather", "godfather"),
        ("Amélie", "amelie"),
        ("Der Pate", "pate"),
        ("Mission: Impossible", "mission impossible"),
        ("Ein Fisch namens Wanda", "fisch namens wanda"),
        ("Straße der Sehnsucht!", "strasse der sehnsucht"),
        ("  DAS   Boot ", "boot"),
        ("Le Mans '66", "mans 66"),
        ("Die", "die"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Inception (OmU)", "Inception"),
        ("Das Boot [4K UHD]", "Das Boot"),
        ("Der Pate (Original mit Untertiteln)", "Der Pate"),
        ("Toni Erdmann", "Toni Erdmann"),
        ("Soul (2020)", "Soul"),
    ],
)
def test_clean_query(raw: str, expected: str) -> None:
    assert clean_query(raw) == expected


def sr(
    tmdb_id: int, title: str, original: str, date: str | None, votes: int = 100, pop: float = 10.0
) -> SearchResult:
    return SearchResult(tmdb_id, title, original, date, popularity=pop, vote_count=votes)


def test_similarity_and_scores() -> None:
    assert title_similarity("Der Pate", "Der Pate") == pytest.approx(100.0)
    assert title_similarity("Der Pate", "The Godfather") < 60
    pate = sr(238, "Der Pate", "The Godfather", "1972-03-14", 21000, 120)
    assert score_candidate("Der Pate", None, pate) >= 95
    assert score_candidate("The Godfather", None, pate) >= 95
    assert score_candidate("Der Pate", 1972, pate) >= score_candidate("Der Pate", 1990, pate) + 10


def test_year_decides_between_remakes() -> None:
    old = sr(871, "Planet der Affen", "Planet of the Apes", "1968-02-07", 4000, 25)
    new = sr(869, "Planet der Affen", "Planet of the Apes", "2001-07-25", 4500, 30)
    best_2001 = choose_best("Planet der Affen", 2001, [old, new])
    best_1968 = choose_best("Planet der Affen", 1968, [new, old])
    assert best_2001 is not None and best_2001[0].tmdb_id == 869
    assert best_1968 is not None and best_1968[0].tmdb_id == 871
    # Without year, a watch date before 2001 rules out the remake.
    bounded = choose_best("Planet der Affen", None, [new, old], max_year=1995)
    assert bounded is not None and bounded[0].tmdb_id == 871


def test_choose_best_empty() -> None:
    assert choose_best("x", None, []) is None


def test_tv_results_are_ignored() -> None:
    tv = SearchResult(1, "Dark", "Dark", "2017-12-01", media_type="tv")
    assert choose_best("Dark", None, [tv]) is None


def client(**kw) -> TMDBClient:
    return TMDBClient(None, base_url=BASE, **kw)


def run(coro):
    return asyncio.run(coro)


@respx.mock
def test_match_german_title() -> None:
    respx.get(f"{BASE}/search/movie").mock(
        return_value=httpx.Response(200, json=load_json("search_der_pate.json"))
    )

    async def go():
        async with client() as c:
            return await match_title(c, "Der Pate")

    out = run(go())
    assert out.status == "matched"
    assert out.tmdb_id == 238
    assert out.score is not None and out.score >= 85


@respx.mock
def test_match_remake_by_year() -> None:
    respx.get(f"{BASE}/search/movie").mock(
        return_value=httpx.Response(200, json=load_json("search_planet_der_affen.json"))
    )

    async def go():
        async with client() as c:
            return await match_title(c, "Planet der Affen", year=1968), await match_title(
                c, "Planet der Affen", year=2001
            )

    a, b = run(go())
    assert (a.tmdb_id, b.tmdb_id) == (871, 869)


@respx.mock
def test_weak_match_is_unmatched() -> None:
    respx.get(f"{BASE}/search/movie").mock(
        return_value=httpx.Response(200, json=load_json("search_weak.json"))
    )

    async def go():
        async with client() as c:
            return await match_title(c, "Kurzer Clip")

    out = run(go())
    assert out.status == "unmatched"
    assert out.tmdb_id is None
    assert out.best_title == "Ein ganz anderer Film"
    assert out.score is not None and out.score < 85


@respx.mock
def test_ambiguous_series_title_is_ignored() -> None:
    respx.get(f"{BASE}/search/movie").mock(
        return_value=httpx.Response(200, json=load_json("search_tiger_king.json"))
    )

    async def go():
        async with client() as c:
            return await match_title(
                c,
                "Tiger King: Großkatzen und Verrückte: Nicht euer Durchschnitts-Joe",
                kind="ambiguous",
            )

    out = run(go())
    assert out.status == "series"
    assert out.tmdb_id is None


@respx.mock
def test_ambiguous_title_with_strong_movie_match_wins() -> None:
    route = respx.get(f"{BASE}/search/movie").mock(
        return_value=httpx.Response(200, json=load_json("search_star_wars.json"))
    )

    async def go():
        async with client() as c:
            return await match_title(
                c, "Star Wars: Episode IV: Eine neue Hoffnung", kind="ambiguous"
            )

    out = run(go())
    assert out.status == "matched"
    assert out.tmdb_id == 11
    assert route.called


@respx.mock
def test_search_results_marked_tv_are_skipped() -> None:
    payload = {
        "results": [
            {
                "id": 5,
                "title": "Dark",
                "original_title": "Dark",
                "release_date": "2017-12-01",
                "media_type": "tv",
            }
        ]
    }
    respx.get(f"{BASE}/search/movie").mock(return_value=httpx.Response(200, json=payload))

    async def go():
        async with client() as c:
            return await match_title(c, "Dark")

    assert run(go()).status == "unmatched"


@respx.mock
def test_cache_prevents_second_request(repo: Repository) -> None:
    route = respx.get(f"{BASE}/search/movie").mock(
        return_value=httpx.Response(200, json=load_json("search_der_pate.json"))
    )

    async def go():
        async with client(cache=repo) as c:
            first = await match_title(c, "Der Pate")
        async with client(cache=repo) as c:
            second = await match_title(c, "Der Pate")
        return first, second

    first, second = run(go())
    assert first.tmdb_id == second.tmdb_id == 238
    assert route.call_count == 1


@respx.mock
def test_match_pending(repo: Repository, ml_mini_dir: Path, tmp_path: Path) -> None:
    process_movielens(ml_mini_dir, tmp_path / "p", checksum="x")
    data = load_processed(tmp_path / "p")
    repo.upsert_movielens_films(
        MovieLensFilm(
            int(r.movieId),
            None if r.tmdbId is None or str(r.tmdbId) == "<NA>" else int(r.tmdbId),
            r.title,
            None,
            [],
            int(r["count"]),
            None,
            int(r.popularity_rank),
        )
        for _, r in data.movies.iterrows()
    )

    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params["query"]
        name = {
            "Der Pate": "search_der_pate.json",
            "Das Leben der Anderen": "search_leben_der_anderen.json",
            TIGER: "search_tiger_king.json",
        }.get(q, "search_weak.json")
        return httpx.Response(200, json=load_json(name))

    respx.get(f"{BASE}/search/movie").mock(side_effect=handler)
    for profile in ("Florian", "Kinder"):
        repo.upsert_watch_event(WatchEvent(source="netflix", profile=profile, raw_title="Der Pate"))
    repo.upsert_watch_event(
        WatchEvent(source="netflix", profile="Florian", raw_title="Das Leben der Anderen")
    )
    repo.upsert_watch_event(
        WatchEvent(source="netflix", profile="Florian", raw_title="Kurzer Clip")
    )
    repo.upsert_watch_event(
        WatchEvent(
            source="netflix",
            profile="Florian",
            raw_title=TIGER,
            kind="ambiguous",
        )
    )

    async def go():
        async with client(cache=repo) as c:
            return await match_pending(repo, c)

    stats = run(go())
    assert (stats.matched, stats.unmatched, stats.series) == (2, 1, 1)
    evs = {(e.profile, e.raw_title): e for e in repo.list_watch_events()}
    assert evs[("Florian", "Der Pate")].tmdb_id == 238
    assert evs[("Florian", "Der Pate")].movielens_id == 1
    assert evs[("Kinder", "Der Pate")].movielens_id == 1
    assert evs[("Florian", "Das Leben der Anderen")].movielens_id == 2
    assert [u.raw_title for u in repo.list_unmatched()] == ["Kurzer Clip"]
    assert repo.pending_titles() == []
    # Running again does nothing new.
    stats2 = run(go())
    assert (stats2.matched, stats2.unmatched, stats2.series) == (0, 0, 0)
