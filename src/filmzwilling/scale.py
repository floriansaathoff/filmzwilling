"""Conversion between Florian's 0–10 notes and the MovieLens 0.5–5 star scale."""

from __future__ import annotations

import math
import numbers

import numpy as np
from numpy.typing import ArrayLike, NDArray

MIN_NOTE = 0
MAX_NOTE = 10
OFFSET = 0.5
FACTOR = 0.45


def validate_note(note: object) -> int:
    """Return the note as int or raise ValueError (only whole numbers 0–10 are valid)."""
    if isinstance(note, bool) or not isinstance(note, numbers.Real):
        raise ValueError(f"Note muss eine ganze Zahl von 0 bis 10 sein, nicht {note!r}")
    value = float(note)
    if not math.isfinite(value) or not value.is_integer():
        raise ValueError(f"Note muss eine ganze Zahl von 0 bis 10 sein, nicht {note!r}")
    if not MIN_NOTE <= value <= MAX_NOTE:
        raise ValueError(f"Note muss zwischen 0 und 10 liegen, nicht {note!r}")
    return int(value)


def to_ml(note: int) -> float:
    """Convert an integer note 0–10 to MovieLens scale: ml = 0.5 + 0.45 * note."""
    return OFFSET + FACTOR * validate_note(note)


def from_ml(ml: float) -> float:
    """Convert a MovieLens rating back to 0–10, clipped to the range."""
    value = (float(ml) - OFFSET) / FACTOR
    return float(min(max(value, MIN_NOTE), MAX_NOTE))


def to_ml_array(notes: ArrayLike) -> NDArray[np.float64]:
    """Vectorised `to_ml` (validates like the scalar version)."""
    arr = np.asarray(notes, dtype=np.float64)
    if arr.size and (
        not np.all(np.isfinite(arr))
        or np.any(arr != np.round(arr))
        or np.any(arr < MIN_NOTE)
        or np.any(arr > MAX_NOTE)
    ):
        raise ValueError("Noten müssen ganze Zahlen von 0 bis 10 sein")
    return OFFSET + FACTOR * arr


def from_ml_array(ml: ArrayLike) -> NDArray[np.float64]:
    """Vectorised `from_ml`."""
    arr = np.asarray(ml, dtype=np.float64)
    return np.clip((arr - OFFSET) / FACTOR, MIN_NOTE, MAX_NOTE)
