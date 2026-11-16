"""Ratings CSV export and rotating backups."""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path
from typing import Any, TextIO

EXPORT_COLUMNS = ("tmdb_id", "movielens_id", "title", "year", "score", "rated_at")
_BACKUP_RE = re.compile(r"^ratings-\d{4}-\d{2}-\d{2}\.csv$")


def write_ratings_csv(repo: Any, out: TextIO) -> int:
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(EXPORT_COLUMNS)
    rows = sorted(repo.list_ratings(), key=lambda r: (r["rated_at"] or "", r["film_id"]))
    for row in rows:
        writer.writerow(["" if row[c] is None else row[c] for c in EXPORT_COLUMNS])
    return len(rows)


def export_ratings(repo: Any, path: Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        return write_ratings_csv(repo, fh)


def backup_ratings(
    repo: Any, backups_dir: Path, *, today: date | None = None, keep: int = 14
) -> Path:
    """Write data/backups/ratings-YYYY-MM-DD.csv and keep only the newest `keep` files."""
    backups_dir = Path(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)
    day = today or date.today()
    target = backups_dir / f"ratings-{day.isoformat()}.csv"
    export_ratings(repo, target)
    backups = sorted(p for p in backups_dir.iterdir() if _BACKUP_RE.match(p.name))
    for old in backups[: max(0, len(backups) - keep)]:
        old.unlink()
    return target
