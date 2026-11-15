from __future__ import annotations

import math

import pytest

from filmzwilling.config import RecommenderConfig
from filmzwilling.evaluate import EvalResult, cross_validate, holdout_evaluate
from filmzwilling.movielens import ProcessedData
from filmzwilling.synthetic import SyntheticDataset, synthetic_user_ratings


@pytest.fixture
def mixed_ratings(synthetic_ds: SyntheticDataset) -> dict[int, int]:
    return synthetic_user_ratings(synthetic_ds, 1, n=120, seed=7, include_favorites=True)


def test_quality_gate_holdout(
    synthetic_data: ProcessedData, mixed_ratings: dict[int, int], config: RecommenderConfig
) -> None:
    res = holdout_evaluate(synthetic_data, mixed_ratings, config, fraction=0.2, seed=1)
    assert res.n_ratings == 24
    assert res.rmse <= 0.85 * res.baseline_rmse, res
    assert res.spearman > res.baseline_spearman
    assert res.improvement >= 0.15


def test_cross_validation(
    synthetic_data: ProcessedData, mixed_ratings: dict[int, int], config: RecommenderConfig
) -> None:
    res = cross_validate(synthetic_data, mixed_ratings, config, folds=5, seed=3)
    assert res.folds == 5
    assert res.n_ratings == len(mixed_ratings)
    assert 0.0 <= res.coverage <= 1.0
    for value in (res.rmse, res.spearman, res.baseline_rmse, res.baseline_spearman):
        assert math.isfinite(value)
    assert res.rmse < res.baseline_rmse
    again = cross_validate(synthetic_data, mixed_ratings, config, folds=5, seed=3)
    assert again == res


def test_too_few_ratings(synthetic_data: ProcessedData, config: RecommenderConfig) -> None:
    with pytest.raises(ValueError):
        cross_validate(synthetic_data, {1: 5, 2: 6, 3: 7}, config, folds=5)


def test_eval_result_dict() -> None:
    r = EvalResult(
        n_ratings=10,
        folds=5,
        rmse=1.0,
        spearman=0.5,
        baseline_rmse=2.0,
        baseline_spearman=0.1,
        coverage=0.9,
    )
    assert r.improvement == pytest.approx(0.5)
    d = r.to_dict()
    assert d["improvement"] == pytest.approx(0.5)
    assert d["rmse"] == 1.0
    zero = EvalResult(
        n_ratings=1,
        folds=5,
        rmse=1.0,
        spearman=0.0,
        baseline_rmse=0.0,
        baseline_spearman=0.0,
        coverage=0.0,
    )
    assert zero.improvement == 0.0
