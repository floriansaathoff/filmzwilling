from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from conftest import rate_movielens
from filmzwilling.importers.common import WatchEvent
from filmzwilling.service import FilmService
from filmzwilling.web.app import create_app


@pytest.fixture
def client(service: FilmService) -> TestClient:
    return TestClient(create_app(service))


@pytest.fixture
def online_client(online_service: FilmService) -> TestClient:
    return TestClient(create_app(online_service))


def rated_client(service: FilmService, ratings: dict[int, int]) -> TestClient:
    rate_movielens(service, ratings)
    service.recompute()
    return TestClient(create_app(service))


def test_queue(client: TestClient) -> None:
    r = client.get("/api/queue", params={"limit": 20})
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 20
    item = body["items"][0]
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
    ):
        assert key in item
    assert body["progress"]["remaining"] == body["progress"]["total"]
    r2 = client.get("/api/queue", params={"limit": 5, "offset": 2})
    assert [i["film_id"] for i in r2.json()["items"]] == [i["film_id"] for i in body["items"][2:7]]
    assert client.get("/api/queue", params={"limit": 0}).status_code == 422
    assert client.get("/api/queue", params={"limit": 500}).status_code == 422


def test_rate_validation(client: TestClient) -> None:
    fid = client.get("/api/queue").json()["items"][0]["film_id"]
    assert client.post("/api/rate", json={"film_id": fid, "score": 11}).status_code == 422
    assert client.post("/api/rate", json={"film_id": fid, "score": -1}).status_code == 422
    assert client.post("/api/rate", json={"film_id": fid, "score": 7.5}).status_code == 422
    assert client.post("/api/rate", json={"film_id": fid}).status_code == 422
    assert client.post("/api/rate", json={"film_id": 10**9, "score": 5}).status_code == 404
    r = client.post("/api/rate", json={"film_id": fid, "score": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["progress"]["rated"] == 1
    assert "recompute_started" in body


def test_actions_progress_and_undo(client: TestClient) -> None:
    items = client.get("/api/queue").json()["items"]
    a, b, c = (i["film_id"] for i in items[:3])
    assert client.post("/api/rate", json={"film_id": a, "score": 7}).status_code == 200
    assert client.post("/api/not-seen", json={"film_id": b}).status_code == 200
    assert client.post("/api/later", json={"film_id": c}).status_code == 200
    progress = client.get("/api/progress").json()
    assert (progress["rated"], progress["not_seen"]) == (1, 1)
    queue = [i["film_id"] for i in client.get("/api/queue", params={"limit": 100}).json()["items"]]
    assert a not in queue and b not in queue
    assert queue[0] == items[3]["film_id"]
    r = client.post("/api/undo")
    assert r.status_code == 200
    assert r.json()["undone"]["action"] == "later"
    assert r.json()["item"]["film_id"] == c
    assert client.post("/api/undo").json()["undone"] == {"action": "not_seen", "film_id": b}
    assert client.post("/api/undo").json()["undone"] == {"action": "rate", "film_id": a}
    r = client.post("/api/undo")
    assert r.status_code == 404
    assert "Rückgängig" in r.json()["detail"]
    assert client.get("/api/progress").json()["rated"] == 0
    assert client.post("/api/not-seen", json={"film_id": 10**9}).status_code == 404


def test_recommendations_need_30_ratings(
    client: TestClient, service: FilmService, florian_ratings: dict[int, int]
) -> None:
    body = client.get("/api/recommendations").json()
    assert body["status"] == "too_few_ratings"
    assert body["items"] == []
    assert "30" in body["message"]


def test_recommendations_with_filters(
    service: FilmService, florian_ratings: dict[int, int]
) -> None:
    client = rated_client(service, florian_ratings)
    body = client.get("/api/recommendations").json()
    assert body["status"] == "ok"
    assert body["items"]
    assert body["computed_at"]
    scores = [i["score"] for i in body["items"]]
    assert scores == sorted(scores, reverse=True)

    only_netflix = client.get("/api/recommendations", params={"providers": "8"}).json()["items"]
    assert only_netflix
    assert all(any(o["provider_id"] == 8 for o in i["offers"]) for i in only_netflix)

    rent = client.get("/api/recommendations", params={"providers": "2"}).json()["items"]
    assert rent == []
    rent = client.get("/api/recommendations", params={"providers": "2", "rent_buy": "1"}).json()[
        "items"
    ]
    assert rent and all(any(o["provider_id"] == 2 for o in i["offers"]) for i in rent)

    drama = client.get(
        "/api/recommendations", params={"providers": "any", "genres": "Drama"}
    ).json()["items"]
    assert drama and all("Drama" in i["genres"] for i in drama)

    no_drama = client.get(
        "/api/recommendations", params={"providers": "any", "exclude_genres": "Drama"}
    ).json()
    assert no_drama["items"] and all("Drama" not in i["genres"] for i in no_drama["items"])
    assert no_drama["filter"]["exclude_genres"] == "Drama"
    service.repo.update_user_settings(excluded_genres=["Drama"])
    saved = client.get("/api/recommendations", params={"providers": "any"}).json()["items"]
    assert [i["film_id"] for i in saved] == [i["film_id"] for i in no_drama["items"]]
    override = client.get(
        "/api/recommendations", params={"providers": "any", "exclude_genres": ""}
    ).json()["items"]
    assert any("Drama" in i["genres"] for i in override)
    service.repo.update_user_settings(excluded_genres=[])

    high = client.get("/api/recommendations", params={"providers": "any", "min_score": "8"}).json()[
        "items"
    ]
    assert all(i["score"] >= 8 for i in high)

    many = client.get(
        "/api/recommendations", params={"providers": "any", "min_support": "30"}
    ).json()["items"]
    assert all(i["support"] >= 30 for i in many)

    by_year = client.get(
        "/api/recommendations", params={"providers": "any", "sort": "year"}
    ).json()["items"]
    years = [i["year"] for i in by_year]
    assert years == sorted(years, reverse=True)

    window = client.get(
        "/api/recommendations",
        params={"providers": "any", "year_from": "1980", "year_to": "1990", "max_runtime": "120"},
    ).json()
    assert all(1980 <= i["year"] <= 1990 and i["runtime"] <= 120 for i in window["items"])
    assert window["filter"]["year_from"] == "1980"


def test_recommendation_actions(service: FilmService, florian_ratings: dict[int, int]) -> None:
    client = rated_client(service, florian_ratings)
    items = client.get("/api/recommendations", params={"providers": "any"}).json()["items"]
    a, b = items[0]["film_id"], items[1]["film_id"]
    assert client.post("/api/not-interested", json={"film_id": a}).status_code == 200
    assert (
        client.post(
            "/api/rate", json={"film_id": b, "score": 9, "context": "recommendations"}
        ).status_code
        == 200
    )
    ids = {
        i["film_id"]
        for i in client.get("/api/recommendations", params={"providers": "any"}).json()["items"]
    }
    assert a not in ids and b not in ids
    assert (
        client.post("/api/undo").status_code == 404
    )  # recommendation ratings are not queue actions


def test_recompute_endpoint(service: FilmService, florian_ratings: dict[int, int]) -> None:
    rate_movielens(service, florian_ratings)
    client = TestClient(create_app(service))
    r = client.post("/api/recompute")
    assert r.status_code == 200
    assert r.json()["count"] > 0
    assert client.get("/api/recommendations").json()["status"] == "ok"


def test_recompute_without_data(tmp_path) -> None:
    from filmzwilling.config import Settings

    svc = FilmService(Settings(data_dir=tmp_path, offline=True))
    client = TestClient(create_app(svc))
    r = client.post("/api/recompute")
    assert r.status_code == 409
    assert "setup" in r.json()["detail"]


def test_new_releases_offline(client: TestClient) -> None:
    body = client.get("/api/new-releases").json()
    assert body["personalized"] is False
    assert body["items"] == []


def test_new_releases_online(online_client: TestClient, online_service: FilmService) -> None:
    assert online_client.post("/api/new-releases/refresh").status_code == 200
    body = online_client.get("/api/new-releases", params={"providers": "any"}).json()
    assert [i["title"] for i in body["items"]] == [
        "Der wilde Roboter",
        "Oppenheimer",
        "Alles steht Kopf 2",
    ]
    assert body["personalized"] is False


def test_availability_refresh(client: TestClient, online_client: TestClient) -> None:
    r = client.post("/api/availability/refresh")
    assert r.status_code == 503
    assert "TMDB" in r.json()["detail"]
    assert online_client.post("/api/availability/refresh").status_code == 200


def test_my_ratings(client: TestClient) -> None:
    items = client.get("/api/queue").json()["items"]
    for i, item in enumerate(items[:3]):
        client.post("/api/rate", json={"film_id": item["film_id"], "score": i + 5})
    listed = client.get("/api/ratings").json()["items"]
    assert len(listed) == 3
    target = listed[0]
    q = client.get("/api/ratings", params={"q": target["title"][:6]}).json()["items"]
    assert target["film_id"] in {x["film_id"] for x in q}
    assert client.put(f"/api/ratings/{target['film_id']}", json={"score": 11}).status_code == 422
    assert client.put(f"/api/ratings/{target['film_id']}", json={"score": 2}).status_code == 200
    updated = {x["film_id"]: x["score"] for x in client.get("/api/ratings").json()["items"]}
    assert updated[target["film_id"]] == 2
    assert client.put("/api/ratings/999999999", json={"score": 2}).status_code == 404
    assert client.delete(f"/api/ratings/{target['film_id']}").status_code == 200
    assert client.delete(f"/api/ratings/{target['film_id']}").status_code == 404
    assert len(client.get("/api/ratings").json()["items"]) == 2


def test_csv_export(client: TestClient) -> None:
    fid = client.get("/api/queue").json()["items"][0]["film_id"]
    client.post("/api/rate", json={"film_id": fid, "score": 6})
    r = client.get("/api/ratings/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 1 and rows[0]["score"] == "6"


def test_unmatched_offline(client: TestClient, service: FilmService) -> None:
    service.repo.upsert_watch_event(
        WatchEvent(source="netflix", profile="Florian", raw_title="Unbekannter Film")
    )
    uid = service.repo.add_unmatched(
        "Unbekannter Film", source="netflix", year=None, best_score=42.0, best_title="Irgendwas"
    )
    items = client.get("/api/unmatched").json()["items"]
    assert [(i["id"], i["raw_title"], i["best_title"]) for i in items] == [
        (uid, "Unbekannter Film", "Irgendwas")
    ]
    assert items[0]["profiles"] == ["Florian"]
    r = client.get("/api/tmdb/search", params={"q": "Inception"})
    assert r.status_code == 503
    assert client.post(f"/api/unmatched/{uid}/ignore").status_code == 200
    assert client.get("/api/unmatched").json()["items"] == []
    assert client.post("/api/unmatched/99999/ignore").status_code == 404


def test_unmatched_resolve_online(online_client: TestClient, online_service: FilmService) -> None:
    online_service.repo.upsert_watch_event(
        WatchEvent(source="netflix", profile="Florian", raw_title="Inzeption")
    )
    uid = online_service.repo.add_unmatched(
        "Inzeption", source="netflix", year=None, best_score=60.0, best_title=None
    )
    found = online_client.get("/api/tmdb/search", params={"q": "Inception"}).json()["items"]
    assert found[0]["tmdb_id"] == 27205
    assert found[0]["title"] == "Inception"
    assert online_client.get("/api/tmdb/search", params={"q": ""}).status_code == 422
    r = online_client.post(f"/api/unmatched/{uid}/resolve", json={"tmdb_id": 27205})
    assert r.status_code == 200
    assert online_client.get("/api/unmatched").json()["items"] == []
    event = online_service.repo.list_watch_events()[0]
    assert event.tmdb_id == 27205


def test_twins_endpoint(service: FilmService, florian_ratings: dict[int, int]) -> None:
    client = rated_client(service, florian_ratings)
    twins = client.get("/api/twins").json()["items"]
    assert len(twins) == 20
    assert {"label", "similarity", "overlap", "top_movies"} <= set(twins[0])


def test_settings(client: TestClient, service: FilmService) -> None:
    service.repo.upsert_watch_event(WatchEvent(source="netflix", profile="Florian", raw_title="X"))
    service.repo.upsert_watch_event(WatchEvent(source="netflix", profile="Kinder", raw_title="Y"))
    body = client.get("/api/settings").json()
    assert body["all_profiles"] == ["Florian", "Kinder"]
    assert body["my_profiles"] == []
    assert body["queue_size"] == 1000
    names = {p["name"]: p for p in body["providers"]}
    assert names["Netflix"]["mine"] is True
    assert names["Apple TV"]["mine"] is False
    r = client.put(
        "/api/settings",
        json={"my_profiles": ["Florian"], "my_providers": [8, 9], "queue_size": 300},
    )
    assert r.status_code == 200
    body = client.get("/api/settings").json()
    assert body["my_profiles"] == ["Florian"]
    assert body["my_providers"] == [8, 9]
    assert body["queue_size"] == 300
    assert client.put("/api/settings", json={"queue_size": -5}).status_code == 422
    assert client.put("/api/settings", json={"queue_size": 10**7}).status_code == 422
    assert client.put("/api/settings", json={"my_profiles": ["Gibtsnicht"]}).status_code == 422
    assert body["excluded_genres"] == []
    assert "Drama" in body["all_genres"]
    r = client.put("/api/settings", json={"excluded_genres": ["Drama"]})
    assert r.json()["excluded_genres"] == ["Drama"]


def test_evaluate_endpoint(
    client: TestClient, service: FilmService, florian_ratings: dict[int, int]
) -> None:
    assert client.post("/api/evaluate").status_code == 409
    rate_movielens(service, florian_ratings)
    r = client.post("/api/evaluate")
    assert r.status_code == 200
    body = r.json()
    assert body["rmse"] < body["baseline_rmse"]
    assert client.get("/api/settings").json()["evaluation"]["rmse"] == pytest.approx(body["rmse"])


def test_poster_placeholder(client: TestClient) -> None:
    item = client.get("/api/queue").json()["items"][0]
    assert item["poster_url"].startswith("/poster/")
    r = client.get(item["poster_url"])
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in r.text
    assert client.get("/poster/999999999.svg").status_code == 404


def test_genres_endpoint(client: TestClient) -> None:
    genres = client.get("/api/genres").json()["items"]
    assert "Drama" in genres
    assert genres == sorted(genres)


def test_static_files(client: TestClient) -> None:
    for path in (
        "/static/js/keys.js",
        "/static/js/queue.js",
        "/static/js/rate.js",
        "/static/css/app.css",
    ):
        r = client.get(path)
        assert r.status_code == 200, path
    assert "javascript" in client.get("/static/js/keys.js").headers["content-type"]


def test_client_ids_make_actions_idempotent(client: TestClient) -> None:
    items = client.get("/api/queue").json()["items"]
    a, b = items[0]["film_id"], items[1]["film_id"]
    first = client.post("/api/rate", json={"film_id": a, "score": 8, "client_id": "c1"})
    assert first.json()["duplicate"] is False
    again = client.post("/api/rate", json={"film_id": a, "score": 8, "client_id": "c1"})
    assert again.json()["duplicate"] is True
    client.post("/api/not-seen", json={"film_id": b, "client_id": "c2"})
    client.post("/api/not-seen", json={"film_id": b, "client_id": "c2"})
    assert (
        client.post("/api/undo", json={"client_id": "u1"}).json()["undone"]["action"] == "not_seen"
    )
    assert client.post("/api/undo", json={"client_id": "u1"}).json()["duplicate"] is True
    progress = client.get("/api/progress").json()
    assert (progress["rated"], progress["not_seen"]) == (1, 0)


def test_actions_batch_in_order(client: TestClient) -> None:
    items = client.get("/api/queue").json()["items"]
    a, b, c = (i["film_id"] for i in items[:3])
    client.post("/api/rate", json={"film_id": a, "score": 4, "client_id": "x1"})
    body = {
        "actions": [
            {"type": "rate", "film_id": a, "score": 4, "client_id": "x1"},  # already processed
            {"type": "not_seen", "film_id": b, "client_id": "x2"},
            {"type": "later", "film_id": c, "client_id": "x3"},
            {"type": "undo", "client_id": "x4"},
            {"type": "undo", "client_id": "x5"},
            {"type": "rate", "film_id": 10**9, "score": 3, "client_id": "x6"},
            {"type": "not_seen", "client_id": "x7"},
            {"type": "rate", "film_id": a, "client_id": "x8"},
        ]
    }
    r = client.post("/api/actions", json=body)
    assert r.status_code == 200
    results = r.json()["results"]
    assert results[0] == {"type": "rate", "ok": True, "duplicate": True}
    assert [x["ok"] for x in results[1:5]] == [True, True, True, True]
    assert [x["ok"] for x in results[5:]] == [False, False, False]
    progress = r.json()["progress"]
    assert (progress["rated"], progress["not_seen"]) == (1, 0)
    assert (
        client.post(
            "/api/actions", json={"actions": [{"type": "rate", "film_id": a, "score": 11}]}
        ).status_code
        == 422
    )
    empty_undo = TestClient(client.app).post(
        "/api/actions", json={"actions": [{"type": "undo"}] * 3}
    )
    assert empty_undo.json()["results"][-1]["ok"] is False


def test_film_media_offline_uses_cache_only(client: TestClient, service: FilmService) -> None:
    from conftest import load_json
    from filmzwilling.tmdb import parse_movie

    fid = client.get("/api/queue").json()["items"][0]["film_id"]
    body = client.get(f"/api/films/{fid}/media").json()
    assert body["trailers"] == [] and body["backdrop_url"] is None
    assert body["online"] is False and body["poster_url"]
    assert client.get("/api/films/999999/media").status_code == 404

    film_id = service.repo.upsert_tmdb_details(parse_movie(load_json("movie_27205.json")))
    service.repo.cache_put("movie:27205", load_json("movie_27205.json"))
    service.repo.cache_put("videos:27205", load_json("videos_27205.json"))
    body = client.get(f"/api/films/{film_id}/media").json()
    assert body["backdrop_url"].startswith("https://image.tmdb.org/t/p/w1280/")
    assert body["overview"]
    assert body["trailers"][0]["key"] == "u_ckVuUUeZw"


def test_film_media_online(online_client: TestClient, online_service: FilmService) -> None:
    from conftest import load_json
    from filmzwilling.tmdb import parse_movie

    film_id = online_service.repo.upsert_tmdb_details(parse_movie(load_json("movie_27205.json")))
    body = online_client.get(f"/api/films/{film_id}/media").json()
    assert body["online"] is True
    assert [t["key"] for t in body["trailers"]][:2] == ["u_ckVuUUeZw", "FANde000001"]
    assert body["trailers"][0]["language"] == "de"
    assert body["backdrop_url"]
    # A film without videos on TMDB (404) still answers with an empty list.
    other = online_service.repo.upsert_tmdb_details(parse_movie(load_json("movie_238.json")))
    body = online_client.get(f"/api/films/{other}/media").json()
    assert body["trailers"] == []


def test_twin_detail(service: FilmService, florian_ratings: dict[int, int]) -> None:
    client = rated_client(service, florian_ratings)
    assert client.get("/api/twins/1").status_code == 200
    body = client.get("/api/twins/1", params={"limit": 300}).json()
    assert body["label"] == "Zwilling 1"
    assert body["n_ratings"] == body["n_common"] + body["n_new"] == body["total"]
    assert sum(body["histogram"]) == body["n_ratings"]
    assert len(body["histogram"]) == 11
    scores = [i["their_score"] for i in body["items"]]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= s <= 10 for s in scores)
    item = body["items"][0]
    for key in ("film_id", "title", "poster_url", "their_score", "their_score_text", "your_score"):
        assert key in item

    common = client.get("/api/twins/1", params={"show": "common", "limit": 300}).json()
    assert common["total"] == body["n_common"]
    assert all(i["your_score"] is not None for i in common["items"])
    new = client.get("/api/twins/1", params={"show": "new", "sort": "low"}).json()
    assert all(i["your_score"] is None for i in new["items"])
    low = [i["their_score"] for i in new["items"]]
    assert low == sorted(low)
    titled = client.get("/api/twins/1", params={"sort": "title", "limit": 5}).json()
    assert len(titled["items"]) == 5
    page2 = client.get("/api/twins/1", params={"offset": 5, "limit": 5}).json()
    assert [i["film_id"] for i in page2["items"]] == [i["film_id"] for i in body["items"][5:10]]

    assert client.get("/api/twins/99").status_code == 404
    assert client.get("/api/twins/1", params={"sort": "bogus"}).status_code == 422
    assert client.get("/api/twins/1", params={"limit": 0}).status_code == 422


def test_twin_detail_without_twins(client: TestClient) -> None:
    assert client.get("/api/twins/1").status_code == 404
