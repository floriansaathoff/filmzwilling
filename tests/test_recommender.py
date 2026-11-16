from __future__ import annotations

import numpy as np
import pytest

from filmzwilling.config import RecommenderConfig
from filmzwilling.movielens import ProcessedData
from filmzwilling.recommender import format_reason, predict_all, recommend, user_arrays
from filmzwilling.scale import to_ml
from filmzwilling.similarity import compute_similarities
from filmzwilling.synthetic import SyntheticDataset, synthetic_user_ratings


@pytest.fixture
def cluster0_ratings(synthetic_ds: SyntheticDataset) -> dict[int, int]:
    return synthetic_user_ratings(synthetic_ds, 0, n=60, seed=3)


def test_favorites_of_own_cluster_on_top(
    synthetic_data: ProcessedData, synthetic_ds: SyntheticDataset, config: RecommenderConfig
) -> None:
    for cluster in range(3):
        ratings = synthetic_user_ratings(synthetic_ds, cluster, n=60, seed=10 + cluster)
        result = recommend(synthetic_data, ratings, config)
        top = [r.movielens_id for r in result.recommendations[:10]]
        own = set(synthetic_ds.favorites[cluster])
        others = {m for c, ms in synthetic_ds.favorites.items() if c != cluster for m in ms}
        assert len(own & set(top)) >= 8, (cluster, top)
        assert not others & set(top)


def test_rated_and_excluded_movies_are_missing(
    synthetic_data: ProcessedData, cluster0_ratings: dict[int, int], config: RecommenderConfig
) -> None:
    excluded = {5, 6, 7}
    result = recommend(synthetic_data, cluster0_ratings, config, exclude_movie_ids=excluded)
    ids = {r.movielens_id for r in result.recommendations}
    assert not ids & set(cluster0_ratings)
    assert not ids & excluded
    assert ids  # still something left


def test_min_support_and_k(synthetic_data: ProcessedData, cluster0_ratings: dict[int, int]) -> None:
    cfg = RecommenderConfig(min_support=12, k=20)
    result = recommend(synthetic_data, cluster0_ratings, cfg)
    assert result.recommendations
    assert all(12 <= r.support <= 20 for r in result.recommendations)
    assert (
        recommend(
            synthetic_data, cluster0_ratings, RecommenderConfig(min_support=10_000)
        ).recommendations
        == []
    )
    small_k = recommend(synthetic_data, cluster0_ratings, RecommenderConfig(k=3, min_support=1))
    assert all(r.support <= 3 for r in small_k.recommendations)


def test_scores_in_range_with_one_decimal(
    synthetic_data: ProcessedData, cluster0_ratings: dict[int, int], config: RecommenderConfig
) -> None:
    result = recommend(synthetic_data, cluster0_ratings, config)
    for r in result.recommendations:
        assert 0.0 <= r.score <= 10.0
        assert r.score == round(r.score, 1)
        assert 0.0 <= r.twin_mean <= 10.0
        assert r.reason == format_reason(r.support, r.twin_mean)
    scores = [r.score for r in result.recommendations]
    assert scores == sorted(scores, reverse=True)


def test_deterministic(
    synthetic_data: ProcessedData, cluster0_ratings: dict[int, int], config: RecommenderConfig
) -> None:
    a = recommend(synthetic_data, cluster0_ratings, config)
    b = recommend(synthetic_data, dict(reversed(list(cluster0_ratings.items()))), config)
    assert a.recommendations == b.recommendations
    np.testing.assert_array_equal(a.twins.user_indices, b.twins.user_indices)


def test_limit_and_metadata(
    synthetic_data: ProcessedData, cluster0_ratings: dict[int, int], config: RecommenderConfig
) -> None:
    result = recommend(synthetic_data, cluster0_ratings, config, limit=7)
    assert len(result.recommendations) == 7
    assert result.n_used_ratings == len(cluster0_ratings)
    assert len(result.twins) > 0
    assert 0.5 <= result.user_mean <= 5.0


def test_unknown_movies_are_ignored(synthetic_data: ProcessedData) -> None:
    idx, vals = user_arrays(synthetic_data, {1: 10, 999_999: 3, 2: 0})
    assert list(vals) == [pytest.approx(5.0), pytest.approx(0.5)]
    assert list(synthetic_data.movie_ids[idx]) == [1, 2]


def test_exclude_users(
    synthetic_data: ProcessedData, cluster0_ratings: dict[int, int], config: RecommenderConfig
) -> None:
    base = recommend(synthetic_data, cluster0_ratings, config)
    top_twin = base.twins.user_indices[:1]
    res = recommend(synthetic_data, cluster0_ratings, config, exclude_users=top_twin)
    assert top_twin[0] not in set(res.twins.user_indices)


def test_format_reason() -> None:
    assert format_reason(23, 8.44) == "23 Zwillinge, im Schnitt 8,4"
    assert format_reason(1, 7.0) == "1 Zwilling, im Schnitt 7,0"
    assert format_reason(50, 10.0) == "50 Zwillinge, im Schnitt 10,0"


def naive_predictions(data: ProcessedData, twins, user_mean: float, cfg: RecommenderConfig):
    dense = data.matrix.toarray()
    coo = data.matrix.tocoo()
    present = np.zeros(dense.shape, dtype=bool)
    present[coo.row, coo.col] = True
    order = list(zip(twins.user_indices, twins.similarities, strict=True))
    support = np.zeros(data.n_movies, dtype=int)
    final = np.zeros(data.n_movies)
    twin_mean = np.full(data.n_movies, np.nan)
    for i in range(data.n_movies):
        chosen = [(int(v), float(s)) for v, s in order if present[v, i]][: cfg.k]
        support[i] = len(chosen)
        bias = (data.movie_means[i] - data.global_mean) if data.movie_counts[i] else 0.0
        prior = user_mean + bias
        if chosen:
            num = sum(s * dense[v, i] for v, s in chosen)
            den = sum(s for _, s in chosen)
            pred = user_mean + num / den
            twin_mean[i] = np.mean([dense[v, i] + data.user_means[v] for v, _ in chosen])
            final[i] = (len(chosen) * pred + cfg.prior_weight * prior) / (
                len(chosen) + cfg.prior_weight
            )
        else:
            final[i] = prior
    return support, final, twin_mean


def test_predict_all_matches_naive(
    synthetic_data: ProcessedData, cluster0_ratings: dict[int, int]
) -> None:
    cfg = RecommenderConfig(k=7)
    idx, vals = user_arrays(synthetic_data, cluster0_ratings)
    twins = compute_similarities(synthetic_data.matrix, idx, vals, cfg)
    user_mean = float(vals.mean())
    pred = predict_all(synthetic_data, twins, user_mean, cfg)
    support, final, twin_mean = naive_predictions(synthetic_data, twins, user_mean, cfg)
    np.testing.assert_array_equal(pred.support, support)
    np.testing.assert_allclose(pred.final_pred, final, rtol=1e-5, atol=1e-6)
    has = support > 0
    np.testing.assert_allclose(pred.twin_mean[has], twin_mean[has], rtol=1e-5)


def test_shrinkage_towards_prior(
    synthetic_data: ProcessedData, cluster0_ratings: dict[int, int]
) -> None:
    idx, vals = user_arrays(synthetic_data, cluster0_ratings)
    no_prior = RecommenderConfig(prior_weight=0.0)
    strong = RecommenderConfig(prior_weight=1000.0)
    twins = compute_similarities(synthetic_data.matrix, idx, vals, no_prior)
    mean = float(vals.mean())
    a = predict_all(synthetic_data, twins, mean, no_prior)
    b = predict_all(synthetic_data, twins, mean, strong)
    has = a.support > 0
    np.testing.assert_allclose(a.final_pred[has], a.raw_pred[has], rtol=1e-6)
    assert np.abs(b.final_pred[has] - b.prior[has]).max() < 0.1


def test_single_rating_user_has_no_twins(
    synthetic_data: ProcessedData, config: RecommenderConfig
) -> None:
    result = recommend(synthetic_data, {1: 8}, config)
    assert result.recommendations == []
    assert len(result.twins) == 0


def test_scale_consistency(synthetic_data: ProcessedData, cluster0_ratings: dict[int, int]) -> None:
    """A user rating everything 10 yields predictions near the top of the scale."""
    high = {m: 10 for m in list(cluster0_ratings)[:30]}
    high.update({m: 9 for m in list(cluster0_ratings)[30:]})
    res = recommend(synthetic_data, high, RecommenderConfig())
    assert res.user_mean == pytest.approx(np.mean([to_ml(n) for n in high.values()]))
