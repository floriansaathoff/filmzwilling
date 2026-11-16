from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from filmzwilling.config import RecommenderConfig
from filmzwilling.movielens import ProcessedData, build_processed
from filmzwilling.scale import to_ml
from filmzwilling.similarity import build_user_vector, compute_similarities


def make_data(rows: list[tuple[int, int, float]], n_movies: int) -> ProcessedData:
    ratings = pd.DataFrame(rows, columns=["userId", "movieId", "rating"]).astype(
        {"userId": "int32", "movieId": "int32", "rating": "float32"}
    )
    movies = pd.DataFrame(
        {
            "movieId": np.arange(1, n_movies + 1, dtype=np.int32),
            "title": [f"M{i} (2000)" for i in range(1, n_movies + 1)],
            "genres": ["Drama"] * n_movies,
        }
    )
    links = pd.DataFrame(
        {
            "movieId": np.arange(1, n_movies + 1, dtype=np.int32),
            "imdbId": np.arange(1, n_movies + 1),
            "tmdbId": pd.array(np.arange(1, n_movies + 1), dtype="Int32"),
        }
    )
    return build_processed(ratings, movies, links)


def florian(notes: list[int]) -> tuple[np.ndarray, np.ndarray]:
    idx = np.arange(len(notes), dtype=np.int64)
    return idx, np.array([to_ml(n) for n in notes], dtype=np.float64)


NOTES = [9, 2, 7, 4, 10, 1, 6, 8, 3, 5, 9, 0, 7, 2, 8, 4, 6, 10, 3, 5]


def twin_rows(user_id: int, ml_values: list[float]) -> list[tuple[int, int, float]]:
    return [(user_id, i + 1, v) for i, v in enumerate(ml_values)]


def sim_by_user(data: ProcessedData, result) -> dict[int, float]:
    return {
        int(data.user_ids[u]): float(s)
        for u, s in zip(result.user_indices, result.similarities, strict=True)
    }


def test_identical_taste_is_about_one() -> None:
    idx, vals = florian(NOTES)
    data = make_data(twin_rows(1, list(vals)) + twin_rows(2, list(vals[::-1])), 20)
    res = compute_similarities(data.matrix, idx, vals, RecommenderConfig())
    pos = list(data.user_ids[res.user_indices]).index(1)
    assert res.raw_similarities[pos] == pytest.approx(1.0, abs=1e-6)
    assert res.overlaps[pos] == 20
    assert res.similarities[pos] == pytest.approx(20 / (20 + 25), abs=1e-6)


def test_shift_by_one_note_gives_same_similarity() -> None:
    idx, vals = florian(NOTES)
    rng = np.random.default_rng(0)
    other = list(np.clip(vals + rng.normal(0, 0.6, len(vals)), 0.5, 5.0))
    shifted_twin = list(np.array(other) + 0.45)  # same taste, every note one point higher
    data = make_data(twin_rows(1, other) + twin_rows(2, shifted_twin), 20)
    res = compute_similarities(data.matrix, idx, vals, RecommenderConfig())
    sims = sim_by_user(data, res)
    assert sims[1] == pytest.approx(sims[2], abs=1e-6)


def test_shifting_own_notes_gives_same_similarity() -> None:
    notes = [n for n in NOTES if n < 10]
    shifted = [n + 1 for n in notes]
    rng = np.random.default_rng(4)
    idx, vals = florian(notes)
    _, vals_shifted = florian(shifted)
    twin = list(np.clip(vals + rng.normal(0, 0.5, len(vals)), 0.5, 5.0))
    data = make_data(twin_rows(1, twin) + twin_rows(2, list(rng.uniform(0.5, 5, len(vals)))), 20)
    res_a = compute_similarities(data.matrix, idx, vals, RecommenderConfig())
    res_b = compute_similarities(data.matrix, idx, vals_shifted, RecommenderConfig())
    np.testing.assert_array_equal(res_a.user_indices, res_b.user_indices)
    np.testing.assert_allclose(res_a.similarities, res_b.similarities, atol=1e-9)


def test_opposite_taste_is_excluded() -> None:
    idx, vals = florian(NOTES)
    opposite = list(5.5 - vals)
    data = make_data(twin_rows(1, list(vals)) + twin_rows(2, opposite), 20)
    res = compute_similarities(data.matrix, idx, vals, RecommenderConfig())
    assert set(data.user_ids[res.user_indices]) == {1}
    assert all(res.similarities > 0)


def test_too_small_overlap_is_excluded() -> None:
    idx, vals = florian(NOTES)
    rows = twin_rows(1, list(vals[:9])) + twin_rows(2, list(vals[:10]))
    data = make_data(rows, 20)
    res = compute_similarities(data.matrix, idx, vals, RecommenderConfig(min_overlap=10))
    assert set(data.user_ids[res.user_indices]) == {2}
    res5 = compute_similarities(data.matrix, idx, vals, RecommenderConfig(min_overlap=5))
    assert set(data.user_ids[res5.user_indices]) == {1, 2}


def test_significance_weighting_lowers_small_overlap() -> None:
    idx, vals = florian(NOTES)
    rows = twin_rows(1, list(vals[:10])) + twin_rows(2, list(vals))
    data = make_data(rows, 20)
    res = compute_similarities(data.matrix, idx, vals, RecommenderConfig())
    sims = sim_by_user(data, res)
    raw = {
        int(data.user_ids[u]): float(s)
        for u, s in zip(res.user_indices, res.raw_similarities, strict=True)
    }
    assert sims[1] < sims[2]
    assert sims[1] == pytest.approx(raw[1] * 10 / 35, rel=1e-6)
    assert sims[2] == pytest.approx(raw[2] * 20 / 45, rel=1e-6)


def test_sorted_descending_and_exclusion() -> None:
    rng = np.random.default_rng(1)
    rows = []
    for u in range(1, 31):
        for m in rng.choice(20, size=15, replace=False):
            rows.append((u, int(m) + 1, float(rng.integers(1, 11)) / 2))
    data = make_data(rows, 20)
    idx, vals = florian(NOTES)
    res = compute_similarities(data.matrix, idx, vals, RecommenderConfig())
    assert len(res) > 0
    assert all(np.diff(res.similarities) <= 1e-12)
    excluded = res.user_indices[:3]
    res2 = compute_similarities(data.matrix, idx, vals, RecommenderConfig(), exclude_users=excluded)
    assert not set(excluded) & set(res2.user_indices)
    assert len(res2) == len(res) - 3


def test_constant_ratings_do_not_produce_nan() -> None:
    idx, vals = florian([5] * 20)
    data = make_data(twin_rows(1, list(np.linspace(1, 5, 20))), 20)
    res = compute_similarities(data.matrix, idx, vals, RecommenderConfig())
    assert len(res) == 0
    idx2, vals2 = florian(NOTES)
    data2 = make_data(twin_rows(1, [3.0] * 20) + twin_rows(2, list(vals2)), 20)
    res2 = compute_similarities(data2.matrix, idx2, vals2, RecommenderConfig())
    assert set(data2.user_ids[res2.user_indices]) == {2}
    assert not np.isnan(res2.similarities).any()


def test_build_user_vector() -> None:
    idx = np.array([0, 3], dtype=np.int64)
    vals = np.array([4.0, 2.0])
    vec = build_user_vector(5, idx, vals)
    assert vec.mean == pytest.approx(3.0)
    np.testing.assert_allclose(vec.centered, [1.0, 0, 0, -1.0, 0])
    np.testing.assert_allclose(vec.indicator, [1, 0, 0, 1, 0])


def naive_similarities(
    data: ProcessedData, idx: np.ndarray, vals: np.ndarray, cfg: RecommenderConfig
) -> dict[int, tuple[float, int]]:
    """Reference implementation with plain Python loops."""
    mean_u = float(np.mean(vals))
    u = {int(i): float(v) - mean_u for i, v in zip(idx, vals, strict=True)}
    dense = data.matrix.toarray()
    present = np.zeros(dense.shape, dtype=bool)
    m = data.matrix.tocoo()
    present[m.row, m.col] = True
    out: dict[int, tuple[float, int]] = {}
    for v in range(dense.shape[0]):
        num = su = sv = 0.0
        n = 0
        for i, cu in u.items():
            if present[v, i]:
                r = float(dense[v, i])
                num += cu * r
                su += cu * cu
                sv += r * r
                n += 1
        if n < cfg.min_overlap or su == 0 or sv == 0:
            continue
        sim = num / (math.sqrt(su) * math.sqrt(sv))
        if sim <= 0:
            continue
        out[v] = (sim * n / (n + cfg.shrinkage), n)
    return out


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_matches_naive_reference(seed: int) -> None:
    rng = np.random.default_rng(seed)
    n_users, n_movies = 60, 40
    rows = []
    for user in range(1, n_users + 1):
        k = int(rng.integers(8, 35))
        for movie in rng.choice(n_movies, size=k, replace=False):
            rows.append((user, int(movie) + 1, float(rng.integers(1, 11)) / 2))
    data = make_data(rows, n_movies)
    notes = rng.integers(0, 11, 25)
    idx = rng.choice(n_movies, size=25, replace=False).astype(np.int64)
    vals = np.array([to_ml(int(n)) for n in notes])
    cfg = RecommenderConfig(min_overlap=5)
    res = compute_similarities(data.matrix, idx, vals, cfg)
    ref = naive_similarities(data, idx, vals, cfg)
    got = {
        int(u): (float(s), int(n))
        for u, s, n in zip(res.user_indices, res.similarities, res.overlaps, strict=True)
    }
    assert set(got) == set(ref)
    for user, (sim, n) in ref.items():
        assert got[user][0] == pytest.approx(sim, rel=1e-5, abs=1e-7)
        assert got[user][1] == n
