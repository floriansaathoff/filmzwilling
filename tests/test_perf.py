from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from filmzwilling.config import RecommenderConfig
from filmzwilling.movielens import build_processed
from filmzwilling.recommender import predict_all, user_arrays
from filmzwilling.similarity import compute_similarities


@pytest.mark.slow
def test_20000_users_3000_movies_under_5_seconds() -> None:
    rng = np.random.default_rng(0)
    n_users, n_movies, per_user = 20_000, 3_000, 100
    weights = 1.0 / np.power(np.arange(1, n_movies + 1), 0.7)
    weights /= weights.sum()
    users = np.repeat(np.arange(1, n_users + 1, dtype=np.int32), per_user)
    movies = rng.choice(n_movies, size=n_users * per_user, p=weights).astype(np.int32) + 1
    ratings = pd.DataFrame({"userId": users, "movieId": movies})
    ratings = ratings.drop_duplicates(["userId", "movieId"]).reset_index(drop=True)
    ratings["rating"] = (rng.integers(1, 11, len(ratings)) / 2).astype(np.float32)
    movie_df = pd.DataFrame(
        {
            "movieId": np.arange(1, n_movies + 1, dtype=np.int32),
            "title": [f"Movie {i} (2000)" for i in range(1, n_movies + 1)],
            "genres": ["Drama"] * n_movies,
        }
    )
    links = pd.DataFrame(
        {
            "movieId": movie_df.movieId,
            "imdbId": movie_df.movieId,
            "tmdbId": pd.array(movie_df.movieId, dtype="Int32"),
        }
    )
    data = build_processed(ratings, movie_df, links)
    own = {
        int(m): int(rng.integers(0, 11)) for m in rng.choice(np.arange(1, 500), 200, replace=False)
    }
    cfg = RecommenderConfig()

    start = time.perf_counter()
    idx, vals = user_arrays(data, own)
    twins = compute_similarities(data.matrix, idx, vals, cfg)
    pred = predict_all(data, twins, float(vals.mean()), cfg)
    elapsed = time.perf_counter() - start

    assert len(twins) > 1000
    assert (pred.support >= cfg.min_support).sum() > 1000
    assert elapsed < 5.0, f"took {elapsed:.2f}s"
