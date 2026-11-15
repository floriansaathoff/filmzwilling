"""Map imported titles to TMDB movies (rapidfuzz scoring) and on to MovieLens."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from filmzwilling.tmdb import SearchResult, TMDBClient

DEFAULT_THRESHOLD = 85.0


@dataclass(frozen=True)
class MatchOutcome:
    raw_title: str
    status: str  # "matched" | "unmatched" | "series"
    tmdb_id: int | None
    score: float | None
    best_title: str | None = None


@dataclass
class MatchStats:
    matched: int = 0
    unmatched: int = 0
    series: int = 0


def normalize_title(title: str) -> str:
    """Lowercase, transliterate umlauts, drop accents, leading articles and punctuation."""
    raise NotImplementedError


def clean_query(title: str) -> str:
    """Remove streaming decorations like "(OmU)" or "[4K UHD]" before searching."""
    raise NotImplementedError


def title_similarity(a: str, b: str) -> float:
    raise NotImplementedError


def score_candidate(
    query: str, year: int | None, candidate: SearchResult, *, max_year: int | None = None
) -> float:
    raise NotImplementedError


def choose_best(
    query: str,
    year: int | None,
    candidates: Sequence[SearchResult],
    *,
    max_year: int | None = None,
) -> tuple[SearchResult, float] | None:
    raise NotImplementedError


async def match_title(
    client: TMDBClient,
    title: str,
    *,
    year: int | None = None,
    kind: str = "movie",
    max_year: int | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> MatchOutcome:
    raise NotImplementedError


async def match_pending(
    repo: Any, client: TMDBClient, *, threshold: float = DEFAULT_THRESHOLD
) -> MatchStats:
    """Match every pending raw title in the database; weak matches go to `unmatched`."""
    raise NotImplementedError
