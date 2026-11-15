"""Checks against the real MovieLens 32M data in ./data.

Run with: FILMZWILLING_REAL_DATA=1 pytest -m real_data -s
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from filmzwilling.config import RecommenderConfig, load_settings
from filmzwilling.evaluate import holdout_evaluate
from filmzwilling.movielens import is_processed, load_processed
from filmzwilling.scale import from_ml

pytestmark = [
    pytest.mark.real_data,
    pytest.mark.skipif(
        os.environ.get("FILMZWILLING_REAL_DATA") != "1", reason="FILMZWILLING_REAL_DATA=1 fehlt"
    ),
]


@pytest.fixture(scope="module")
def real_data():
    settings = load_settings()
    processed = settings.processed_dir
    if not (Path(processed) / "meta.json").exists():
        pytest.skip("data/processed fehlt, zuerst 'filmzwilling setup' ausführen")
    start = time.perf_counter()
    data = load_processed(processed)
    print(
        f"\nload_processed: {time.perf_counter() - start:.1f}s, users={data.n_users}, "
        f"movies={data.n_movies}, nnz={data.matrix.nnz}"
    )
    return data


def test_processed_metadata(real_data) -> None:
    assert real_data.matrix.nnz == 32_000_204
    assert real_data.n_users == 200_948
    settings = load_settings()
    assert is_processed(settings.processed_dir, "d472be332d4daa821edc399621853b57")


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_test_florian_beats_baseline(real_data, seed: int) -> None:
    """A real user with >= 300 ratings acts as Florian: removed from the matrix, 20 % hidden."""
    counts = np.diff(real_data.matrix.indptr)
    rng = np.random.default_rng(seed)
    candidates = np.flatnonzero((counts >= 300) & (counts <= 800))
    user = int(rng.choice(candidates))
    row = real_data.matrix.getrow(user)
    ml = row.data + real_data.user_means[user]
    notes = np.clip(np.rint([from_ml(float(v)) for v in ml]), 0, 10).astype(int)
    ratings = {int(real_data.movie_ids[c]): int(n) for c, n in zip(row.indices, notes, strict=True)}
    start = time.perf_counter()
    res = holdout_evaluate(
        real_data,
        ratings,
        RecommenderConfig(),
        fraction=0.2,
        seed=seed,
        exclude_users=np.array([user]),
    )
    elapsed = time.perf_counter() - start
    print(
        f"\nuser={int(real_data.user_ids[user])} n={len(ratings)} rmse={res.rmse:.3f} "
        f"baseline={res.baseline_rmse:.3f} spearman={res.spearman:.3f} "
        f"baseline_spearman={res.baseline_spearman:.3f} coverage={res.coverage:.2f} "
        f"time={elapsed:.1f}s"
    )
    assert res.rmse < res.baseline_rmse
    assert res.spearman > res.baseline_spearman
