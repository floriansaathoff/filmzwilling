"""Ratings CSV export and rotating backups."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, TextIO

EXPORT_COLUMNS = ("tmdb_id", "movielens_id", "title", "year", "score", "rated_at")


def write_ratings_csv(repo: Any, out: TextIO) -> int:
    raise NotImplementedError


def export_ratings(repo: Any, path: Path) -> int:
    raise NotImplementedError


def backup_ratings(
    repo: Any, backups_dir: Path, *, today: date | None = None, keep: int = 14
) -> Path:
    """Write data/backups/ratings-YYYY-MM-DD.csv and keep only the newest `keep` files."""
    raise NotImplementedError
