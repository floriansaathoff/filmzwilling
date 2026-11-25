"""Data-science page: embeddings, statistics, API and page."""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from conftest import rate_movielens
from filmzwilling.insights import (
    InsightConfig,
    build_insights,
    genre_profile,
    rating_histograms,
    timeline,
)
from filmzwilling.movielens import ProcessedData
from filmzwilling.service import FilmService
from filmzwilling.web.app import create_app


def no_titles(film_ids: object) -> dict[int, str]:
    return {}


def test_taste_space_puts_twins_near_you(
    synthetic_data: ProcessedData, florian_ratings: dict[int, int], config: object
) -> None:
    out = build_insights(
        synthetic_data, florian_ratings, config, ml_to_film={}, titles=no_titles, recs=[]
    )
    taste = out["taste"]
    xyz = np.array([taste["x"], taste["y"], taste["z"]]).T
    sim = np.array(taste["similarity"])
    assert len(xyz) == synthetic_data.n_users  # sample covers the small synthetic set
    assert taste["n_twins"] > 20
    assert list(sim) == sorted(sim, reverse=True)
    assert taste["rank"][0] == 1
    dist = np.linalg.norm(xyz - np.array(taste["you"]), axis=1)
    assert dist[sim > 0].mean() < dist[sim == 0].mean()
    assert sum(taste["explained"]) < 100
    assert taste["explained"] == sorted(taste["explained"], reverse=True)


def test_film_universe_marks_rated_and_recommended(
    synthetic_data: ProcessedData, florian_ratings: dict[int, int], config: object
) -> None:
    rec_id = next(int(m) for m in synthetic_data.movie_ids if int(m) not in florian_ratings)
    cfg = InsightConfig(display_movies=20, svd_movies=50)
    out = build_insights(
        synthetic_data,
        florian_ratings,
        config,
        ml_to_film={rec_id: 99},
        titles=lambda ids: {99: "Empfohlen"} if 99 in ids else {},
        recs=[(rec_id, 8.5, 12)],
        cfg=cfg,
    )
    films = out["films"]["films"]
    assert len(films) == len(out["films"]["x"])
    assert len(films) >= len(florian_ratings)  # all own films are shown on top of the 20
    assert sum(f["your"] is not None for f in films) == len(florian_ratings)
    rec = next(f for f in films if f["rec"] is not None)
    assert rec == {**rec, "film_id": 99, "title": "Empfohlen", "rec": 8.5}
    assert out["recs"] == {"score": [8.5], "support": [12], "title": ["Empfohlen"]}
    assert all(f["title"] for f in films)


def test_embedding_without_ratings_is_empty_but_valid(
    synthetic_data: ProcessedData, config: object
) -> None:
    out = build_insights(synthetic_data, {}, config, ml_to_film={}, titles=no_titles, recs=[])
    assert out["taste"]["n_twins"] == 0
    assert out["twins"]["total"] == 0
    assert all(f["your"] is None for f in out["films"]["films"])


def test_tiny_matrix_falls_back_to_zeros(synthetic_data: ProcessedData, config: object) -> None:
    cfg = InsightConfig(sample_users=3, display_users=3, svd_movies=2, display_movies=2)
    out = build_insights(
        synthetic_data, {}, config, ml_to_film={}, titles=no_titles, recs=[], cfg=cfg
    )
    assert set(out["taste"]["x"]) == {0.0}


def test_rating_histograms(synthetic_data: ProcessedData) -> None:
    hist = rating_histograms(synthetic_data, [5, 5, 10, 0], InsightConfig(rating_sample=5000))
    assert hist["yours"] == [1, 0, 0, 0, 0, 2, 0, 0, 0, 0, 1]
    assert abs(sum(hist["movielens_share"]) - 1) < 1e-3
    # half stars are split between neighbours, so no note stays empty in the middle
    assert all(v > 0 for v in hist["movielens_share"][2:9])


def test_genre_profile_and_timeline() -> None:
    profile = genre_profile([(8, ["Drama", "Krimi"]), (4, ["Drama"]), (10, ["Komödie"])])
    assert profile[0] == {"genre": "Drama", "count": 2, "mean": 6.0}
    assert [g["genre"] for g in profile] == ["Drama", "Komödie", "Krimi"]
    points = timeline(["2026-11-02T10:00", "2026-11-01T09:00", "2026-11-02T11:00", ""])
    assert points == [
        {"at": "2026-11-01T09:00", "total": 1},
        {"at": "2026-11-02T10:00", "total": 2},
        {"at": "2026-11-02T11:00", "total": 3},
    ]
    many = timeline([f"2026-11-01T10:{m:02d}" for m in range(50)], max_points=7)
    assert len(many) <= 8
    assert many[-1] == {"at": "2026-11-01T10:49", "total": 50}
    assert timeline([]) == []


def test_service_insights_cached_until_ratings_change(
    service: FilmService, florian_ratings: dict[int, int]
) -> None:
    rate_movielens(service, florian_ratings)
    service.recompute()
    first = service.insights()
    assert service.insights() is first
    assert first["summary"]["ratings"] == len(florian_ratings)
    assert first["summary"]["recs"] > 0
    assert sum(first["histogram"]["yours"]) == len(florian_ratings)
    assert first["genres"]
    assert first["timeline"][-1]["total"] == len(florian_ratings)
    assert first["recs"]["title"][0]
    assert sorted(first["twin_pages"].values()) == list(range(1, 21))
    film_id = service.repo.film_id_for_movielens(next(iter(florian_ratings)))
    assert film_id is not None
    service.repo.set_rating(film_id, 0 if service.repo.get_rating(film_id) else 10)
    assert service.insights() is not first


def test_insights_api_and_page(service: FilmService, florian_ratings: dict[int, int]) -> None:
    rate_movielens(service, florian_ratings)
    client = TestClient(create_app(service))
    body = client.get("/api/insights").json()
    assert {"taste", "films", "twins", "recs", "histogram", "genres", "timeline"} <= set(body)
    page = client.get("/data-science")
    assert page.status_code == 200
    assert 'id="ds-app"' in page.text
    # Only reachable through the settings, not through the tab bar.
    assert 'href="/data-science"' not in page.text.split("</header>")[0]
    assert 'href="/data-science"' in client.get("/einstellungen").text


def test_film_universe_survives_missing_metadata(
    synthetic_data: ProcessedData, florian_ratings: dict[int, int], config: object
) -> None:
    """Parquet can hand back NaN years, None genres and missing titles (real data crashed)."""
    from dataclasses import replace

    movies = synthetic_data.movies.copy()
    movies["year"] = movies["year"].astype("float64")
    movies.loc[movies.index[::3], "year"] = float("nan")
    movies["genres"] = [
        None if i % 4 == 1 else np.array(g, dtype=object) if i % 4 == 2 else g
        for i, g in enumerate(movies["genres"])
    ]
    movies.loc[movies.index[::5], "title"] = None
    means = synthetic_data.movie_means.copy()
    means[::7] = np.nan
    data = replace(synthetic_data, movies=movies, movie_means=means)
    out = build_insights(data, florian_ratings, config, ml_to_film={}, titles=no_titles, recs=[])
    films = out["films"]["films"]
    assert any(f["year"] is None for f in films)
    assert all(f["year"] is None or isinstance(f["year"], int) for f in films)
    assert all(isinstance(f["genres"], list) for f in films)
    assert all(f["title"] for f in films)
    assert any(f["mean"] is None for f in films)
    import json

    json.dumps(out, allow_nan=False)
