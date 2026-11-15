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
    if watched_fraction is not None:
        return min(max(float(watched_fraction), 0.0), 1.0)
    if not runtime_minutes or runtime_minutes <= 0:
        return None
    seconds = max_position_seconds or total_watch_seconds
    if not seconds:
        return None
    return min(float(seconds) / (runtime_minutes * 60.0), 1.0)


def classify(fraction: float | None) -> str:
    if fraction is None:
        return UNKNOWN
    if fraction >= FINISHED_THRESHOLD:
        return FINISHED
    if fraction < ABANDONED_THRESHOLD:
        return ABANDONED
    return UNCLEAR


def _percent(fraction: float) -> int:
    return int(fraction * 100 + 0.5)


def describe(
    status: str,
    fraction: float | None,
    runtime_minutes: int | None,
    profile: str,
) -> str:
    """German hint, e.g. "Abgebrochen bei 28 % (34 von 121 Min.), Profil Florian"."""
    suffix = f"Profil {profile}"
    if status == UNKNOWN or fraction is None:
        return f"Gesehen, Laufzeit unbekannt, {suffix}"
    minutes = (
        f" ({int(fraction * runtime_minutes + 0.5)} von {runtime_minutes} Min.)"
        if runtime_minutes
        else ""
    )
    if status == FINISHED:
        detail = minutes or f" ({_percent(fraction)} %)"
        return f"Zu Ende geschaut{detail}, {suffix}"
    if status == ABANDONED:
        return f"Abgebrochen bei {_percent(fraction)} %{minutes}, {suffix}"
    return f"Unklar: {_percent(fraction)} % gesehen{minutes}, {suffix}"
