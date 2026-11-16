from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from conftest import rate_movielens
from filmzwilling.config import RecommenderConfig, Settings
from filmzwilling.filters import RecFilter
from filmzwilling.service import FilmService, ServiceError
from filmzwilling.synthetic import SyntheticDataset, synthetic_user_ratings


def test_sync_movielens_films_is_idempotent(
    service: FilmService, synthetic_ds: SyntheticDataset
) -> None:
    n = len(synthetic_ds.movies)
    assert service.repo.count_films() == n
    service.sync_movielens_films()
    assert service.repo.count_films() == n


def test_too_few_ratings_gives_hint(service: FilmService, florian_ratings: dict[int, int]) -> None:
    rate_movielens(service, dict(list(florian_ratings.items())[:29]))
    result = service.recommendations(RecFilter())
    assert result["status"] == "too_few_ratings"
    assert "30" in result["message"]
    assert result["items"] == []


def test_recompute_and_recommendations(
    service: FilmService, florian_ratings: dict[int, int], synthetic_ds: SyntheticDataset
) -> None:
    rate_movielens(service, florian_ratings)
    summary = service.recompute()
    assert summary["count"] > 0
    assert summary["rating_count"] == len(florian_ratings)
    result = service.recommendations(RecFilter())
    assert result["status"] == "ok"
    items = result["items"]
    assert items
    rated_films = {service.repo.film_id_for_movielens(m) for m in florian_ratings}
    assert not rated_films & {i["film_id"] for i in items}
    top_ml = [i["movielens_id"] for i in items[:10]]
    assert len(set(top_ml) & set(synthetic_ds.favorites[0])) >= 7
    first = items[0]
    for key in (
        "title",
        "year",
        "score",
        "score_text",
        "support",
        "reason",
        "offers",
        "genres",
        "runtime",
        "poster_url",
    ):
        assert key in first
    assert "," in first["score_text"]
    assert (
        first["reason"].endswith(first["score_text"].split()[0]) or "Zwillinge" in first["reason"]
    )


def test_not_interested_and_not_seen(service: FilmService, florian_ratings: dict[int, int]) -> None:
    rate_movielens(service, florian_ratings)
    service.recompute()
    items = service.recommendations(RecFilter())["items"]
    a, b = items[0]["film_id"], items[1]["film_id"]
    service.not_interested(a)
    service.not_seen(b)
    ids = {i["film_id"] for i in service.recommendations(RecFilter())["items"]}
    assert a not in ids
    assert b in ids
    service.recompute()
    ids = {i["film_id"] for i in service.recommendations(RecFilter())["items"]}
    assert a not in ids and b in ids


def test_rating_from_recommendations_removes_item(
    service: FilmService, florian_ratings: dict[int, int]
) -> None:
    rate_movielens(service, florian_ratings)
    service.recompute()
    first = service.recommendations(RecFilter())["items"][0]["film_id"]
    service.rate(first, 9, from_queue=False)
    assert first not in {i["film_id"] for i in service.recommendations(RecFilter())["items"]}
    assert service.undo() is None  # not a queue action


def test_provider_filter(service: FilmService, florian_ratings: dict[int, int]) -> None:
    rate_movielens(service, florian_ratings)
    service.recompute()
    res = service.recommendations(RecFilter(providers=frozenset({8})))
    assert res["items"]
    for item in res["items"]:
        assert any(
            o["provider_id"] == 8 and o["category"] in ("flatrate", "free", "ads")
            for o in item["offers"]
        )
    total_any = service.recommendations(RecFilter())["total"]
    assert res["total"] < total_any


def test_background_recompute_after_25_ratings(
    service: FilmService, synthetic_ds: SyntheticDataset
) -> None:
    ratings = synthetic_user_ratings(synthetic_ds, 2, n=80, seed=9)
    items = list(ratings.items())
    started = []
    for movie_id, note in items[:30]:
        started.append(service.rate(service.repo.film_id_for_movielens(movie_id), note))
    # The first automatic run starts once the minimum of 30 own ratings is reached.
    assert started[:29] == [False] * 29
    assert started[29] is True
    service.wait_for_background(timeout=30)
    assert service.repo.get_setting("recs_meta")["rating_count"] == 30
    started = []
    for movie_id, note in items[30:55]:
        started.append(service.rate(service.repo.film_id_for_movielens(movie_id), note))
    assert started[:-1] == [False] * 24
    assert started[-1] is True
    service.wait_for_background(timeout=30)
    meta = service.repo.get_setting("recs_meta")
    assert meta["rating_count"] == 55


def test_queue_items_and_actions(service: FilmService) -> None:
    items = service.queue_items(limit=20)
    assert len(items) == 20
    first = items[0]
    for key in (
        "film_id",
        "title",
        "original_title",
        "year",
        "runtime",
        "genres",
        "poster_url",
        "hints",
        "highlight_low",
        "source",
    ):
        assert key in first
    service.rate(first["film_id"], 8)
    service.not_seen(items[1]["film_id"])
    service.later(items[2]["film_id"])
    new = service.queue_items(limit=20)
    assert new[0]["film_id"] == items[3]["film_id"]
    progress = service.progress()
    assert (progress.rated, progress.not_seen) == (1, 1)
    undone = service.undo()
    assert undone is not None
    assert (undone["action"], undone["film_id"]) == ("later", items[2]["film_id"])
    assert undone["item"]["film_id"] == items[2]["film_id"]
    service.undo()
    service.undo()
    assert service.queue_items(limit=1)[0]["film_id"] == first["film_id"]
    assert service.undo() is None


def test_queue_offset(service: FilmService) -> None:
    a = service.queue_items(limit=10)
    b = service.queue_items(limit=10, offset=5)
    assert [x["film_id"] for x in a[5:]] == [x["film_id"] for x in b[:5]]


def test_rate_validation(service: FilmService) -> None:
    fid = service.queue_items(limit=1)[0]["film_id"]
    with pytest.raises(ValueError):
        service.rate(fid, 11)
    with pytest.raises(KeyError):
        service.rate(10**9, 5)


def test_twins(service: FilmService, florian_ratings: dict[int, int]) -> None:
    assert service.twins() == []
    rate_movielens(service, florian_ratings)
    service.recompute()
    twins = service.twins()
    assert len(twins) == 20
    assert twins[0]["similarity"] >= twins[-1]["similarity"]
    for t in twins:
        assert t["label"].startswith("Zwilling ")
        assert t["overlap"] >= 10
        assert len(t["top_movies"]) == 3
        for m in t["top_movies"]:
            assert {"title", "your_score", "their_score"} <= set(m)


def test_evaluate_is_stored(service: FilmService, synthetic_ds: SyntheticDataset) -> None:
    ratings = synthetic_user_ratings(synthetic_ds, 1, n=100, seed=2, include_favorites=True)
    rate_movielens(service, ratings)
    result = service.evaluate()
    assert result.rmse < result.baseline_rmse
    stored = service.repo.get_setting("evaluation")
    assert stored["rmse"] == pytest.approx(result.rmse)
    assert "evaluated_at" in stored


def test_evaluate_needs_ratings(service: FilmService) -> None:
    with pytest.raises(ServiceError):
        service.evaluate()


def test_check_title(service: FilmService, synthetic_ds: SyntheticDataset) -> None:
    title = str(synthetic_ds.movies.iloc[0].title)
    name, year = title.rsplit(" (", 1)
    res = service.check_title(name, int(year.rstrip(")")))
    assert res.found
    assert res.movielens_id == 1
    assert res.rating_count is not None and res.rating_count > 0
    assert res.popularity_rank is not None and res.total_movies == len(synthetic_ds.movies)
    assert res.queue_position is not None or res.note
    missing = service.check_title("Gibt es wirklich nicht xyz")
    assert not missing.found


def test_top_recommendations(service: FilmService, florian_ratings: dict[int, int]) -> None:
    rate_movielens(service, florian_ratings)
    top = service.top_recommendations(5)
    assert len(top) == 5
    assert top == sorted(top, key=lambda x: -x["score"])


def test_offline_tmdb_is_none(service: FilmService) -> None:
    assert service.tmdb() is None
    with pytest.raises(ServiceError):
        asyncio.run(service.search_tmdb("Inception"))


def test_import_file_offline(service: FilmService, fixtures_dir: Path) -> None:
    report = service.import_file("netflix", fixtures_dir / "netflix" / "CONTENT_INTERACTION")
    assert report.inserted == 10
    assert any("TMDB" in n for n in report.notes)
    report = service.import_file("csv", fixtures_dir / "csv" / "disney.csv")
    assert report.inserted == 5
    report = service.import_file(
        "prime",
        fixtures_dir / "prime" / "custom.csv",
        mapping=fixtures_dir / "prime" / "mapping.toml",
    )
    assert report.inserted == 2
    with pytest.raises(ValueError):
        service.import_file("vhs", fixtures_dir / "csv" / "disney.csv")


def test_service_without_data(tmp_path: Path) -> None:
    svc = FilmService(Settings(data_dir=tmp_path, offline=True))
    assert svc.data() is None
    with pytest.raises(ServiceError):
        svc.require_data()
    with pytest.raises(ServiceError):
        svc.recompute()
    assert svc.recommendations(RecFilter())["status"] in ("no_data", "too_few_ratings")


def test_online_matching_and_metadata(online_service: FilmService, fixtures_dir: Path) -> None:
    report = online_service.import_file(
        "netflix", fixtures_dir / "netflix" / "NetflixViewingHistory.csv", profile="Florian"
    )
    assert report.matched >= 2
    events = {e.raw_title: e for e in online_service.repo.list_watch_events()}
    assert events["Inception"].tmdb_id == 27205
    assert events["Das Leben der Anderen"].tmdb_id == 582
    film = online_service.repo.get_film(online_service.repo.film_id_for_tmdb(27205))
    assert film is not None and film.runtime == 148
    assert any(
        u.raw_title == "Mission: Impossible – Fallout" for u in online_service.repo.list_unmatched()
    )


def test_online_providers_and_new_releases(online_service: FilmService) -> None:
    providers = asyncio.run(online_service.refresh_providers())
    assert len(providers) == 15
    assert set(online_service.default_provider_ids()) >= {8, 9, 337}
    n = asyncio.run(online_service.refresh_new_releases())
    assert n == 3
    items = online_service.new_release_items(RecFilter(providers=frozenset({337})))
    assert [i["title"] for i in items] == ["Alles steht Kopf 2"]
    all_items = online_service.new_release_items(RecFilter())
    assert [i["title"] for i in all_items] == [
        "Der wilde Roboter",
        "Oppenheimer",
        "Alles steht Kopf 2",
    ]
    assert all(i["personalized"] is False for i in all_items)


def test_online_availability(online_service: FilmService, synthetic_ds: SyntheticDataset) -> None:
    rate_movielens(online_service, synthetic_user_ratings(synthetic_ds, 0, n=40, seed=5))
    online_service.recompute()
    updated = asyncio.run(online_service.refresh_availability(limit=10))
    assert updated == 10


def test_online_search_and_resolve(online_service: FilmService) -> None:
    results = asyncio.run(online_service.search_tmdb("Inception"))
    assert results[0]["tmdb_id"] == 27205
    assert results[0]["year"] == 2010
    online_service.repo.upsert_watch_event(
        __import__("filmzwilling.importers.common", fromlist=["WatchEvent"]).WatchEvent(
            source="csv", profile="Florian", raw_title="Inzeption"
        )
    )
    uid = online_service.repo.add_unmatched(
        "Inzeption", source="csv", year=None, best_score=50, best_title=None
    )
    film_id = asyncio.run(online_service.resolve_unmatched(uid, 27205))
    assert online_service.repo.get_film(film_id).title == "Inception"  # type: ignore[union-attr]


def test_sync_queue_metadata(online_service: FilmService) -> None:
    n = asyncio.run(online_service.sync_queue_metadata(limit=5))
    assert n >= 0


def test_config_is_used(
    offline_settings: Settings, synthetic_data, synthetic_ds: SyntheticDataset, florian_ratings
) -> None:
    svc = FilmService(
        offline_settings, data=synthetic_data, config=RecommenderConfig(min_support=1000)
    )
    svc.sync_movielens_films()
    rate_movielens(svc, florian_ratings)
    assert svc.recompute()["count"] == 0


def test_availability_also_fetches_missing_metadata(
    tmp_path: Path, synthetic_data, synthetic_ds: SyntheticDataset
) -> None:
    import httpx

    from conftest import load_json, tmdb_fixture_handler

    template = load_json("movie_27205.json")
    extra: dict[str, object] = {}
    for tmdb_id in synthetic_ds.links["tmdbId"].dropna():
        payload = dict(template)
        payload.update(
            {"id": int(tmdb_id), "title": f"Deutscher Titel {int(tmdb_id)}", "runtime": 99}
        )
        extra[f"/movie/{int(tmdb_id)}"] = payload
    settings = Settings(data_dir=tmp_path / "meta", offline=False)
    svc = FilmService(
        settings, data=synthetic_data, transport=httpx.MockTransport(tmdb_fixture_handler(extra))
    )
    svc.sync_movielens_films()
    rate_movielens(svc, synthetic_user_ratings(synthetic_ds, 0, n=40, seed=5))
    svc.recompute()
    svc.wait_for_background(timeout=60)  # the availability refresh starts after recompute
    top = svc.recommendations(RecFilter(providers=frozenset({8})), limit=5)["items"]
    assert top, "films with Netflix offers expected after the background refresh"
    for item in top:
        assert item["title"].startswith("Deutscher Titel")
        assert item["runtime"] == 99
        assert item["poster_url"].startswith("https://image.tmdb.org/")
    assert asyncio.run(svc.refresh_availability(limit=5, force=False)) == 0  # all fresh now
