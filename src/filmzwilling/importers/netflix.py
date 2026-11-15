"""Netflix: full data export (ViewingActivity.csv, Ratings.csv) and simple viewing history."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from filmzwilling.importers.common import ParseResult

SOURCE = "netflix"
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


def detect_kind(path: Path) -> str | None:
    """'viewing_activity', 'simple', 'ratings' or None based on the headers."""
    raise NotImplementedError


def parse_viewing_activity(path: Path) -> ParseResult:
    raise NotImplementedError


def parse_simple_history(path: Path, profile: str) -> ParseResult:
    raise NotImplementedError


def parse_ratings(path: Path) -> list[dict[str, Any]]:
    """Thumb ratings: [{"profile", "title", "thumbs"}] with thumbs in down/up/love."""
    raise NotImplementedError


def find_export_files(path: Path) -> dict[str, Path]:
    """Locate ViewingActivity/simple history/Ratings files in a file or export directory."""
    raise NotImplementedError


def parse_netflix(
    path: Path, profile: str | None = None
) -> tuple[ParseResult, list[dict[str, Any]]]:
    """Parse whatever Netflix files `path` contains. Returns (viewing result, thumb ratings)."""
    raise NotImplementedError
