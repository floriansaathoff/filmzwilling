"""Shared importer helpers: episode detection, time parsing, session aggregation, storage."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

KIND_MOVIE = "movie"
KIND_EPISODE = "episode"
KIND_AMBIGUOUS = "ambiguous"
MIN_WATCH_SECONDS = 120


@dataclass
class WatchEvent:
    source: str
    profile: str
    raw_title: str
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    total_watch_seconds: int | None = None
    max_position_seconds: int | None = None
    sessions: int = 1
    hints: dict[str, Any] = field(default_factory=dict)
    year: int | None = None
    kind: str = KIND_MOVIE
    tmdb_id: int | None = None
    movielens_id: int | None = None


@dataclass(frozen=True)
class Session:
    """One raw viewing row."""

    profile: str
    title: str
    start: datetime | None
    duration_seconds: int | None
    position_seconds: int | None
    year: int | None = None
    watched_fraction: float | None = None


@dataclass
class ParseResult:
    events: list[WatchEvent] = field(default_factory=list)
    rows: int = 0
    skipped_supplemental: int = 0
    skipped_series: int = 0
    skipped_short: int = 0
    skipped_invalid: int = 0


@dataclass
class ImportReport:
    parse: ParseResult
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    matched: int = 0
    unmatched: int = 0
    series: int = 0
    notes: list[str] = field(default_factory=list)


def classify_title(title: str) -> str:
    """Return KIND_MOVIE, KIND_EPISODE or KIND_AMBIGUOUS for a streaming title."""
    raise NotImplementedError


def is_episode(title: str) -> bool:
    raise NotImplementedError


def parse_duration(value: str | None, unit: str = "auto") -> int | None:
    """Parse "HH:MM:SS", "MM:SS" or a number (seconds by default) into seconds."""
    raise NotImplementedError


def parse_datetime(value: str | None) -> datetime | None:
    """Parse common ISO, German and US date/time formats."""
    raise NotImplementedError


def aggregate_sessions(
    sessions: Iterable[Session],
    *,
    source: str,
    min_watch_seconds: int | None = MIN_WATCH_SECONDS,
    result: ParseResult | None = None,
) -> ParseResult:
    """Drop episodes, merge sessions per (profile, title), drop autoplay snippets."""
    raise NotImplementedError


def read_csv_rows(path: Any) -> tuple[list[str], list[dict[str, str]]]:
    """Read a CSV (UTF-8 with or without BOM, delimiter sniffed). Returns (headers, rows)."""
    raise NotImplementedError


def store_events(repo: Any, events: Iterable[WatchEvent]) -> ImportReport:
    raise NotImplementedError
