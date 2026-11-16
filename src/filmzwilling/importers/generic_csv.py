"""Generic CSV import (Disney+ and everything else): title, year, profile, watched_fraction."""

from __future__ import annotations

from pathlib import Path

from filmzwilling.importers.common import ParseResult, Session, aggregate_sessions, read_csv_rows
from filmzwilling.importers.header_aliases import normalize_header

SOURCE = "csv"
DEFAULT_PROFILE = "Manuell"
_COLUMNS = {
    "title": ("title", "titel"),
    "year": ("year", "jahr"),
    "profile": ("profile", "profil", "profilname", "profilename"),
    "watched_fraction": ("watchedfraction", "fraction", "anteil", "gesehen", "watched"),
}


def parse_fraction(value: str | None) -> float | None:
    """Parse 0.85, "0,85", "85 %" or 85 into a fraction between 0 and 1."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    percent = "%" in text
    text = text.replace("%", "").replace(" ", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    if number != number or number < 0:
        return None
    if percent or number > 1:
        number /= 100.0
    return min(number, 1.0)


def parse_generic_csv(path: Path, source: str = SOURCE) -> ParseResult:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Datei nicht gefunden: {path}")
    headers, rows = read_csv_rows(path)
    normalized = {normalize_header(h): h for h in headers}
    columns: dict[str, str] = {}
    for name, aliases in _COLUMNS.items():
        for alias in aliases:
            if alias in normalized:
                columns[name] = normalized[alias]
                break
    if "title" not in columns:
        raise ValueError(f"Spalte 'title' fehlt in {path.name} (gefunden: {', '.join(headers)})")
    result = ParseResult()
    sessions: list[Session] = []
    for row in rows:
        result.rows += 1
        title = row.get(columns["title"], "").strip()
        if not title:
            result.skipped_invalid += 1
            continue
        year_text = row.get(columns.get("year", ""), "").strip()
        sessions.append(
            Session(
                profile=row.get(columns.get("profile", ""), "").strip() or DEFAULT_PROFILE,
                title=title,
                start=None,
                duration_seconds=None,
                position_seconds=None,
                year=int(year_text[:4]) if year_text[:4].isdigit() else None,
                watched_fraction=parse_fraction(row.get(columns.get("watched_fraction", ""))),
            )
        )
    return aggregate_sessions(sessions, source=source, min_watch_seconds=None, result=result)
