"""Predictions from the k most similar twins per movie, with shrinkage to the movie mean."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from filmzwilling.config import RecommenderConfig
from filmzwilling.movielens import ProcessedData
from filmzwilling.similarity import TwinResult


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
    raise NotImplementedError


def user_arrays(
    data: ProcessedData, user_ratings: Mapping[int, int]
) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
    """Map {movielens_id: note} to (column indices, ML-scale ratings), skipping unknown ids."""
    raise NotImplementedError


def predict_all(
    data: ProcessedData, twins: TwinResult, user_mean: float, config: RecommenderConfig
) -> Predictions:
    """Predict every movie column from its k most similar twins (vectorised)."""
    raise NotImplementedError


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
    raise NotImplementedError
