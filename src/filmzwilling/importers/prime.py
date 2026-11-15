"""Prime Video: heuristic CSV importer, mapping overrides via TOML, exporter-script JSON/CSV."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from filmzwilling.importers.common import ParseResult

SOURCE = "prime"
DEFAULT_PROFILE = "Prime Video"


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
        raise NotImplementedError


@dataclass
class InspectReport:
    path: Path
    format: str
    headers: list[str]
    mapping: ColumnMapping
    sample: list[dict[str, Any]]
    row_count: int


def detect_mapping(headers: list[str]) -> ColumnMapping:
    raise NotImplementedError


def load_mapping(path: Path, base: ColumnMapping | None = None) -> ColumnMapping:
    """Override a detected mapping with a TOML file ([columns] and [units] tables)."""
    raise NotImplementedError


def read_records(path: Path) -> tuple[str, list[str], list[dict[str, Any]]]:
    """Read CSV or JSON records. Returns (format, headers, records)."""
    raise NotImplementedError


def inspect_file(path: Path, mapping_path: Path | None = None) -> InspectReport:
    raise NotImplementedError


def parse_prime(path: Path, mapping: ColumnMapping | None = None) -> ParseResult:
    raise NotImplementedError
