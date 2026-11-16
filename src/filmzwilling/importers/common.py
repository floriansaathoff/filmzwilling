"""Shared importer helpers: episode detection, time parsing, session aggregation, storage."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
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


# --- episode detection ----------------------------------------------------------------------

_NUMBER_WORDS = (
    "eins|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn|elf|zwölf|zwoelf|"
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    "erster|zweiter|dritter|first|second|third"
)
_SEGMENT_SPLIT = re.compile(r":\s+")
# Season words are unambiguous: "Staffel 2" never names a movie part.
_STRONG_SEASON = re.compile(
    rf"^(staffel|season|saison|temporada|stagione|series|serie)\s+(\d+|[ivx]+|{_NUMBER_WORDS})$",
    re.IGNORECASE,
)
# Part words are also used by movies ("Kill Bill: Volume 1", "Dune: Part Two"). They only mark a
# series when another segment (the episode title) follows.
_WEAK_SEASON = re.compile(
    rf"^(teil|part|volume|vol\.?|buch|book|collection|kollektion)\s+(\d+|[ivx]+|{_NUMBER_WORDS})$",
    re.IGNORECASE,
)
_SERIES_MARKER = re.compile(
    r"^(limitierte serie|limited series|miniserie|mini-serie|miniseries|mini-series|"
    r"mini series|dokuserie|docuseries|die serie|the series)$",
    re.IGNORECASE,
)
# "Folge 3", "Episode 4", "Kapitel eins" – but not "Episode IV" (Star Wars uses roman numerals).
_EPISODE_SEGMENT = re.compile(
    rf"^(folge|episode|ep\.?|kapitel|chapter)\s+(\d+|{_NUMBER_WORDS})\b", re.IGNORECASE
)
_ANYWHERE_EPISODE = re.compile(
    r"(\b(staffel|season|saison)\s+\d+\b)|(\bS\d{1,2}\s*E\d{1,3}\b)|"
    r"([-–]\s*(staffel|season)\s+\d+)",
    re.IGNORECASE,
)


def classify_title(title: str) -> str:
    """Return KIND_MOVIE, KIND_EPISODE or KIND_AMBIGUOUS for a streaming title."""
    text = " ".join(title.split())
    if _ANYWHERE_EPISODE.search(text):
        return KIND_EPISODE
    segments = [s.strip() for s in _SEGMENT_SPLIT.split(text) if s.strip()]
    if len(segments) < 2:
        return KIND_MOVIE
    rest = segments[1:]
    for i, seg in enumerate(rest):
        is_last = i == len(rest) - 1
        if _STRONG_SEASON.match(seg) or _SERIES_MARKER.match(seg) or _EPISODE_SEGMENT.match(seg):
            return KIND_EPISODE
        if not is_last and _WEAK_SEASON.match(seg):
            return KIND_EPISODE
    if len(segments) >= 3:
        return KIND_AMBIGUOUS
    return KIND_MOVIE


def is_episode(title: str) -> bool:
    return classify_title(title) == KIND_EPISODE


# --- value parsing --------------------------------------------------------------------------

_CLOCK = re.compile(r"^(\d+):(\d{1,2})(?::(\d{1,2}))?$")
_ISO_DURATION = re.compile(
    r"^P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$", re.IGNORECASE
)
_DATE_FORMATS = (
    "%d.%m.%y",
    "%d.%m.%Y",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%y %H:%M",
    "%d.%m.%y, %H:%M",
    "%d.%m.%Y, %H:%M",
    "%m/%d/%y",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %I:%M %p",
    "%Y/%m/%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S %Z",
    "%d %b %Y",
    "%b %d, %Y",
)


def parse_duration(value: str | None, unit: str = "auto") -> int | None:
    """Parse "HH:MM:SS", "MM:SS" or a number (seconds by default) into seconds."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    clock = _CLOCK.match(text)
    if clock:
        a, b, c = clock.groups()
        if c is None:
            return int(a) * 60 + int(b)
        return int(a) * 3600 + int(b) * 60 + int(c)
    iso = _ISO_DURATION.match(text)
    if iso and any(iso.groups()):
        h, m, s = iso.groups()
        return int(h or 0) * 3600 + int(m or 0) * 60 + round(float(s or 0))
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        return None
    if number < 0 or number != number:
        return None
    unit = unit.lower()
    if unit in ("ms", "milliseconds", "millis"):
        number /= 1000.0
    elif unit in ("minutes", "minuten", "min"):
        number *= 60.0
    elif unit in ("hours", "stunden", "h"):
        number *= 3600.0
    return round(number)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse common ISO, German and US date/time formats."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) in (10, 13):
        seconds = int(text) / (1000 if len(text) == 13 else 1)
        return datetime.fromtimestamp(seconds, tz=UTC).replace(tzinfo=None)
    iso = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


# --- aggregation ----------------------------------------------------------------------------


def aggregate_sessions(
    sessions: Iterable[Session],
    *,
    source: str,
    min_watch_seconds: int | None = MIN_WATCH_SECONDS,
    result: ParseResult | None = None,
) -> ParseResult:
    """Drop episodes, merge sessions per (profile, title), drop autoplay snippets."""
    res = result if result is not None else ParseResult()
    groups: dict[tuple[str, str], list[Session]] = {}
    kinds: dict[tuple[str, str], str] = {}
    for session in sessions:
        title = " ".join(session.title.split())
        if not title:
            res.skipped_invalid += 1
            continue
        kind = classify_title(title)
        if kind == KIND_EPISODE:
            res.skipped_series += 1
            continue
        key = (session.profile.strip() or "Unbekannt", title)
        groups.setdefault(key, []).append(session)
        kinds[key] = kind
    for (profile, title), items in groups.items():
        durations = [s.duration_seconds for s in items if s.duration_seconds is not None]
        total = sum(durations) if durations else None
        if min_watch_seconds is not None and total is not None and total < min_watch_seconds:
            res.skipped_short += 1
            continue
        positions = [s.position_seconds for s in items if s.position_seconds is not None]
        starts = [s.start for s in items if s.start is not None]
        fractions = [s.watched_fraction for s in items if s.watched_fraction is not None]
        year = next((s.year for s in items if s.year is not None), None)
        hints: dict[str, Any] = {}
        if fractions:
            hints["watched_fraction"] = max(fractions)
        res.events.append(
            WatchEvent(
                source=source,
                profile=profile,
                raw_title=title,
                first_seen=min(starts) if starts else None,
                last_seen=max(starts) if starts else None,
                total_watch_seconds=total,
                max_position_seconds=max(positions) if positions else None,
                sessions=len(items),
                hints=hints,
                year=year,
                kind=kinds[(profile, title)],
            )
        )
    return res


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _delimiter(first_line: str) -> str:
    counts = {d: first_line.count(d) for d in (",", ";", "\t", "|")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] > 0 else ","


def read_csv_rows(path: Any) -> tuple[list[str], list[dict[str, str]]]:
    """Read a CSV (UTF-8 with or without BOM, delimiter sniffed). Returns (headers, rows)."""
    text = _decode(Path(path).read_bytes()).lstrip("﻿")
    first_line = text.split("\n", 1)[0]
    reader = csv.reader(io.StringIO(text), delimiter=_delimiter(first_line))
    try:
        headers = [h.replace("﻿", "").strip() for h in next(reader)]
    except StopIteration:
        return [], []
    rows: list[dict[str, str]] = []
    for values in reader:
        if not any(v.strip() for v in values):
            continue
        padded = values + [""] * (len(headers) - len(values))
        rows.append({h: padded[i].strip() for i, h in enumerate(headers)})
    return headers, rows


def store_events(repo: Any, events: Iterable[WatchEvent]) -> ImportReport:
    report = ImportReport(parse=ParseResult())
    for event in events:
        outcome = repo.upsert_watch_event(event)
        if outcome == "inserted":
            report.inserted += 1
        elif outcome == "updated":
            report.updated += 1
        else:
            report.unchanged += 1
    return report
