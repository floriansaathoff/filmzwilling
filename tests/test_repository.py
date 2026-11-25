from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from filmzwilling.importers.common import WatchEvent
from filmzwilling.repository import (
    MovieLensFilm,
    Repository,
    StoredRecommendation,
    StoredTwin,
)
from filmzwilling.tmdb import MovieDetails, Provider, ProviderOffer


def ml_films(n: int = 5) -> list[MovieLensFilm]:
    return [
        MovieLensFilm(
            movielens_id=i,
            tmdb_id=1000 + i if i != 4 else None,
            title=f"Film {i}, The" if i == 1 else f"Film {i}",
            year=2000 + i,
            genres=["Comedy", "Sci-Fi"] if i == 1 else ["Drama"],
            count=100 - i,
            mean=3.5,
            popularity_rank=i,
        )
        for i in range(1, n + 1)
    ]


def details(
    tmdb_id: int, title: str = "Deutscher Titel", runtime: int | None = 100
) -> MovieDetails:
    return MovieDetails(
        tmdb_id=tmdb_id,
        title=title,
        original_title="Original",
        runtime=runtime,
        genres=["Drama", "Krimi"],
        poster_path="/p.jpg",
        vote_average=7.5,
        vote_count=1000,
        release_date="2001-02-03",
        popularity=10.0,
        offers=[ProviderOffer(8, "Netflix", "/n.jpg", "flatrate", 0)],
    )


def test_settings_roundtrip(repo: Repository) -> None:
    assert repo.get_setting("missing", 42) == 42
    repo.set_setting("complex", {"a": [1, 2], "b": None})
    assert repo.get_setting("complex") == {"a": [1, 2], "b": None}
    repo.set_setting("complex", "replaced")
    assert repo.get_setting("complex") == "replaced"


def test_user_settings_defaults_and_update(repo: Repository) -> None:
    s = repo.get_user_settings()
    assert s.my_profiles == []
    assert s.my_providers is None
    assert s.queue_size == 1000
    s = repo.update_user_settings(my_profiles=["Florian"], my_providers=[8, 9], queue_size=500)
    assert (s.my_profiles, s.my_providers, s.queue_size) == (["Florian"], [8, 9], 500)
    s = repo.update_user_settings(queue_size=200)
    assert s.my_profiles == ["Florian"]
    assert s.queue_size == 200
    with pytest.raises(ValueError):
        repo.update_user_settings(queue_size=-1)
    assert s.excluded_genres == []
    s = repo.update_user_settings(excluded_genres=["Horror", "Western"])
    assert s.excluded_genres == ["Horror", "Western"]
    assert s.queue_size == 200


def test_movielens_films_and_display(repo: Repository) -> None:
    assert repo.upsert_movielens_films(ml_films()) == 5
    assert repo.count_films() == 5
    fid = repo.film_id_for_movielens(1)
    assert fid is not None
    film = repo.get_film(fid)
    assert film is not None
    assert film.display_title == "The Film 1"
    assert film.display_year == 2001
    assert film.display_genres == ["Komödie", "Science Fiction"]
    assert repo.film_id_for_tmdb(1001) == fid
    # idempotent
    assert repo.upsert_movielens_films(ml_films()) == 5
    assert repo.count_films() == 5
    assert repo.movielens_film_map()[3] == repo.film_id_for_movielens(3)


def test_tmdb_details_merge_into_movielens_film(repo: Repository) -> None:
    repo.upsert_movielens_films(ml_films())
    fid = repo.upsert_tmdb_details(details(1001))
    assert fid == repo.film_id_for_movielens(1)
    film = repo.get_film(fid)
    assert film is not None
    assert film.display_title == "Deutscher Titel"
    assert film.display_genres == ["Drama", "Krimi"]
    assert film.runtime == 100
    assert film.meta_fetched_at is not None
    new_id = repo.upsert_tmdb_details(details(5555, "Neu"))
    assert new_id != fid
    assert repo.get_film(new_id).movielens_id is None  # type: ignore[union-attr]


def test_tmdb_film_first_then_movielens(repo: Repository) -> None:
    fid = repo.upsert_tmdb_details(details(1002, "Zuerst TMDB"))
    repo.upsert_movielens_films(ml_films())
    assert repo.film_id_for_movielens(2) == fid
    assert repo.count_films() == 5


def test_offers(repo: Repository) -> None:
    repo.upsert_providers([Provider(8, "Netflix", "/n.jpg", 0), Provider(2, "Apple TV", None, 3)])
    assert [p.name for p in repo.list_providers()] == ["Netflix", "Apple TV"]
    fid = repo.upsert_tmdb_details(details(1))
    repo.set_film_offers(
        fid,
        [
            ProviderOffer(8, "Netflix", "/n.jpg", "flatrate"),
            ProviderOffer(2, "Apple TV", None, "rent"),
        ],
    )
    offers = repo.film_offers([fid])[fid]
    assert {(o.provider_id, o.category) for o in offers} == {(8, "flatrate"), (2, "rent")}
    repo.set_film_offers(fid, [])
    assert repo.film_offers([fid]).get(fid, []) == []
    assert repo.get_film(fid).providers_fetched_at is not None  # type: ignore[union-attr]


def test_missing_metadata_and_offers(repo: Repository) -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    r = Repository(repo.db, clock=lambda: now)
    r.upsert_movielens_films(ml_films())
    ids = [r.film_id_for_movielens(i) for i in range(1, 6)]
    # Film 4 has no tmdb_id: there is nothing to fetch for it.
    fetchable = set(ids) - {r.film_id_for_movielens(4)}
    assert set(r.films_missing_metadata(ids)) == fetchable
    fid = r.upsert_tmdb_details(details(1001), fetched_at=now - timedelta(days=10))
    r.set_film_offers(fid, [], fetched_at=now - timedelta(days=10))
    assert fid not in r.films_missing_metadata(ids)
    assert fid in r.films_missing_offers(ids)
    r.upsert_tmdb_details(details(1002), fetched_at=now - timedelta(days=31))
    assert r.film_id_for_tmdb(1002) in r.films_missing_metadata(ids)


def test_popular_film_ids(repo: Repository) -> None:
    repo.upsert_movielens_films(ml_films())
    ids = repo.popular_film_ids(10)
    expected = [repo.film_id_for_movielens(i) for i in (1, 2, 3, 5)]  # 4 has no tmdb id
    assert ids == expected
    assert repo.popular_film_ids(2) == expected[:2]
    tmdb_only = repo.upsert_tmdb_details(details(9999))
    assert tmdb_only not in repo.popular_film_ids(10)


def test_ratings(repo: Repository) -> None:
    repo.upsert_movielens_films(ml_films())
    fid = repo.film_id_for_movielens(1)
    repo.set_rating(fid, 7)
    assert repo.get_rating(fid) == 7
    repo.set_rating(fid, 9)
    assert repo.get_rating(fid) == 9
    assert repo.count_ratings() == 1
    for bad in (11, -1, 7.5, "5"):
        with pytest.raises(ValueError):
            repo.set_rating(fid, bad)  # type: ignore[arg-type]
    with pytest.raises(KeyError):
        repo.set_rating(123456, 5)
    tmdb_only = repo.upsert_tmdb_details(details(9999, "Nur TMDB"))
    repo.set_rating(tmdb_only, 4)
    assert repo.ratings_for_cf() == {1: 9}
    listed = repo.list_ratings()
    assert {r["film_id"] for r in listed} == {fid, tmdb_only}
    assert [r["title"] for r in repo.list_ratings("nur")] == ["Nur TMDB"]
    assert repo.delete_rating(fid) is True
    assert repo.delete_rating(fid) is False
    assert repo.get_rating(fid) is None


def test_statuses_and_rating_clears_not_seen(repo: Repository) -> None:
    repo.upsert_movielens_films(ml_films())
    a, b = repo.film_id_for_movielens(1), repo.film_id_for_movielens(2)
    repo.mark_not_seen(a)
    repo.mark_not_interested(b)
    assert repo.statuses() == {a: "not_seen", b: "not_interested"}
    assert repo.count_status("not_seen") == 1
    repo.set_rating(a, 5)
    assert a not in repo.statuses()
    assert repo.rated_film_ids() == {a}


def test_undo_stack(repo: Repository) -> None:
    repo.upsert_movielens_films(ml_films())
    a, b, c = (repo.film_id_for_movielens(i) for i in (1, 2, 3))
    assert repo.undo_last() is None
    repo.set_rating(a, 6)
    repo.set_rating(a, 8)
    repo.mark_not_seen(b)
    repo.defer(c)
    repo.defer(c)
    assert repo.undo_last() == {"action": "later", "film_id": c}
    assert c in repo.deferred_order()
    assert repo.undo_last() == {"action": "later", "film_id": c}
    assert c not in repo.deferred_order()
    assert repo.undo_last() == {"action": "not_seen", "film_id": b}
    assert b not in repo.statuses()
    assert repo.undo_last() == {"action": "rate", "film_id": a}
    assert repo.get_rating(a) == 6
    assert repo.undo_last() == {"action": "rate", "film_id": a}
    assert repo.get_rating(a) is None
    assert repo.undo_last() is None


def test_undo_restores_not_seen_after_rating(repo: Repository) -> None:
    repo.upsert_movielens_films(ml_films())
    a = repo.film_id_for_movielens(1)
    repo.mark_not_seen(a)
    repo.set_rating(a, 3)
    repo.undo_last()
    assert repo.statuses() == {a: "not_seen"}
    assert repo.get_rating(a) is None


def test_unlogged_actions_are_not_undone(repo: Repository) -> None:
    repo.upsert_movielens_films(ml_films())
    a = repo.film_id_for_movielens(1)
    repo.set_rating(a, 3, log_action=False)
    assert repo.undo_last() is None
    assert repo.get_rating(a) == 3


def test_deferred_order(repo: Repository) -> None:
    repo.upsert_movielens_films(ml_films())
    a, b = repo.film_id_for_movielens(1), repo.film_id_for_movielens(2)
    repo.defer(a)
    repo.defer(b)
    order = repo.deferred_order()
    assert order[a] < order[b]
    repo.defer(a)
    order = repo.deferred_order()
    assert order[a] > order[b]


def event(**kw) -> WatchEvent:
    base = dict(
        source="netflix",
        profile="Florian",
        raw_title="Der Pate",
        first_seen=datetime(2024, 1, 1, 20, 0),
        last_seen=datetime(2024, 1, 2, 20, 0),
        total_watch_seconds=3600,
        max_position_seconds=3500,
        sessions=2,
    )
    base.update(kw)
    return WatchEvent(**base)  # type: ignore[arg-type]


def test_watch_event_upsert_is_idempotent(repo: Repository) -> None:
    assert repo.upsert_watch_event(event()) == "inserted"
    assert repo.upsert_watch_event(event()) == "unchanged"
    assert repo.upsert_watch_event(event(sessions=3, total_watch_seconds=5000)) == "updated"
    assert repo.count_watch_events() == 1
    repo.upsert_watch_event(event(profile="Kinder"))
    assert repo.profiles() == ["Florian", "Kinder"]
    stored = {e.profile: e for e in repo.list_watch_events()}
    assert stored["Florian"].sessions == 3
    assert stored["Florian"].total_watch_seconds == 5000
    assert stored["Florian"].first_seen.startswith("2024-01-01")  # type: ignore[union-attr]


def test_hints_merge(repo: Repository) -> None:
    repo.upsert_watch_event(event())
    repo.merge_event_hints("netflix", "Florian", "Der Pate", {"netflix_thumbs": "up"})
    repo.upsert_watch_event(event())  # re-import keeps hints
    stored = repo.list_watch_events()[0]
    assert stored.hints["netflix_thumbs"] == "up"
    repo.merge_event_hints("netflix", "Florian", "Neuer Titel", {"netflix_thumbs": "down"})
    titles = {e.raw_title: e for e in repo.list_watch_events()}
    assert titles["Neuer Titel"].sessions == 0
    assert titles["Neuer Titel"].hints == {"netflix_thumbs": "down"}


def test_pending_assign_and_unmatched(repo: Repository) -> None:
    repo.upsert_movielens_films(ml_films())
    repo.upsert_watch_event(event())
    repo.upsert_watch_event(event(profile="Kinder"))
    repo.upsert_watch_event(event(raw_title="Unbekannt", year=1999))
    repo.upsert_watch_event(event(raw_title="Serie: Etwas: Anderes", kind="ambiguous"))
    pending = {p["raw_title"]: p for p in repo.pending_titles()}
    assert set(pending) == {"Der Pate", "Unbekannt", "Serie: Etwas: Anderes"}
    assert pending["Unbekannt"]["year"] == 1999
    assert pending["Serie: Etwas: Anderes"]["kind"] == "ambiguous"
    assert repo.assign_title("Der Pate", 1001) == 2
    for e in repo.list_watch_events():
        if e.raw_title == "Der Pate":
            assert e.tmdb_id == 1001 and e.movielens_id == 1
    repo.mark_title_series("Serie: Etwas: Anderes")
    uid = repo.add_unmatched(
        "Unbekannt", source="netflix", year=1999, best_score=40.0, best_title="X"
    )
    assert {p["raw_title"] for p in repo.pending_titles()} == set()
    assert (
        repo.add_unmatched(
            "Unbekannt", source="netflix", year=1999, best_score=41.0, best_title="Y"
        )
        == uid
    )
    items = repo.list_unmatched()
    assert [u.raw_title for u in items] == ["Unbekannt"]
    assert items[0].profiles == ["Florian"]
    assert repo.resolve_unmatched(uid, 1002) == 1
    assert repo.list_unmatched() == []
    assert repo.get_unmatched(uid).status == "resolved"  # type: ignore[union-attr]
    assert any(e.tmdb_id == 1002 for e in repo.list_watch_events())


def test_ignore_unmatched(repo: Repository) -> None:
    repo.upsert_watch_event(event(raw_title="Quatsch"))
    uid = repo.add_unmatched(
        "Quatsch", source="netflix", year=None, best_score=None, best_title=None
    )
    repo.ignore_unmatched(uid)
    assert repo.list_unmatched() == []
    assert [u.raw_title for u in repo.list_unmatched("ignored")] == ["Quatsch"]
    assert repo.pending_titles() == []


def test_relink_movielens_ids(repo: Repository) -> None:
    repo.upsert_watch_event(event())
    repo.assign_title("Der Pate", 1003)
    assert repo.list_watch_events()[0].movielens_id is None
    repo.upsert_movielens_films(ml_films())
    assert repo.relink_movielens_ids() == 1
    assert repo.list_watch_events()[0].movielens_id == 3


def test_recommendations_and_twins(repo: Repository) -> None:
    repo.upsert_movielens_films(ml_films())
    recs = [
        StoredRecommendation(
            movielens_id=2,
            film_id=repo.film_id_for_movielens(2),
            score=8.1,
            support=20,
            twin_mean=8.3,
            rank=1,
        ),
        StoredRecommendation(
            movielens_id=3,
            film_id=repo.film_id_for_movielens(3),
            score=7.0,
            support=9,
            twin_mean=6.9,
            rank=2,
        ),
    ]
    repo.save_recommendations(recs, {"rating_count": 31})
    assert repo.load_recommendations() == recs
    assert repo.get_setting("recs_meta")["rating_count"] == 31
    repo.save_recommendations(recs[:1], {"rating_count": 40})
    assert repo.load_recommendations() == recs[:1]
    twins = [
        StoredTwin(rank=1, ml_user_id=77, similarity=0.5, overlap=30, top_movies=[{"title": "A"}])
    ]
    repo.save_twins(twins)
    assert repo.load_twins() == twins
    repo.save_new_releases([repo.film_id_for_movielens(5), repo.film_id_for_movielens(1)])
    assert repo.list_new_releases() == [
        repo.film_id_for_movielens(5),
        repo.film_id_for_movielens(1),
    ]


def test_cache(repo: Repository) -> None:
    assert repo.cache_get("k") is None
    t = datetime(2026, 1, 1, tzinfo=UTC)
    repo.cache_put("k", {"x": 1}, fetched_at=t)
    payload, fetched = repo.cache_get("k")  # type: ignore[misc]
    assert payload == {"x": 1}
    assert fetched == t
    repo.cache_put("k", [1, 2])
    assert repo.cache_get("k")[0] == [1, 2]  # type: ignore[index]


def test_search_films(repo: Repository) -> None:
    repo.upsert_movielens_films(ml_films())
    repo.upsert_tmdb_details(details(1002, "Das große Abenteuer"))
    assert [f.display_title for f in repo.search_films("große")] == ["Das große Abenteuer"]
    assert len(repo.search_films("film")) >= 3
