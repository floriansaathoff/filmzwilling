"""`filmzwilling demo`: synthetic data dir with MovieLens-like data, metadata and providers.

Works without network and without token: posters are generated placeholders, provider logos are
left out and the data directory is marked as demo so that TMDB is never contacted for it.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from filmzwilling.config import Settings
from filmzwilling.genres import german_genres
from filmzwilling.importers.common import WatchEvent
from filmzwilling.movielens import clean_ml_title, parse_ml_title, process_movielens
from filmzwilling.synthetic import generate_dataset, write_csvs
from filmzwilling.tmdb import MovieDetails, Provider, ProviderOffer

DEMO_PROVIDERS = (
    Provider(8, "Netflix", None, 0),
    Provider(9, "Amazon Prime Video", None, 1),
    Provider(337, "Disney Plus", None, 2),
    Provider(304, "Joyn", None, 3),
    Provider(219, "ARD Mediathek", None, 4),
    Provider(537, "ZDF", None, 5),
    Provider(234, "Arte", None, 6),
    Provider(1990, "3sat", None, 7),
    Provider(1796, "Netflix basic with Ads", None, 8),
    Provider(2, "Apple TV", None, 9),
    Provider(10, "Amazon Video", None, 10),
    Provider(30, "WOW", None, 11),
)
_INCLUDED = (
    (8, "flatrate"),
    (9, "flatrate"),
    (337, "flatrate"),
    (304, "free"),
    (219, "free"),
    (537, "free"),
    (234, "free"),
    (1990, "free"),
    (1796, "ads"),
    (30, "flatrate"),
)
_PAID = ((2, "rent"), (2, "buy"), (10, "rent"), (10, "buy"))


def _offers(rng: np.random.Generator) -> list[ProviderOffer]:
    names = {p.provider_id: p.name for p in DEMO_PROVIDERS}
    chosen: list[tuple[int, str]] = []
    if rng.random() < 0.75:
        picks = rng.choice(len(_INCLUDED), size=int(rng.integers(1, 3)), replace=False)
        chosen.extend(_INCLUDED[int(i)] for i in picks)
    if rng.random() < 0.5:
        chosen.append(_PAID[int(rng.integers(0, len(_PAID)))])
    return [ProviderOffer(pid, names[pid], None, cat, 0) for pid, cat in chosen]


def prepare_demo(
    data_dir: Path, *, seed: int = 7, n_users: int = 600, n_movies: int = 400
) -> Settings:
    """Create processed synthetic data, a database with metadata, providers and imports."""
    from filmzwilling.service import FilmService

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(data_dir=data_dir, offline=True)
    ds = generate_dataset(
        n_users=n_users,
        n_movies=n_movies,
        n_clusters=4,
        min_ratings=30,
        max_ratings=150,
        n_favorites=12,
        seed=seed,
    )
    csv_dir = settings.raw_dir / "demo"
    write_csvs(ds, csv_dir)
    process_movielens(csv_dir, settings.processed_dir, checksum=f"demo-{seed}-{n_users}-{n_movies}")
    shutil.rmtree(csv_dir, ignore_errors=True)

    service = FilmService(settings)
    repo = service.repo
    repo.set_setting("demo_mode", True)
    service.sync_movielens_films()
    repo.upsert_providers(DEMO_PROVIDERS)

    rng = np.random.default_rng(seed)
    data = service.require_data()
    for row in data.movies.itertuples():
        tmdb = row.tmdbId
        if tmdb is None or str(tmdb) == "<NA>":
            continue
        _, year = parse_ml_title(str(row.title))
        details = MovieDetails(
            tmdb_id=int(tmdb),
            title=clean_ml_title(str(row.title)),
            original_title=clean_ml_title(str(row.title)),
            runtime=int(rng.integers(78, 175)),
            genres=german_genres(list(row.genres)) or ["Drama"],
            poster_path=None,
            vote_average=round(float(rng.uniform(5.0, 8.6)), 1),
            vote_count=int(rng.integers(100, 20000)),
            release_date=f"{year or 2000}-06-01",
            popularity=float(row.count),
            offers=_offers(rng),
        )
        film_id = repo.upsert_tmdb_details(details)
        repo.set_film_offers(film_id, details.offers or [])

    # A few imported titles so that the hint chips and the profile logic can be seen.
    films = data.movies[data.movies["tmdbId"].notna()].sort_values("popularity_rank")
    picks = films.iloc[[3, 8, 14, 21, 30, 42, 55, 70]]
    base = datetime(2024, 5, 1, 20, 0)
    fractions = (1.0, 0.95, 0.3, 0.7, 1.0, 0.2, 1.0, 0.9)
    for i, (row, fraction) in enumerate(zip(picks.itertuples(), fractions, strict=True)):
        film_id = repo.film_id_for_tmdb(int(row.tmdbId))
        film = repo.get_film(film_id) if film_id else None
        runtime = (film.runtime if film else None) or 100
        profile = "Florian" if i < 6 else "Kinder"
        seconds = int(runtime * 60 * fraction)
        repo.upsert_watch_event(
            WatchEvent(
                source="demo",
                profile=profile,
                raw_title=clean_ml_title(str(row.title)),
                first_seen=base - timedelta(days=10 * i),
                last_seen=base - timedelta(days=10 * i),
                total_watch_seconds=seconds,
                max_position_seconds=seconds,
                sessions=1 + i % 2,
                hints={"netflix_thumbs": "up"} if i == 1 else {},
                tmdb_id=int(row.tmdbId),
                movielens_id=int(row.movieId),
            )
        )
    repo.upsert_watch_event(
        WatchEvent(source="demo", profile="Florian", raw_title="Ein Film, den es nicht gibt")
    )
    repo.add_unmatched(
        "Ein Film, den es nicht gibt",
        source="demo",
        year=None,
        best_score=41.0,
        best_title="Ein ganz anderer Film",
    )
    repo.update_user_settings(my_profiles=["Florian"])
    return settings
