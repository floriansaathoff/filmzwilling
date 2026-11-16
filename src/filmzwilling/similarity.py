"""Taste twins: adjusted cosine similarity over co-rated movies, fully vectorised."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import sparse

from filmzwilling.config import RecommenderConfig

_EPS = 1e-12


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

    @classmethod
    def empty(cls) -> TwinResult:
        return cls(
            user_indices=np.zeros(0, dtype=np.int64),
            similarities=np.zeros(0, dtype=np.float64),
            raw_similarities=np.zeros(0, dtype=np.float64),
            overlaps=np.zeros(0, dtype=np.int64),
        )


def build_user_vector(
    n_movies: int, movie_indices: NDArray[np.int64], ml_ratings: NDArray[np.float64]
) -> UserVector:
    """Dense centered rating vector and indicator for the active user."""
    idx = np.asarray(movie_indices, dtype=np.int64)
    vals = np.asarray(ml_ratings, dtype=np.float64)
    mean = float(vals.mean()) if vals.size else 0.0
    centered = np.zeros(n_movies, dtype=np.float64)
    indicator = np.zeros(n_movies, dtype=np.float64)
    centered[idx] = vals - mean
    indicator[idx] = 1.0
    return UserVector(centered=centered, indicator=indicator, mean=mean)


def _matvec(
    matrix: sparse.csr_matrix, data: NDArray[np.float32], vector: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Multiply a matrix with the sparsity pattern of `matrix` but other values by a vector."""
    view = sparse.csr_matrix((data, matrix.indices, matrix.indptr), shape=matrix.shape, copy=False)
    return np.asarray(view @ vector, dtype=np.float64).ravel()


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
    n_users, n_movies = matrix.shape
    if len(movie_indices) == 0 or n_users == 0:
        return TwinResult.empty()
    vec = build_user_vector(n_movies, movie_indices, ml_ratings)
    data = np.asarray(matrix.data, dtype=np.float32)
    ones = np.ones_like(data)

    numerator = np.asarray(matrix @ vec.centered, dtype=np.float64).ravel()
    sum_u2 = _matvec(matrix, ones, vec.centered * vec.centered)
    sum_r2 = _matvec(matrix, data * data, vec.indicator)
    overlap = np.rint(_matvec(matrix, ones, vec.indicator)).astype(np.int64)

    valid = (overlap >= config.min_overlap) & (sum_u2 > _EPS) & (sum_r2 > _EPS)
    raw = np.zeros(n_users, dtype=np.float64)
    raw[valid] = numerator[valid] / np.sqrt(sum_u2[valid] * sum_r2[valid])
    keep = valid & (raw > _EPS)
    if exclude_users is not None and len(exclude_users):
        keep[np.asarray(exclude_users, dtype=np.int64)] = False

    users = np.flatnonzero(keep).astype(np.int64)
    n = overlap[users]
    weighted = raw[users] * n / (n + config.shrinkage)
    order = np.lexsort((users, -weighted))
    return TwinResult(
        user_indices=users[order],
        similarities=weighted[order],
        raw_similarities=raw[users][order],
        overlaps=n[order],
    )
