from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from filmzwilling.config import RecommenderConfig, Settings
from filmzwilling.db import Database
from filmzwilling.movielens import ProcessedData, build_processed
from filmzwilling.repository import Repository
from filmzwilling.synthetic import SyntheticDataset, generate_dataset, synthetic_user_ratings
from filmzwilling.tmdb import MovieDetails, Provider, ProviderOffer

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / "tmdb" / name).read_text(encoding="utf-8"))


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def ml_mini_dir() -> Path:
    return FIXTURES / "ml-mini"


@pytest.fixture(scope="session")
def synthetic_ds() -> SyntheticDataset:
    return generate_dataset(seed=42)


@pytest.fixture(scope="session")
def synthetic_data(synthetic_ds: SyntheticDataset) -> ProcessedData:
    return build_processed(synthetic_ds.ratings, synthetic_ds.movies, synthetic_ds.links)


@pytest.fixture
def config() -> RecommenderConfig:
    return RecommenderConfig()


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "app.sqlite")
    database.initialize()
    return database


@pytest.fixture
def repo(db: Database) -> Repository:
    return Repository(db)


@pytest.fixture
def offline_settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", offline=True)


PROVIDERS = [
    Provider(8, "Netflix", "/netflix.jpg", 0),
    Provider(9, "Amazon Prime Video", "/prime.jpg", 1),
    Provider(219, "ARD Mediathek", "/ard.jpg", 4),
    Provider(1796, "Netflix basic with Ads", "/netflixads.jpg", 8),
    Provider(2, "Apple TV", "/apple.jpg", 10),
    Provider(30, "WOW", "/wow.jpg", 12),
]


def offers_for(movie_id: int) -> list[ProviderOffer]:
    """Deterministic fake availability used by service/API tests."""
    offers: list[ProviderOffer] = []
    if movie_id % 3 == 0:
        offers.append(ProviderOffer(8, "Netflix", "/netflix.jpg", "flatrate", 0))
    if movie_id % 3 == 1:
        offers.append(ProviderOffer(219, "ARD Mediathek", "/ard.jpg", "free", 4))
    if movie_id % 7 == 0:
        offers.append(ProviderOffer(1796, "Netflix basic with Ads", "/netflixads.jpg", "ads", 8))
    if movie_id % 5 == 0:
        offers.append(ProviderOffer(2, "Apple TV", "/apple.jpg", "rent", 10))
    if movie_id % 11 == 0:
        offers.append(ProviderOffer(30, "WOW", "/wow.jpg", "flatrate", 12))
    return offers


GENRE_CYCLE = ["Drama", "Komödie", "Action", "Science Fiction", "Thriller", "Liebesfilm"]


def populate_metadata(repo: Repository, ds: SyntheticDataset) -> None:
    """Fake TMDB metadata for every synthetic movie that has a tmdbId."""
    repo.upsert_providers(PROVIDERS)
    links = ds.links.set_index("movieId")["tmdbId"]
    for row in ds.movies.itertuples():
        tmdb_id = links.loc[row.movieId]
        if tmdb_id is None or str(tmdb_id) == "<NA>":
            continue
        movie_id = int(row.movieId)
        title = str(row.title).rsplit(" (", 1)[0]
        year = int(str(row.title).rsplit("(", 1)[1].rstrip(")"))
        details = MovieDetails(
            tmdb_id=int(tmdb_id),
            title=f"{title} DE",
            original_title=title,
            runtime=80 + (movie_id * 7) % 80,
            genres=[GENRE_CYCLE[movie_id % 6], GENRE_CYCLE[(movie_id // 6) % 6]],
            poster_path=None,
            vote_average=5.0 + (movie_id % 40) / 10,
            vote_count=100 + movie_id,
            release_date=f"{year}-05-01",
            popularity=float(movie_id),
            offers=offers_for(movie_id),
        )
        film_id = repo.upsert_tmdb_details(details)
        repo.set_film_offers(film_id, details.offers or [])


@pytest.fixture
def service(
    offline_settings: Settings, synthetic_data: ProcessedData, synthetic_ds: SyntheticDataset
):
    from filmzwilling.service import FilmService

    svc = FilmService(offline_settings, data=synthetic_data)
    svc.sync_movielens_films()
    populate_metadata(svc.repo, synthetic_ds)
    yield svc
    svc.wait_for_background(timeout=30)


@pytest.fixture
def florian_ratings(synthetic_ds: SyntheticDataset) -> dict[int, int]:
    return synthetic_user_ratings(synthetic_ds, 0, n=60, seed=3)


def rate_movielens(svc: Any, ratings: dict[int, int]) -> None:
    for movie_id, note in ratings.items():
        film_id = svc.repo.film_id_for_movielens(movie_id)
        assert film_id is not None
        svc.repo.set_rating(film_id, note, log_action=False)


TMDBHandler = Callable[[httpx.Request], httpx.Response]


def tmdb_fixture_handler(extra: dict[str, Any] | None = None) -> TMDBHandler:
    """MockTransport handler serving TMDB fixtures by path."""
    extra = extra or {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/3")
        if path in extra:
            return httpx.Response(200, json=extra[path])
        if path.startswith("/movie/"):
            parts = path.split("/")
            tmdb_id = parts[2]
            name = f"movie_{tmdb_id}.json"
            if len(parts) > 3:
                name = f"providers_{tmdb_id}.json"
            file = FIXTURES / "tmdb" / name
            if file.exists():
                return httpx.Response(200, json=load_json(name))
            return httpx.Response(404, json={"status_code": 34})
        if path == "/search/movie":
            query = request.url.params.get("query", "").lower()
            mapping = {
                "inception": "search_inception.json",
                "der pate": "search_der_pate.json",
                "the godfather": "search_der_pate.json",
                "das leben der anderen": "search_leben_der_anderen.json",
                "planet der affen": "search_planet_der_affen.json",
            }
            return httpx.Response(200, json=load_json(mapping.get(query, "search_empty.json")))
        if path == "/watch/providers/movie":
            return httpx.Response(200, json=load_json("providers_de.json"))
        if path == "/discover/movie":
            page = request.url.params.get("page", "1")
            return httpx.Response(200, json=load_json(f"discover_page{page}.json"))
        return httpx.Response(404, json={})

    return handler


@pytest.fixture
def online_service(
    tmp_path: Path, synthetic_data: ProcessedData, synthetic_ds: SyntheticDataset
) -> Iterator[Any]:
    from filmzwilling.service import FilmService

    settings = Settings(data_dir=tmp_path / "data-online", offline=False, tmdb_token=None)
    transport = httpx.MockTransport(tmdb_fixture_handler())
    svc = FilmService(settings, data=synthetic_data, transport=transport)
    svc.sync_movielens_films()
    populate_metadata(svc.repo, synthetic_ds)
    yield svc
    svc.wait_for_background(timeout=30)
