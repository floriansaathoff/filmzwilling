"""Prime Video: heuristic CSV importer, mapping overrides via TOML, exporter-script JSON/CSV.

The exact format of Amazon's data export is unknown, so columns are detected by header name
(see `header_aliases.py`). `filmzwilling import inspect` shows the guess; a TOML file overrides it:

    [columns]
    title = "Sendung"
    date = "Wann"
    [units]
    duration = "minutes"   # seconds | ms | minutes | auto
    [defaults]
    profile = "Prime Video"
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field, replace
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
from filmzwilling.importers.header_aliases import (
    EPISODE_KIND_VALUES,
    HEADER_ALIASES,
    normalize_header,
)

SOURCE = "prime"
DEFAULT_PROFILE = "Prime Video"
FIELDS = ("title", "date", "profile", "duration", "position", "episode", "kind", "year")
EPISODE_LIST_KEYS = ("episode", "series", "show", "tv", "serie", "folge")


@dataclass
class ColumnMapping:
    title: str | None = None
    date: str | None = None
    profile: str | None = None
    duration: str | None = None
    position: str | None = None
    kind: str | None = None
    episode: str | None = None
    year: str | None = None
    units: dict[str, str] = field(default_factory=dict)
    default_profile: str = DEFAULT_PROFILE

    def as_dict(self) -> dict[str, Any]:
        return {
            **{name: getattr(self, name) for name in FIELDS},
            "units": dict(self.units),
            "default_profile": self.default_profile,
        }


@dataclass
class InspectReport:
    path: Path
    format: str
    headers: list[str]
    mapping: ColumnMapping
    sample: list[dict[str, Any]]
    row_count: int


def _unit(header: str) -> str:
    norm = normalize_header(header)
    if "millis" in norm or "millisekunden" in norm or norm.endswith("ms"):
        return "ms"
    if "minute" in norm or "minuten" in norm or norm.endswith(("min", "mins")):
        return "minutes"
    return "seconds"


def _matches(rule: str, norm: str, alias: str) -> bool:
    if rule == "exact":
        return norm == alias
    if rule == "prefix":
        return len(alias) >= 4 and norm.startswith(alias)
    return len(alias) >= 5 and alias in norm


def detect_mapping(headers: list[str]) -> ColumnMapping:
    """Guess the column mapping. Exact alias matches win over prefix and substring matches."""
    normalized = [(normalize_header(h), h) for h in headers]
    used: set[str] = set()
    found: dict[str, str] = {}
    for rule in ("exact", "prefix", "contains"):
        for name in FIELDS:
            if name in found:
                continue
            match = next(
                (
                    original
                    for alias in HEADER_ALIASES[name]
                    for norm, original in normalized
                    if original not in used and norm and _matches(rule, norm, alias)
                ),
                None,
            )
            if match:
                found[name] = match
                used.add(match)
    mapping = ColumnMapping(**found)
    for name in ("duration", "position"):
        header = found.get(name)
        if header:
            mapping.units[name] = _unit(header)
    return mapping


def load_mapping(path: Path, base: ColumnMapping | None = None) -> ColumnMapping:
    """Override a detected mapping with a TOML file ([columns] and [units] tables)."""
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    mapping = replace(base) if base is not None else ColumnMapping()
    mapping.units = dict(mapping.units)
    for name, value in (data.get("columns") or {}).items():
        if name not in FIELDS:
            raise ValueError(f"Unbekanntes Feld '{name}' in {path} (erlaubt: {', '.join(FIELDS)})")
        setattr(mapping, name, str(value) if value else None)
    for name, value in (data.get("units") or {}).items():
        mapping.units[str(name)] = str(value)
    defaults = data.get("defaults") or {}
    if defaults.get("profile"):
        mapping.default_profile = str(defaults["profile"])
    return mapping


def _records_from_json(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        records: list[dict[str, Any]] = []
        for key, value in data.items():
            if not isinstance(value, list):
                continue
            is_episode_list = any(k in key.lower() for k in EPISODE_LIST_KEYS)
            for item in value:
                if isinstance(item, dict):
                    records.append({**item, "__kind__": "episode"} if is_episode_list else item)
        return records
    return []


def read_records(path: Path) -> tuple[str, list[str], list[dict[str, Any]]]:
    """Read CSV or JSON records. Returns (format, headers, records)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Datei nicht gefunden: {path}")
    raw = path.read_bytes().decode("utf-8-sig", errors="replace")
    if path.suffix.lower() == ".json" or raw.lstrip().startswith(("[", "{")):
        records = _records_from_json(json.loads(raw))
        headers: list[str] = []
        for record in records:
            for key in record:
                if key != "__kind__" and key not in headers:
                    headers.append(key)
        return "json", headers, records
    csv_headers, rows = read_csv_rows(path)
    return "csv", csv_headers, list(rows)


def inspect_file(path: Path, mapping_path: Path | None = None) -> InspectReport:
    fmt, headers, records = read_records(path)
    mapping = detect_mapping(headers)
    if mapping_path is not None:
        mapping = load_mapping(mapping_path, mapping)
    return InspectReport(
        path=Path(path),
        format=fmt,
        headers=headers,
        mapping=mapping,
        sample=records[:5],
        row_count=len(records),
    )


def _text(record: dict[str, Any], column: str | None) -> str:
    if not column:
        return ""
    value = record.get(column)
    return "" if value is None else str(value).strip()


def parse_prime(path: Path, mapping: ColumnMapping | None = None) -> ParseResult:
    fmt, headers, records = read_records(path)
    mapping = mapping or detect_mapping(headers)
    if not mapping.title:
        raise ValueError(
            "Keine Titel-Spalte erkannt. Prüfe die Datei mit 'filmzwilling import inspect' und "
            "gib die Zuordnung mit '--mapping datei.toml' an."
        )
    for name in FIELDS:
        column = getattr(mapping, name)
        if column and column not in headers:
            raise ValueError(
                f"Spalte '{column}' aus der Zuordnung fehlt in der Datei {Path(path).name}"
            )
    result = ParseResult()
    sessions: list[Session] = []
    for record in records:
        result.rows += 1
        title = _text(record, mapping.title)
        if not title:
            result.skipped_invalid += 1
            continue
        kind_value = normalize_header(_text(record, mapping.kind))
        if (
            record.get("__kind__") == "episode"
            or kind_value in EPISODE_KIND_VALUES
            or _text(record, mapping.episode)
        ):
            result.skipped_series += 1
            continue
        year_text = _text(record, mapping.year)
        sessions.append(
            Session(
                profile=_text(record, mapping.profile) or mapping.default_profile,
                title=title,
                start=parse_datetime(_text(record, mapping.date)),
                duration_seconds=parse_duration(
                    _text(record, mapping.duration), mapping.units.get("duration", "seconds")
                ),
                position_seconds=parse_duration(
                    _text(record, mapping.position), mapping.units.get("position", "seconds")
                ),
                year=int(year_text[:4]) if year_text[:4].isdigit() else None,
            )
        )
    return aggregate_sessions(sessions, source=SOURCE, result=result)
