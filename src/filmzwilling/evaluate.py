"""Self-test: cross-validation over the user's own ratings against a movie-mean baseline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.stats import spearmanr

from filmzwilling.config import RecommenderConfig
from filmzwilling.movielens import ProcessedData
from filmzwilling.recommender import predict_all, user_arrays
from filmzwilling.scale import from_ml_array
from filmzwilling.similarity import compute_similarities


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
        if self.baseline_rmse <= 0:
            return 0.0
        return 1.0 - self.rmse / self.baseline_rmse

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["improvement"] = self.improvement
        return d


def _spearman(a: NDArray[np.float64], b: NDArray[np.float64]) -> float:
    if a.size < 2 or np.all(a == a[0]) or np.all(b == b[0]):
        return 0.0
    value = float(spearmanr(a, b).statistic)
    return value if np.isfinite(value) else 0.0


def predict_hidden(
    data: ProcessedData,
    train: Mapping[int, int],
    hidden_ids: list[int],
    config: RecommenderConfig,
    exclude_users: NDArray[np.int64] | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.bool_]]:
    """Return (model predictions, baseline predictions, has_support) on the 0–10 scale."""
    cols, vals = user_arrays(data, train)
    user_mean = float(vals.mean()) if vals.size else data.global_mean
    twins = compute_similarities(data.matrix, cols, vals, config, exclude_users)
    pred = predict_all(data, twins, user_mean, config)
    index = data.movie_index
    hidden_cols = np.array([index[int(m)] for m in hidden_ids], dtype=np.int64)
    has_support = pred.support[hidden_cols] >= config.min_support
    model_ml = np.where(has_support, pred.final_pred[hidden_cols], pred.prior[hidden_cols])
    counts = data.movie_counts[hidden_cols]
    baseline_ml = np.where(counts > 0, data.movie_means[hidden_cols], data.global_mean)
    return from_ml_array(model_ml), from_ml_array(baseline_ml.astype(np.float64)), has_support


def _metrics(
    actual: NDArray[np.float64],
    model: NDArray[np.float64],
    baseline: NDArray[np.float64],
    has_support: NDArray[np.bool_],
    folds: int,
) -> EvalResult:
    return EvalResult(
        n_ratings=int(actual.size),
        folds=folds,
        rmse=float(np.sqrt(np.mean((model - actual) ** 2))),
        spearman=_spearman(model, actual),
        baseline_rmse=float(np.sqrt(np.mean((baseline - actual) ** 2))),
        baseline_spearman=_spearman(baseline, actual),
        coverage=float(np.mean(has_support)) if has_support.size else 0.0,
    )


def _known_items(data: ProcessedData, user_ratings: Mapping[int, int]) -> list[int]:
    index = data.movie_index
    return sorted(int(m) for m in user_ratings if int(m) in index)


def holdout_evaluate(
    data: ProcessedData,
    user_ratings: Mapping[int, int],
    config: RecommenderConfig,
    *,
    fraction: float = 0.2,
    seed: int = 42,
    exclude_users: NDArray[np.int64] | None = None,
) -> EvalResult:
    items = _known_items(data, user_ratings)
    if len(items) < 5:
        raise ValueError("Zu wenige Bewertungen mit MovieLens-ID für eine Auswertung")
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(items))
    n_hidden = max(1, round(fraction * len(items)))
    hidden = [items[i] for i in perm[:n_hidden]]
    train = {items[i]: user_ratings[items[i]] for i in perm[n_hidden:]}
    model, baseline, has = predict_hidden(data, train, hidden, config, exclude_users)
    actual = np.array([user_ratings[m] for m in hidden], dtype=np.float64)
    return _metrics(actual, model, baseline, has, folds=1)


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
    items = _known_items(data, user_ratings)
    if folds < 2 or len(items) < 2 * folds:
        raise ValueError(
            f"Zu wenige Bewertungen mit MovieLens-ID für {folds}-fache Kreuzvalidierung "
            f"(mindestens {2 * max(folds, 2)} nötig, vorhanden {len(items)})"
        )
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(items))
    actual_parts: list[NDArray[np.float64]] = []
    model_parts: list[NDArray[np.float64]] = []
    base_parts: list[NDArray[np.float64]] = []
    has_parts: list[NDArray[np.bool_]] = []
    for fold in np.array_split(perm, folds):
        hidden = [items[i] for i in fold]
        hidden_set = set(hidden)
        train = {m: user_ratings[m] for m in items if m not in hidden_set}
        model, baseline, has = predict_hidden(data, train, hidden, config, exclude_users)
        actual_parts.append(np.array([user_ratings[m] for m in hidden], dtype=np.float64))
        model_parts.append(model)
        base_parts.append(baseline)
        has_parts.append(has)
    return _metrics(
        np.concatenate(actual_parts),
        np.concatenate(model_parts),
        np.concatenate(base_parts),
        np.concatenate(has_parts),
        folds=folds,
    )
