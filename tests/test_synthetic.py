from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from filmzwilling.synthetic import generate_dataset, synthetic_user_ratings, write_csvs, write_zip


def test_reproducible() -> None:
    a = generate_dataset(n_users=50, n_movies=60, seed=3)
    b = generate_dataset(n_users=50, n_movies=60, seed=3)
    c = generate_dataset(n_users=50, n_movies=60, seed=4)
    pd.testing.assert_frame_equal(a.ratings, b.ratings)
    assert not a.ratings.equals(c.ratings)
    assert a.favorites == b.favorites


def test_shapes_and_ranges() -> None:
    ds = generate_dataset(n_users=80, n_movies=90, n_clusters=3, seed=1)
    assert ds.ratings.userId.nunique() == 80
    assert ds.ratings.rating.between(0.5, 5.0).all()
    assert ((ds.ratings.rating * 2) % 1 == 0).all()
    assert not ds.ratings.duplicated(["userId", "movieId"]).any()
    assert len(ds.movies) == 90
    assert ds.links.tmdbId.isna().sum() >= 0
    assert set(ds.favorites) == {0, 1, 2}


def test_favorites_are_loved_by_own_cluster() -> None:
    ds = generate_dataset(seed=11)
    r = ds.ratings.merge(
        pd.DataFrame(
            {"userId": np.arange(1, len(ds.user_clusters) + 1), "cluster": ds.user_clusters}
        )
    )
    for c, favs in ds.favorites.items():
        sub = r[r.movieId.isin(favs)]
        own = sub[sub.cluster == c].rating.mean()
        other = sub[sub.cluster != c].rating.mean()
        assert own > other + 1.5


def test_synthetic_user_ratings() -> None:
    ds = generate_dataset(seed=2)
    ratings = synthetic_user_ratings(ds, 0, n=40, seed=1)
    assert len(ratings) == 40
    assert not set(ratings) & set(ds.favorites[0])
    assert all(isinstance(v, int) and 0 <= v <= 10 for v in ratings.values())
    with_favs = synthetic_user_ratings(ds, 0, n=200, seed=1, include_favorites=True)
    assert set(ds.favorites[0]) <= set(with_favs)
    assert synthetic_user_ratings(ds, 0, n=40, seed=1) == ratings


def test_writers(tmp_path: Path) -> None:
    ds = generate_dataset(n_users=20, n_movies=30, n_favorites=3, seed=1)
    d = write_csvs(ds, tmp_path / "csv")
    assert (d / "ratings.csv").read_text().startswith("userId,movieId,rating,timestamp")
    z = write_zip(ds, tmp_path / "ml.zip")
    with zipfile.ZipFile(z) as zf:
        assert {"ml-32m/ratings.csv", "ml-32m/movies.csv", "ml-32m/links.csv"} <= set(zf.namelist())


def test_invalid_parameters() -> None:
    with pytest.raises(ValueError):
        generate_dataset(n_clusters=9)
    with pytest.raises(ValueError):
        generate_dataset(n_movies=20, n_favorites=10)
