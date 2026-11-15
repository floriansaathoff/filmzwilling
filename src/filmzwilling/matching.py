"""Map imported titles to TMDB movies (rapidfuzz scoring) and on to MovieLens."""

from __future__ import annotations

import asyncio
import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from filmzwilling.tmdb import SearchResult, TMDBClient

DEFAULT_THRESHOLD = 85.0
_ARTICLES = {
    "der",
    "die",
    "das",
    "ein",
    "eine",
    "the",
    "a",
    "an",
    "le",
    "la",
    "les",
    "l",
    "el",
    "il",
    "lo",
    "los",
    "las",
    "un",
    "une",
}
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_TAG = re.compile(
    r"^(omu|omdu|ov|om u|omeu|original.*|dt\..*|deutsch.*|german.*|english.*|englisch.*|"
    r"untertitel.*|4k.*|uhd.*|hd|sd|hdr|\d{4}|extended.*|director'?s cut.*|kinofassung|"
    r"ungekürzt.*|uncut)$",
    re.IGNORECASE,
)
_TRAILING_GROUP = re.compile(r"\s*[\(\[]([^\(\)\[\]]*)[\)\]]\s*$")
_YEAR_GROUP = re.compile(r"[\(\[]((?:19|20)\d{2})[\)\]]\s*$")


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
    text = unicodedata.normalize("NFKC", title).lower().translate(_UMLAUTS)
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]|_", " ", text)
    words = text.split()
    if len(words) > 1 and words[0] in _ARTICLES:
        words = words[1:]
    return " ".join(words)


def clean_query(title: str) -> str:
    """Remove streaming decorations like "(OmU)" or "[4K UHD]" before searching."""
    text = " ".join(title.split())
    while True:
        match = _TRAILING_GROUP.search(text)
        if not match or not _TAG.match(match.group(1).strip()):
            return text
        stripped = text[: match.start()].strip()
        if not stripped:
            return text
        text = stripped


def year_from_title(title: str) -> int | None:
    match = _YEAR_GROUP.search(title.strip())
    return int(match.group(1)) if match else None


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return float(max(fuzz.ratio(na, nb), fuzz.token_sort_ratio(na, nb)))


def _raw_score(
    query: str, year: int | None, candidate: SearchResult, max_year: int | None
) -> float:
    similarity = max(
        title_similarity(query, candidate.title), title_similarity(query, candidate.original_title)
    )
    score = similarity
    cand_year = candidate.year
    if year and cand_year:
        diff = abs(year - cand_year)
        score += 5.0 if diff == 0 else 2.0 if diff == 1 else -min(25.0, 8.0 * diff)
    elif max_year and cand_year and cand_year > max_year:
        score -= 30.0
    score += min(3.0, math.log10(1 + max(candidate.vote_count, 0)) / 2.0)
    return score


def score_candidate(
    query: str, year: int | None, candidate: SearchResult, *, max_year: int | None = None
) -> float:
    """Title similarity (0–100) adjusted by year distance and a small popularity bonus."""
    return _raw_score(query, year, candidate, max_year)


def choose_best(
    query: str,
    year: int | None,
    candidates: Sequence[SearchResult],
    *,
    max_year: int | None = None,
) -> tuple[SearchResult, float] | None:
    movies = [c for c in candidates if c.media_type == "movie"]
    if not movies:
        return None
    scored = [(c, _raw_score(query, year, c, max_year)) for c in movies]
    scored.sort(key=lambda cs: (-cs[1], -cs[0].vote_count, cs[0].tmdb_id))
    return scored[0]


async def match_title(
    client: TMDBClient,
    title: str,
    *,
    year: int | None = None,
    kind: str = "movie",
    max_year: int | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> MatchOutcome:
    query = clean_query(title)
    year = year or year_from_title(title)
    results = await client.search_movie(query, year)
    if not results and year:
        results = await client.search_movie(query)
    best = choose_best(query, year, results, max_year=max_year)
    if best is not None and best[1] >= threshold:
        return MatchOutcome(title, "matched", best[0].tmdb_id, min(best[1], 100.0), best[0].title)
    score = None if best is None else round(min(best[1], 100.0), 1)
    best_title = None if best is None else best[0].title
    if kind == "ambiguous":
        return MatchOutcome(title, "series", None, score, best_title)
    return MatchOutcome(title, "unmatched", None, score, best_title)


def _max_year(last_seen: str | None) -> int | None:
    if last_seen and last_seen[:4].isdigit():
        return int(last_seen[:4])
    return None


async def match_pending(
    repo: Any, client: TMDBClient, *, threshold: float = DEFAULT_THRESHOLD
) -> MatchStats:
    """Match every pending raw title in the database; weak matches go to `unmatched`."""
    pending = repo.pending_titles()
    outcomes = await asyncio.gather(
        *(
            match_title(
                client,
                p["raw_title"],
                year=p["year"],
                kind=p["kind"],
                max_year=None if p["year"] else _max_year(p["last_seen"]),
                threshold=threshold,
            )
            for p in pending
        )
    )
    stats = MatchStats()
    for item, outcome in zip(pending, outcomes, strict=True):
        if outcome.status == "matched" and outcome.tmdb_id is not None:
            repo.assign_title(item["raw_title"], outcome.tmdb_id)
            stats.matched += 1
        elif outcome.status == "series":
            repo.mark_title_series(item["raw_title"])
            stats.series += 1
        else:
            repo.add_unmatched(
                item["raw_title"],
                source=item["source"],
                year=item["year"],
                best_score=outcome.score,
                best_title=outcome.best_title,
            )
            stats.unmatched += 1
    return stats
