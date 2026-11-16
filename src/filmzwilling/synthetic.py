"""Reproducible synthetic MovieLens-like data with taste clusters.

Users belong to taste clusters. Each cluster has a set of favourite movies that its members rate
highly while the other clusters rate them low, so the plain movie mean is a weak predictor and
collaborative filtering has something to find. Used by the tests and by `filmzwilling demo`.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.typing import NDArray

ML_GENRES = (
    "Action",
    "Adventure",
    "Animation",
    "Children",
    "Comedy",
    "Crime",
    "Documentary",
    "Drama",
    "Fantasy",
    "Horror",
    "Mystery",
    "Romance",
    "Sci-Fi",
    "Thriller",
    "War",
    "Western",
)

# Genres that each cluster tends to like (used to make demo data feel plausible).
CLUSTER_GENRES = (
    ("Sci-Fi", "Action", "Thriller"),
    ("Drama", "Romance", "War"),
    ("Comedy", "Animation", "Children"),
    ("Horror", "Mystery", "Crime"),
    ("Documentary", "Western", "Adventure"),
)

_ADJECTIVES = (
    "lang",
    "still",
    "letzt",
    "kalt",
    "verloren",
    "rot",
    "dunkl",
    "golden",
    "geheim",
    "wild",
    "zweit",
    "fern",
)
# (noun, article) so that "Der lange Sommer" / "Die stille Stadt" / "Das letzte Signal" fit.
_NOUNS = (
    ("Sommer", "Der"),
    ("Stadt", "Die"),
    ("Signal", "Das"),
    ("Fluss", "Der"),
    ("Reise", "Die"),
    ("Haus", "Das"),
    ("Horizont", "Der"),
    ("Spiel", "Das"),
    ("Nacht", "Die"),
    ("Grenze", "Die"),
    ("Insel", "Die"),
    ("Echo", "Das"),
    ("Spur", "Die"),
    ("Wald", "Der"),
    ("Planet", "Der"),
    ("Brücke", "Die"),
)
_SUFFIXES = ("", " II", " – Die Rückkehr", " von Hamburg", " am Meer", " im Nebel", " 3000")


@dataclass
class SyntheticDataset:
    ratings: pd.DataFrame
    movies: pd.DataFrame
    links: pd.DataFrame
    user_clusters: NDArray[np.int64]
    affinity: NDArray[np.float64]
    quality: NDArray[np.float64]
    favorites: dict[int, list[int]]
    seed: int

    @property
    def movie_ids(self) -> NDArray[np.int64]:
        return self.movies["movieId"].to_numpy(dtype=np.int64)

    def expected_ml(self, cluster: int, movie_id: int) -> float:
        """Noise-free expected MovieLens rating of a cluster member (without user bias)."""
        m = int(movie_id) - 1
        value = 3.0 + 0.4 * self.quality[m] + 0.9 * self.affinity[cluster, m]
        return float(np.clip(value, 0.5, 5.0))


def _title_for(rng: np.random.Generator, index: int) -> str:
    stem = _ADJECTIVES[index % len(_ADJECTIVES)]
    noun, article = _NOUNS[(index // len(_ADJECTIVES)) % len(_NOUNS)]
    suffix = _SUFFIXES[int(rng.integers(0, len(_SUFFIXES)))] if index >= 150 else ""
    return f"{article} {stem}e {noun}{suffix}"


def generate_dataset(
    *,
    n_users: int = 300,
    n_movies: int = 200,
    n_clusters: int = 3,
    min_ratings: int = 40,
    max_ratings: int = 120,
    n_favorites: int = 10,
    noise: float = 0.35,
    missing_tmdb_fraction: float = 0.03,
    seed: int = 42,
) -> SyntheticDataset:
    """Generate a clustered rating dataset in MovieLens CSV layout."""
    if n_clusters < 1 or n_clusters > len(CLUSTER_GENRES):
        raise ValueError(f"n_clusters must be between 1 and {len(CLUSTER_GENRES)}")
    if n_favorites * n_clusters > n_movies // 2:
        raise ValueError("too many favourites for the number of movies")
    rng = np.random.default_rng(seed)

    quality = rng.normal(0.0, 0.5, n_movies)
    affinity = rng.normal(0.0, 0.6, (n_clusters, n_movies))

    # Popularity: Zipf-like weights over a random permutation of the movies.
    pop_rank = rng.permutation(n_movies)
    weights = 1.0 / np.power(1.0 + pop_rank, 0.6)

    # Favourites come from the more popular half so that enough twins rate them.
    popular_half = np.argsort(pop_rank, kind="stable")[: n_movies // 2]
    chosen = rng.choice(popular_half, size=n_favorites * n_clusters, replace=False)
    favorites: dict[int, list[int]] = {}
    for c in range(n_clusters):
        fav = np.sort(chosen[c * n_favorites : (c + 1) * n_favorites])
        favorites[c] = [int(m) + 1 for m in fav]
        affinity[:, fav] = -1.2
        affinity[c, fav] = 2.0
        quality[fav] = 0.0

    user_clusters = rng.integers(0, n_clusters, n_users).astype(np.int64)
    user_bias = rng.normal(0.0, 0.3, n_users)

    user_col: list[NDArray[np.int64]] = []
    movie_col: list[NDArray[np.int64]] = []
    rating_col: list[NDArray[np.float64]] = []
    p = weights / weights.sum()
    for u in range(n_users):
        n = int(rng.integers(min_ratings, max_ratings + 1))
        n = min(n, n_movies)
        movies = np.sort(rng.choice(n_movies, size=n, replace=False, p=p))
        c = user_clusters[u]
        raw = (
            3.0
            + 0.4 * quality[movies]
            + 0.9 * affinity[c, movies]
            + user_bias[u]
            + rng.normal(0.0, noise, n)
        )
        stars = np.clip(np.round(raw * 2.0) / 2.0, 0.5, 5.0)
        user_col.append(np.full(n, u + 1, dtype=np.int64))
        movie_col.append(movies.astype(np.int64) + 1)
        rating_col.append(stars)

    ratings = pd.DataFrame(
        {
            "userId": np.concatenate(user_col),
            "movieId": np.concatenate(movie_col),
            "rating": np.concatenate(rating_col),
        }
    )
    ratings["timestamp"] = 1_600_000_000 + np.arange(len(ratings), dtype=np.int64) * 60

    titles: list[str] = []
    genres: list[str] = []
    years = rng.integers(1960, 2023, n_movies)
    fav_cluster = {m: c for c, ms in favorites.items() for m in ms}
    for m in range(n_movies):
        base = _title_for(rng, m)
        titles.append(f"{base} ({int(years[m])})")
        best_cluster = fav_cluster.get(m + 1, int(np.argmax(affinity[:, m])))
        g = {CLUSTER_GENRES[best_cluster][int(rng.integers(0, 3))]}
        if rng.random() < 0.6:
            g.add(ML_GENRES[int(rng.integers(0, len(ML_GENRES)))])
        genres.append("|".join(sorted(g)))
    movie_ids = np.arange(1, n_movies + 1, dtype=np.int64)
    movies_df = pd.DataFrame({"movieId": movie_ids, "title": titles, "genres": genres})

    tmdb = pd.array(100_000 + movie_ids, dtype="Int64")
    fav_set = set(fav_cluster)
    for m in range(n_movies):
        if (m + 1) not in fav_set and rng.random() < missing_tmdb_fraction:
            tmdb[m] = pd.NA
    links = pd.DataFrame({"movieId": movie_ids, "imdbId": 1_000_000 + movie_ids, "tmdbId": tmdb})

    return SyntheticDataset(
        ratings=ratings,
        movies=movies_df,
        links=links,
        user_clusters=user_clusters,
        affinity=affinity,
        quality=quality,
        favorites=favorites,
        seed=seed,
    )


def synthetic_user_ratings(
    ds: SyntheticDataset,
    cluster: int,
    *,
    n: int = 60,
    seed: int = 1,
    include_favorites: bool = False,
    noise: float = 0.3,
) -> dict[int, int]:
    """Ratings (0–10) of a new user in `cluster` for `n` movies.

    By default the cluster's favourites are left out so that they remain candidates.
    """
    rng = np.random.default_rng(seed)
    favs = set(ds.favorites[cluster])
    pool = [int(m) for m in ds.movie_ids if include_favorites or int(m) not in favs]
    n = min(n, len(pool))
    chosen = rng.choice(np.array(pool), size=n, replace=False)
    result: dict[int, int] = {}
    for m in sorted(int(x) for x in chosen):
        ml = ds.expected_ml(cluster, m) + rng.normal(0.0, noise)
        note = round((float(np.clip(ml, 0.5, 5.0)) - 0.5) / 0.45)
        result[m] = int(np.clip(note, 0, 10))
    return result


def write_csvs(ds: SyntheticDataset, directory: Path) -> Path:
    """Write ratings.csv, movies.csv and links.csv in MovieLens format."""
    directory.mkdir(parents=True, exist_ok=True)
    ds.ratings.to_csv(directory / "ratings.csv", index=False)
    ds.movies.to_csv(directory / "movies.csv", index=False)
    ds.links.to_csv(directory / "links.csv", index=False)
    return directory


def write_zip(ds: SyntheticDataset, zip_path: Path, folder: str = "ml-32m") -> Path:
    """Write a zip that looks like the official ml-32m.zip."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{folder}/ratings.csv", ds.ratings.to_csv(index=False))
        zf.writestr(f"{folder}/movies.csv", ds.movies.to_csv(index=False))
        zf.writestr(f"{folder}/links.csv", ds.links.to_csv(index=False))
        zf.writestr(f"{folder}/README.txt", "Synthetic MovieLens-like data for tests.\n")
    return zip_path
