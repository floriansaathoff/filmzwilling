from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from filmzwilling.importers.netflix import (
    detect_kind,
    find_export_files,
    parse_netflix,
    parse_ratings,
    parse_simple_history,
    parse_viewing_activity,
)


@pytest.fixture
def netflix_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "netflix"


@pytest.fixture
def activity(netflix_dir: Path) -> Path:
    return netflix_dir / "CONTENT_INTERACTION" / "ViewingActivity.csv"


def by_key(result) -> dict[tuple[str, str], object]:
    return {(e.profile, e.raw_title): e for e in result.events}


def test_viewing_activity_events(activity: Path) -> None:
    res = parse_viewing_activity(activity)
    events = by_key(res)
    assert set(events) == {
        ("Florian", "Inception"),
        ("Florian", "Toni Erdmann"),
        ("Florian", "Lola rennt"),
        ("Florian", "Star Wars: Episode IV – Eine neue Hoffnung"),
        ("Florian", "Mission: Impossible – Fallout"),
        ("Florian", "Mission: Impossible"),
        ("Florian", "Der Pate"),
        ("Kinder", "Die Eiskönigin – Völlig unverfroren"),
        ("Kinder", "Inception"),
    }
    assert res.rows == 26
    assert res.skipped_supplemental == 3
    assert res.skipped_series == 9
    assert res.skipped_short == 1  # Der Schuh des Manitu (autoplay)
    assert all(e.source == "netflix" for e in res.events)


def test_sessions_are_merged(activity: Path) -> None:
    events = by_key(parse_viewing_activity(activity))
    inc = events[("Florian", "Inception")]
    assert inc.sessions == 2  # type: ignore[attr-defined]
    assert inc.total_watch_seconds == 7500  # type: ignore[attr-defined]
    assert inc.max_position_seconds == 7500  # type: ignore[attr-defined]
    assert inc.first_seen == datetime(2024, 3, 10, 20, 5, 11)  # type: ignore[attr-defined]
    assert inc.last_seen == datetime(2024, 3, 11, 19, 0, 0)  # type: ignore[attr-defined]
    pate = events[("Florian", "Der Pate")]
    assert pate.sessions == 3  # type: ignore[attr-defined]
    assert pate.max_position_seconds == 2 * 3600 + 55 * 60  # type: ignore[attr-defined]
    lola = events[("Florian", "Lola rennt")]
    assert lola.total_watch_seconds == 130  # type: ignore[attr-defined]
    kinder = events[("Kinder", "Inception")]
    assert kinder.sessions == 1  # type: ignore[attr-defined]


def test_movies_with_colons_are_movies(activity: Path) -> None:
    titles = {e.raw_title for e in parse_viewing_activity(activity).events}
    assert "Star Wars: Episode IV – Eine neue Hoffnung" in titles
    assert "Mission: Impossible" in titles
    assert not any("Staffel" in t or "Season" in t or "Folge" in t for t in titles)


def test_bom_is_handled(activity: Path) -> None:
    assert activity.read_bytes().startswith(b"\xef\xbb\xbf")
    assert detect_kind(activity) == "viewing_activity"


def test_simple_history(netflix_dir: Path) -> None:
    path = netflix_dir / "NetflixViewingHistory.csv"
    assert detect_kind(path) == "simple"
    res = parse_simple_history(path, profile="Florian")
    events = by_key(res)
    assert set(events) == {
        ("Florian", "Inception"),
        ("Florian", "Das Leben der Anderen"),
        ("Florian", "Mission: Impossible – Fallout"),
    }
    lda = events[("Florian", "Das Leben der Anderen")]
    assert lda.sessions == 2  # type: ignore[attr-defined]
    assert lda.first_seen == datetime(2024, 2, 20)  # type: ignore[attr-defined]
    assert lda.last_seen == datetime(2024, 2, 21)  # type: ignore[attr-defined]
    assert lda.total_watch_seconds is None  # type: ignore[attr-defined]
    assert res.skipped_series == 1


def test_ratings(netflix_dir: Path) -> None:
    path = netflix_dir / "CONTENT_INTERACTION" / "Ratings.csv"
    assert detect_kind(path) == "ratings"
    thumbs = parse_ratings(path)
    assert {(t["profile"], t["title"], t["thumbs"]) for t in thumbs} == {
        ("Florian", "Inception", "up"),
        ("Florian", "Toni Erdmann", "down"),
        ("Florian", "Interstellar", "love"),
        ("Kinder", "Die Eiskönigin – Völlig unverfroren", "love"),
    }


def test_ratings_with_alternative_headers(tmp_path: Path) -> None:
    p = tmp_path / "Ratings.csv"
    p.write_text("Profile,Title,Thumbs Value\nLena,Soul,2\nLena,Cars,0\n", encoding="utf-8")
    assert detect_kind(p) == "ratings"
    assert parse_ratings(p) == [{"profile": "Lena", "title": "Soul", "thumbs": "up"}]


def test_find_export_files_and_parse_dir(netflix_dir: Path) -> None:
    files = find_export_files(netflix_dir)
    assert files["viewing_activity"].name == "ViewingActivity.csv"
    assert files["ratings"].name == "Ratings.csv"
    assert files["simple"].name == "NetflixViewingHistory.csv"
    result, thumbs = parse_netflix(netflix_dir / "CONTENT_INTERACTION")
    assert len(result.events) == 9
    assert len(thumbs) == 4


def test_parse_netflix_simple_needs_profile(netflix_dir: Path) -> None:
    result, thumbs = parse_netflix(netflix_dir / "NetflixViewingHistory.csv", profile="Lena")
    assert {e.profile for e in result.events} == {"Lena"}
    assert thumbs == []
    result, _ = parse_netflix(netflix_dir / "NetflixViewingHistory.csv")
    assert {e.profile for e in result.events} == {"Netflix"}


def test_unknown_file(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    p.write_text("foo,bar\n1,2\n", encoding="utf-8")
    assert detect_kind(p) is None
    with pytest.raises(ValueError):
        parse_netflix(p)


def test_import_is_idempotent(service, activity: Path, netflix_dir: Path) -> None:
    result, thumbs = parse_netflix(netflix_dir / "CONTENT_INTERACTION")
    first = service.store_import(result, thumbs)
    assert first.inserted == 9 + 1  # + Interstellar (thumb only)
    assert service.repo.count_watch_events() == 10
    result2, thumbs2 = parse_netflix(netflix_dir / "CONTENT_INTERACTION")
    second = service.store_import(result2, thumbs2)
    assert second.inserted == 0
    assert service.repo.count_watch_events() == 10
    hints = {(e.profile, e.raw_title): e.hints for e in service.repo.list_watch_events()}
    assert hints[("Florian", "Inception")]["netflix_thumbs"] == "up"
    assert hints[("Florian", "Interstellar")]["netflix_thumbs"] == "love"
