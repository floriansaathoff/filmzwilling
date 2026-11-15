"""Generic CSV import (Disney+ and everything else): title, year, profile, watched_fraction."""

from __future__ import annotations

from pathlib import Path

from filmzwilling.importers.common import ParseResult

SOURCE = "csv"
DEFAULT_PROFILE = "Manuell"


def parse_fraction(value: str | None) -> float | None:
    """Parse 0.85, "0,85", "85 %" or 85 into a fraction between 0 and 1."""
    raise NotImplementedError


def parse_generic_csv(path: Path, source: str = SOURCE) -> ParseResult:
    raise NotImplementedError
