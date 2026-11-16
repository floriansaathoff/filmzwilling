"""Regenerate tests/fixtures/ml-mini (deterministic). Run: python tests/fixtures/make_ml_mini.py"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from filmzwilling.synthetic import generate_dataset, write_csvs

HERE = Path(__file__).parent


def main() -> None:
    ds = generate_dataset(
        n_users=30, n_movies=40, n_clusters=2, min_ratings=12, max_ratings=30, n_favorites=3, seed=5
    )
    movies = ds.movies.copy()
    movies.loc[movies.movieId == 1, ["title", "genres"]] = ["Godfather, The (1972)", "Crime|Drama"]
    movies.loc[movies.movieId == 2, "title"] = (
        "Lives of Others, The (Leben der Anderen, Das) (2006)"
    )
    movies.loc[movies.movieId == 3, "title"] = (
        'Dr. Strangelove or: How I Learned to Stop Worrying ("Quoted") (1964)'
    )
    movies.loc[movies.movieId == 38, ["title", "genres"]] = [
        "Untitled Project",
        "(no genres listed)",
    ]
    ds.movies = movies
    links = ds.links.copy()
    links["tmdbId"] = links["tmdbId"].astype("Int64")
    links.loc[links.movieId == 39, "tmdbId"] = pd.NA
    links.loc[links.movieId == 1, "tmdbId"] = 238
    links.loc[links.movieId == 2, "tmdbId"] = 582
    ds.links = links
    # Movie 40 has no ratings at all.
    ds.ratings = ds.ratings[ds.ratings.movieId != 40].reset_index(drop=True)
    write_csvs(ds, HERE / "ml-mini")


if __name__ == "__main__":
    main()
