from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from pathlib import Path

from filmzwilling.backup import EXPORT_COLUMNS, backup_ratings, export_ratings, write_ratings_csv
from filmzwilling.repository import MovieLensFilm, Repository


def seed(repo: Repository) -> None:
    repo.upsert_movielens_films(
        [
            MovieLensFilm(1, 238, "Godfather, The", 1972, ["Crime", "Drama"], 100, 4.3, 1),
            MovieLensFilm(2, 582, "Lives of Others, The", 2006, ["Drama"], 50, 4.1, 2),
        ]
    )
    repo.set_rating(repo.film_id_for_movielens(1), 10)
    repo.set_rating(repo.film_id_for_movielens(2), 8)


def test_write_ratings_csv(repo: Repository) -> None:
    seed(repo)
    buf = io.StringIO()
    assert write_ratings_csv(repo, buf) == 2
    rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
    assert tuple(rows[0].keys()) == EXPORT_COLUMNS
    by_tmdb = {r["tmdb_id"]: r for r in rows}
    assert by_tmdb["238"]["score"] == "10"
    assert by_tmdb["238"]["title"] == "The Godfather"
    assert by_tmdb["582"]["movielens_id"] == "2"


def test_export_ratings(repo: Repository, tmp_path: Path) -> None:
    seed(repo)
    out = tmp_path / "sub" / "ratings.csv"
    assert export_ratings(repo, out) == 2
    assert out.read_text(encoding="utf-8").splitlines()[0] == ",".join(EXPORT_COLUMNS)


def test_backup_rotation(repo: Repository, tmp_path: Path) -> None:
    seed(repo)
    backups = tmp_path / "backups"
    backups.mkdir()
    start = date(2026, 1, 1)
    for i in range(16):
        (backups / f"ratings-{(start + timedelta(days=i)).isoformat()}.csv").write_text("old")
    (backups / "notes.txt").write_text("keep me")
    today = start + timedelta(days=20)
    path = backup_ratings(repo, backups, today=today, keep=14)
    assert path == backups / f"ratings-{today.isoformat()}.csv"
    files = sorted(p.name for p in backups.glob("ratings-*.csv"))
    assert len(files) == 14
    assert files[-1] == path.name
    assert f"ratings-{start.isoformat()}.csv" not in files
    assert (backups / "notes.txt").exists()
    # Same day again: overwritten, still 14 files
    backup_ratings(repo, backups, today=today, keep=14)
    assert len(list(backups.glob("ratings-*.csv"))) == 14
    assert "The Godfather" in path.read_text(encoding="utf-8")


def test_backup_creates_directory(repo: Repository, tmp_path: Path) -> None:
    path = backup_ratings(repo, tmp_path / "new" / "backups", today=date(2026, 5, 4))
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("tmdb_id,")
