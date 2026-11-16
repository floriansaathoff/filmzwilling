from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from filmzwilling.demo import prepare_demo
from filmzwilling.service import FilmService
from filmzwilling.web.app import create_app


def test_demo_end_to_end(tmp_path: Path) -> None:
    settings = prepare_demo(tmp_path / "demo")
    assert settings.offline is True
    svc = FilmService(settings)
    repo = svc.repo
    assert repo.count_films() > 0
    assert repo.list_providers()
    assert repo.count_watch_events() > 0
    assert len(repo.profiles()) >= 2
    client = TestClient(create_app(svc))
    for path in (
        "/",
        "/empfehlungen",
        "/bewertungen",
        "/zuordnung",
        "/zwillinge",
        "/einstellungen",
    ):
        assert client.get(path).status_code == 200
    first = client.get("/api/queue").json()["items"][0]
    assert first["title"] and first["genres"] and first["runtime"]
    assert any(h["kind"] == "source" for h in first["hints"]) or first["source"] == 4
    rated = 0
    while rated < 50:
        items = client.get("/api/queue", params={"limit": 20}).json()["items"]
        for item in items:
            score = (item["film_id"] * 3) % 11
            assert (
                client.post(
                    "/api/rate", json={"film_id": item["film_id"], "score": score}
                ).status_code
                == 200
            )
            rated += 1
            if rated == 50:
                break
    svc.wait_for_background(timeout=60)
    body = client.get("/api/recommendations", params={"providers": "any"}).json()
    assert body["status"] == "ok"
    assert len(body["items"]) > 0
    default = client.get("/api/recommendations").json()
    assert default["items"]
    assert all(i["offers"] for i in default["items"])


def test_demo_is_reproducible(tmp_path: Path) -> None:
    a = prepare_demo(tmp_path / "a", seed=3)
    b = prepare_demo(tmp_path / "b", seed=3)
    ta = [f.display_title for f in FilmService(a).repo.search_films("", limit=50)]
    tb = [f.display_title for f in FilmService(b).repo.search_films("", limit=50)]
    assert ta == tb


def test_prepare_demo_twice_same_dir(tmp_path: Path) -> None:
    prepare_demo(tmp_path / "x")
    settings = prepare_demo(tmp_path / "x")
    assert FilmService(settings).repo.count_films() > 0
