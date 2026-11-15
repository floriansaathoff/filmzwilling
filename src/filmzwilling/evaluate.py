"""Self-test: cross-validation over the user's own ratings against a movie-mean baseline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from filmzwilling.config import RecommenderConfig
from filmzwilling.movielens import ProcessedData


@dataclass(frozen=True)
class EvalResult:
    n_ratings: int
    folds: int
    rmse: float
    spearman: float
    baseline_rmse: float
    baseline_spearman: float
    coverage: float

    @property
    def improvement(self) -> float:
        """Relative RMSE improvement over the baseline (0.2 = 20 % better)."""
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["improvement"] = self.improvement
        return d


def predict_hidden(
    data: ProcessedData,
    train: Mapping[int, int],
    hidden_ids: list[int],
    config: RecommenderConfig,
    exclude_users: NDArray[np.int64] | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.bool_]]:
    """Return (model predictions, baseline predictions, has_support) on the 0–10 scale."""
    raise NotImplementedError


def holdout_evaluate(
    data: ProcessedData,
    user_ratings: Mapping[int, int],
    config: RecommenderConfig,
    *,
    fraction: float = 0.2,
    seed: int = 42,
    exclude_users: NDArray[np.int64] | None = None,
) -> EvalResult:
    raise NotImplementedError


def cross_validate(
    data: ProcessedData,
    user_ratings: Mapping[int, int],
    config: RecommenderConfig,
    *,
    folds: int = 5,
    seed: int = 42,
    exclude_users: NDArray[np.int64] | None = None,
) -> EvalResult:
    """k-fold CV (each fold hides 1/folds of the ratings)."""
    raise NotImplementedError
