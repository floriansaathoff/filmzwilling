"""Netflix: full data export (ViewingActivity.csv, Ratings.csv) and simple viewing history.

Ratings.csv assumptions (documented in docs/ENTSCHEIDUNGEN.md): columns are detected by name
(profile: "Profile Name"/"Profile", title: "Title Name"/"Title", thumbs: "Thumbs Value");
Thumbs Value 1 = thumbs down, 2 = thumbs up, 3 = two thumbs up ("love"), 0/empty = no thumb.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from filmzwilling.importers.common import (
    ParseResult,
    Session,
    aggregate_sessions,
    parse_datetime,
    parse_duration,
    read_csv_rows,
)
from filmzwilling.importers.header_aliases import normalize_header

SOURCE = "netflix"
DEFAULT_PROFILE = "Netflix"
VIEWING_ACTIVITY_COLUMNS = (
    "Profile Name",
    "Start Time",
    "Duration",
    "Attributes",
    "Title",
    "Supplemental Video Type",
    "Device Type",
    "Bookmark",
    "Latest Bookmark",
    "Country",
)
THUMBS = {"1": "down", "2": "up", "3": "love"}


def _header_map(headers: list[str]) -> dict[str, str]:
    return {normalize_header(h): h for h in headers}


def _kind_from_headers(headers: list[str]) -> str | None:
    norm = set(_header_map(headers))
    if {"profilename", "starttime", "duration", "title"} <= norm:
        return "viewing_activity"
    if "thumbsvalue" in norm and ({"titlename", "title"} & norm):
        return "ratings"
    if {"title", "date"} <= norm and not ({"profilename", "duration"} & norm):
        return "simple"
    return None


def detect_kind(path: Path) -> str | None:
    """'viewing_activity', 'simple', 'ratings' or None based on the headers."""
    headers, _ = read_csv_rows(path)
    return _kind_from_headers(headers)


def _get(row: dict[str, str], hmap: dict[str, str], *names: str) -> str:
    for name in names:
        header = hmap.get(name)
        if header is not None and row.get(header):
            return row[header].strip()
    return ""


def parse_viewing_activity(path: Path) -> ParseResult:
    headers, rows = read_csv_rows(path)
    hmap = _header_map(headers)
    result = ParseResult()
    sessions: list[Session] = []
    for row in rows:
        result.rows += 1
        if _get(row, hmap, "supplementalvideotype"):
            result.skipped_supplemental += 1
            continue
        sessions.append(
            Session(
                profile=_get(row, hmap, "profilename") or DEFAULT_PROFILE,
                title=_get(row, hmap, "title"),
                start=parse_datetime(_get(row, hmap, "starttime")),
                duration_seconds=parse_duration(_get(row, hmap, "duration")),
                position_seconds=parse_duration(_get(row, hmap, "bookmark")),
            )
        )
    return aggregate_sessions(sessions, source=SOURCE, result=result)


def parse_simple_history(path: Path, profile: str) -> ParseResult:
    headers, rows = read_csv_rows(path)
    hmap = _header_map(headers)
    result = ParseResult()
    sessions = []
    for row in rows:
        result.rows += 1
        sessions.append(
            Session(
                profile=profile,
                title=_get(row, hmap, "title"),
                start=parse_datetime(_get(row, hmap, "date")),
                duration_seconds=None,
                position_seconds=None,
            )
        )
    return aggregate_sessions(sessions, source=SOURCE, min_watch_seconds=None, result=result)


def parse_ratings(path: Path) -> list[dict[str, Any]]:
    """Thumb ratings: [{"profile", "title", "thumbs"}] with thumbs in down/up/love."""
    headers, rows = read_csv_rows(path)
    hmap = _header_map(headers)
    thumbs: list[dict[str, Any]] = []
    for row in rows:
        value = _get(row, hmap, "thumbsvalue")
        kind = THUMBS.get(value.split(".")[0] if value else "")
        title = _get(row, hmap, "titlename", "title")
        if not kind or not title:
            continue
        profile = _get(row, hmap, "profilename", "profile") or DEFAULT_PROFILE
        thumbs.append({"profile": profile, "title": title, "thumbs": kind})
    return thumbs


def find_export_files(path: Path) -> dict[str, Path]:
    """Locate ViewingActivity/simple history/Ratings files in a file or export directory."""
    path = Path(path)
    candidates = [path] if path.is_file() else sorted(path.rglob("*.csv"))
    found: dict[str, Path] = {}
    for file in candidates:
        kind = detect_kind(file)
        if kind and kind not in found:
            found[kind] = file
    return found


def parse_netflix(
    path: Path, profile: str | None = None
) -> tuple[ParseResult, list[dict[str, Any]]]:
    """Parse whatever Netflix files `path` contains. Returns (viewing result, thumb ratings)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Datei oder Ordner nicht gefunden: {path}")
    files = find_export_files(path)
    if not files:
        raise ValueError(
            f"In {path} wurde keine Netflix-Datei erkannt (ViewingActivity.csv, "
            "NetflixViewingHistory.csv oder Ratings.csv)."
        )
    if "viewing_activity" in files:
        result = parse_viewing_activity(files["viewing_activity"])
    elif "simple" in files:
        result = parse_simple_history(files["simple"], profile or DEFAULT_PROFILE)
    else:
        result = ParseResult()
    thumbs = parse_ratings(files["ratings"]) if "ratings" in files else []
    return result, thumbs
