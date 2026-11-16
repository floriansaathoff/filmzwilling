from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import rate_movielens
from filmzwilling.service import FilmService
from filmzwilling.web.app import create_app

PAGES = {
    "/": "Bewerten",
    "/empfehlungen": "Empfehlungen",
    "/bewertungen": "Meine Bewertungen",
    "/zuordnung": "Zuordnung",
    "/zwillinge": "Zwillinge",
    "/einstellungen": "Einstellungen",
}
FOOTER = (
    "Diese App nutzt die TMDB-API, wird aber nicht von TMDB unterstützt oder zertifiziert. "
    "Streaming-Verfügbarkeit: JustWatch."
)


@pytest.fixture
def client(service: FilmService) -> TestClient:
    return TestClient(create_app(service))


@pytest.mark.parametrize(("path", "label"), list(PAGES.items()))
def test_pages_render(client: TestClient, path: str, label: str) -> None:
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    html = r.text
    assert '<html lang="de">' in html
    assert "{{" not in html and "{%" not in html
    for nav_label in PAGES.values():
        assert nav_label in html
    assert FOOTER in html
    assert label in html


def test_rate_page_uses_modules(client: TestClient) -> None:
    html = client.get("/").text
    assert 'type="module"' in html
    assert "/static/js/rate.js" in html
    for label in ("Nicht gesehen", "Später", "Zurück"):
        assert label in html
    for n in range(11):
        assert f'data-score="{n}"' in html


def test_recommendations_page_hint_below_30(client: TestClient) -> None:
    html = client.get("/empfehlungen").text
    assert "30" in html
    assert "Neu seit Ende 2023" in html
    assert "nicht personalisiert" in html


def test_pages_with_data(service: FilmService, florian_ratings: dict[int, int]) -> None:
    rate_movielens(service, florian_ratings)
    service.recompute()
    client = TestClient(create_app(service))
    for path in PAGES:
        assert client.get(path).status_code == 200
    html = client.get("/zwillinge").text
    assert "Zwilling 1" in html
    assert "So gut kennt dich die App" in client.get("/einstellungen").text


def test_unknown_page(client: TestClient) -> None:
    assert client.get("/gibtsnicht").status_code == 404
