"""Detect abandoned movies from watch positions and the TMDB runtime."""

from __future__ import annotations

FINISHED = "finished"
ABANDONED = "abandoned"
UNCLEAR = "unclear"
UNKNOWN = "unknown"
FINISHED_THRESHOLD = 0.85
ABANDONED_THRESHOLD = 0.6


def watch_fraction(
    max_position_seconds: int | None,
    total_watch_seconds: int | None,
    runtime_minutes: int | None,
    watched_fraction: float | None = None,
) -> float | None:
    """fraction = max_position / runtime, else total_watch / runtime (capped at 1)."""
    raise NotImplementedError


def classify(fraction: float | None) -> str:
    raise NotImplementedError


def describe(
    status: str,
    fraction: float | None,
    runtime_minutes: int | None,
    profile: str,
) -> str:
    """German hint, e.g. "Abgebrochen bei 28 % (34 von 121 Min.), Profil Florian"."""
    raise NotImplementedError
