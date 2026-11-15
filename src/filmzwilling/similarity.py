"""Taste twins: adjusted cosine similarity over co-rated movies, fully vectorised."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import sparse

from filmzwilling.config import RecommenderConfig


@dataclass(frozen=True)
class UserVector:
    """The active user's ratings as dense vectors over all movie columns."""

    centered: NDArray[np.float64]
    indicator: NDArray[np.float64]
    mean: float


@dataclass(frozen=True)
class TwinResult:
    """Twins sorted by weighted similarity (descending)."""

    user_indices: NDArray[np.int64]
    similarities: NDArray[np.float64]
    raw_similarities: NDArray[np.float64]
    overlaps: NDArray[np.int64]

    def __len__(self) -> int:
        return int(self.user_indices.shape[0])


def build_user_vector(
    n_movies: int, movie_indices: NDArray[np.int64], ml_ratings: NDArray[np.float64]
) -> UserVector:
    """Dense centered rating vector and indicator for the active user."""
    raise NotImplementedError


def compute_similarities(
    matrix: sparse.csr_matrix,
    movie_indices: NDArray[np.int64],
    ml_ratings: NDArray[np.float64],
    config: RecommenderConfig,
    exclude_users: NDArray[np.int64] | None = None,
) -> TwinResult:
    """Adjusted cosine with significance weighting sim * n / (n + shrinkage).

    `matrix` holds mean-centered ratings (users x movies). Users with overlap < min_overlap or
    similarity <= 0 are dropped.
    """
    raise NotImplementedError
