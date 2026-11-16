"""Predictions from the k most similar twins per movie, with shrinkage to the movie mean."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import sparse

from filmzwilling.config import RecommenderConfig
from filmzwilling.movielens import ProcessedData
from filmzwilling.scale import from_ml_array, to_ml
from filmzwilling.similarity import TwinResult, compute_similarities


@dataclass(frozen=True)
class Predictions:
    """Per-movie-column prediction arrays (ML scale)."""

    support: NDArray[np.int64]
    raw_pred: NDArray[np.float64]
    final_pred: NDArray[np.float64]
    twin_mean: NDArray[np.float64]
    prior: NDArray[np.float64]


@dataclass(frozen=True)
class Recommendation:
    movielens_id: int
    score: float
    support: int
    twin_mean: float
    reason: str


@dataclass(frozen=True)
class RecommendationResult:
    recommendations: list[Recommendation]
    twins: TwinResult
    user_mean: float
    n_used_ratings: int


def format_reason(support: int, twin_mean: float) -> str:
    """German short explanation, e.g. "23 Zwillinge, im Schnitt 8,4"."""
    noun = "Zwilling" if support == 1 else "Zwillinge"
    mean_text = f"{twin_mean:.1f}".replace(".", ",")
    return f"{support} {noun}, im Schnitt {mean_text}"


def user_arrays(
    data: ProcessedData, user_ratings: Mapping[int, int]
) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
    """Map {movielens_id: note} to (column indices, ML-scale ratings), skipping unknown ids."""
    index = data.movie_index
    pairs = sorted(
        (index[int(movie_id)], to_ml(note))
        for movie_id, note in user_ratings.items()
        if int(movie_id) in index
    )
    cols = np.array([p[0] for p in pairs], dtype=np.int64)
    vals = np.array([p[1] for p in pairs], dtype=np.float64)
    return cols, vals


def predict_all(
    data: ProcessedData, twins: TwinResult, user_mean: float, config: RecommenderConfig
) -> Predictions:
    """Predict every movie column from its k most similar twins (vectorised)."""
    n_movies = data.n_movies
    counts = data.movie_counts.astype(np.int64)
    bias = np.where(counts > 0, data.movie_means.astype(np.float64) - data.global_mean, 0.0)
    prior = user_mean + bias
    support = np.zeros(n_movies, dtype=np.int64)
    raw_pred = np.full(n_movies, np.nan)
    twin_mean = np.full(n_movies, np.nan)
    if len(twins) == 0:
        return Predictions(support, raw_pred, prior.copy(), twin_mean, prior)

    # Rows of the twins in similarity order; in CSC each column lists twins by rank.
    sub = data.matrix[twins.user_indices]
    csc = sparse.csc_matrix(sub)
    if not csc.has_sorted_indices:
        csc.sort_indices()
    per_column = np.diff(csc.indptr)
    col_of_entry = np.repeat(np.arange(n_movies, dtype=np.int32), per_column)
    position = np.arange(csc.nnz, dtype=np.int64) - csc.indptr[col_of_entry]
    take = position < config.k
    ranks = csc.indices[take].astype(np.int64)
    cols = col_of_entry[take]
    centered = csc.data[take].astype(np.float64)
    del csc, sub, position, col_of_entry

    sims = twins.similarities[ranks]
    raw_ratings = centered + data.user_means[twins.user_indices[ranks]].astype(np.float64)
    support = np.bincount(cols, minlength=n_movies).astype(np.int64)
    sum_sim = np.bincount(cols, weights=sims, minlength=n_movies)
    sum_weighted = np.bincount(cols, weights=sims * centered, minlength=n_movies)
    sum_raw = np.bincount(cols, weights=raw_ratings, minlength=n_movies)

    has = (support > 0) & (sum_sim > 0)
    raw_pred[has] = user_mean + sum_weighted[has] / sum_sim[has]
    twin_mean[has] = sum_raw[has] / support[has]
    final = prior.copy()
    weight = support[has].astype(np.float64)
    denominator = weight + config.prior_weight
    final[has] = (weight * raw_pred[has] + config.prior_weight * prior[has]) / denominator
    return Predictions(support, raw_pred, final, twin_mean, prior)


def recommend(
    data: ProcessedData,
    user_ratings: Mapping[int, int],
    config: RecommenderConfig,
    *,
    exclude_movie_ids: Iterable[int] = (),
    exclude_users: NDArray[np.int64] | None = None,
    limit: int | None = None,
) -> RecommendationResult:
    """Compute recommendations sorted by predicted note (descending)."""
    cols, vals = user_arrays(data, user_ratings)
    user_mean = float(vals.mean()) if vals.size else data.global_mean
    twins = compute_similarities(data.matrix, cols, vals, config, exclude_users)
    pred = predict_all(data, twins, user_mean, config)

    candidate = pred.support >= config.min_support
    candidate[cols] = False
    index = data.movie_index
    excluded = [index[int(m)] for m in exclude_movie_ids if int(m) in index]
    if excluded:
        candidate[np.array(excluded, dtype=np.int64)] = False
    chosen = np.flatnonzero(candidate)
    order = np.lexsort((data.movie_ids[chosen], -pred.final_pred[chosen]))
    chosen = chosen[order]
    if limit is not None:
        chosen = chosen[:limit]

    scores = np.round(from_ml_array(pred.final_pred[chosen]), 1)
    means = np.round(from_ml_array(pred.twin_mean[chosen]), 1)
    recs = [
        Recommendation(
            movielens_id=int(data.movie_ids[c]),
            score=float(s),
            support=int(pred.support[c]),
            twin_mean=float(m),
            reason=format_reason(int(pred.support[c]), float(m)),
        )
        for c, s, m in zip(chosen, scores, means, strict=True)
    ]
    return RecommendationResult(
        recommendations=recs, twins=twins, user_mean=user_mean, n_used_ratings=int(cols.size)
    )
