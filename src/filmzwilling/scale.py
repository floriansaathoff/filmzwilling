"""Conversion between Florian's 0–10 notes and the MovieLens 0.5–5 star scale."""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray


def to_ml(note: int) -> float:
    """Convert an integer note 0–10 to MovieLens scale: ml = 0.5 + 0.45 * note."""
    raise NotImplementedError


def from_ml(ml: float) -> float:
    """Convert a MovieLens rating back to 0–10, clipped to the range."""
    raise NotImplementedError


def to_ml_array(notes: ArrayLike) -> NDArray[np.float64]:
    """Vectorised `to_ml` (validates like the scalar version)."""
    raise NotImplementedError


def from_ml_array(ml: ArrayLike) -> NDArray[np.float64]:
    """Vectorised `from_ml`."""
    raise NotImplementedError
