from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from filmzwilling.importers.common import (
    KIND_AMBIGUOUS,
    KIND_EPISODE,
    KIND_MOVIE,
    Session,
    aggregate_sessions,
    classify_title,
    is_episode,
    parse_datetime,
    parse_duration,
    read_csv_rows,
)
from filmzwilling.importers.header_aliases import normalize_header


@pytest.mark.parametrize(
    "title",
    [
        "Dark: Staffel 1: Geheimnisse",
        "Breaking Bad: Season 1: Pilot",
        "The Crown: Season 2: Misadventure",
        "Das Damengambit: Limitierte Serie: Eröffnungen",
        "Unorthodox: Miniserie: Folge 1",
        "Chernobyl: Limited Series: 1:23:45",
        "Haus des Geldes: Teil 1: Folge 1",
        "Stranger Things: Stranger Things 2: Kapitel eins: MADMAX",
        "Babylon Berlin: Folge 3",
        "Lupin: Teil 2: Kapitel 6",
        "How I Met Your Mother: Staffel 9: Die Hochzeit",
        "Tiger King: Limitierte Serie: Nicht euer Durchschnitts-Joe",
        "Bridgerton: Season 3: Episode 4",
        "Kleo: Staffel 1: Episode 1",
        "The Office (U.S.): Season 5: Stress Relief: Part 1",
        "Squid Game: Staffel 1: Rotes Licht, grünes Licht",
    ],
)
def test_episodes(title: str) -> None:
    assert classify_title(title) == KIND_EPISODE
    assert is_episode(title)


@pytest.mark.parametrize(
    "title",
    [
        "Inception",
        "Star Wars: Episode IV – Eine neue Hoffnung",
        "Star Wars: Episode V - Das Imperium schlägt zurück",
        "Mission: Impossible",
        "Mission: Impossible – Fallout",
        "Mission: Impossible – Dead Reckoning Teil eins",
        "Harry Potter und die Heiligtümer des Todes – Teil 2",
        "Dune: Part Two",
        "Spider-Man: No Way Home",
        "Der Pate",
        "Kill Bill: Volume 1",
        "Fast & Furious 7",
        "Zurück in die Zukunft",
        "Rogue One: A Star Wars Story",
        "Glass Onion: A Knives Out Mystery",
        "Bruce Springsteen: Letter to You",
    ],
)
def test_movies(title: str) -> None:
    assert classify_title(title) == KIND_MOVIE
    assert not is_episode(title)


@pytest.mark.parametrize(
    "title",
    [
        "Star Wars: Episode IV: Eine neue Hoffnung",
        "Tiger King: Großkatzen und Verrückte: Nicht euer Durchschnitts-Joe",
        "Our Planet: Unser Planet: Eiswelten",
    ],
)
def test_ambiguous(title: str) -> None:
    assert classify_title(title) == KIND_AMBIGUOUS
    assert not is_episode(title)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("01:10:00", "auto", 4200),
        ("00:00:45", "auto", 45),
        ("1:02", "auto", 62),
        ("4400", "auto", 4400),
        ("4400", "seconds", 4400),
        ("4400000", "ms", 4400),
        ("150", "minutes", 9000),
        ("2,5", "minutes", 150),
        ("", "auto", None),
        (None, "auto", None),
        ("Not latest view", "auto", None),
        ("-5", "auto", None),
    ],
)
def test_parse_duration(value: str | None, unit: str, expected: int | None) -> None:
    assert parse_duration(value, unit) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2024-03-10 20:05:11", datetime(2024, 3, 10, 20, 5, 11)),
        ("2024-05-01T20:00:00.000Z", datetime(2024, 5, 1, 20, 0, 0)),
        ("2024-05-01", datetime(2024, 5, 1)),
        ("10.03.24", datetime(2024, 3, 10)),
        ("01.04.2024 20:00", datetime(2024, 4, 1, 20, 0)),
        ("3/15/24", datetime(2024, 3, 15)),
        ("15/03/2024", datetime(2024, 3, 15)),
        ("", None),
        ("gestern", None),
    ],
)
def test_parse_datetime(value: str, expected: datetime | None) -> None:
    assert parse_datetime(value) == expected


def test_aggregate_sessions() -> None:
    sessions = [
        Session("Florian", "Inception", datetime(2024, 3, 11, 19), 3300, 7500),
        Session("Florian", "Inception", datetime(2024, 3, 10, 20), 4200, 4200),
        Session("Kinder", "Inception", datetime(2024, 3, 2, 15), 3600, 3600),
        Session("Florian", "Kurz", datetime(2024, 3, 1), 45, 45),
        Session("Florian", "Zweimal kurz", datetime(2024, 3, 1), 70, 70),
        Session("Florian", "Zweimal kurz", datetime(2024, 3, 1, 0, 2), 60, 130),
        Session("Florian", "Dark: Staffel 1: Geheimnisse", datetime(2024, 1, 5), 3000, 3000),
        Session("Florian", "Our Planet: Unser Planet: Eiswelten", datetime(2024, 1, 5), 3000, 3000),
    ]
    res = aggregate_sessions(sessions, source="netflix")
    events = {(e.profile, e.raw_title): e for e in res.events}
    assert set(events) == {
        ("Florian", "Inception"),
        ("Kinder", "Inception"),
        ("Florian", "Zweimal kurz"),
        ("Florian", "Our Planet: Unser Planet: Eiswelten"),
    }
    inc = events[("Florian", "Inception")]
    assert inc.total_watch_seconds == 7500
    assert inc.max_position_seconds == 7500
    assert inc.sessions == 2
    assert inc.first_seen == datetime(2024, 3, 10, 20)
    assert inc.last_seen == datetime(2024, 3, 11, 19)
    assert inc.source == "netflix"
    assert inc.kind == KIND_MOVIE
    assert events[("Florian", "Our Planet: Unser Planet: Eiswelten")].kind == KIND_AMBIGUOUS
    assert res.skipped_series == 1
    assert res.skipped_short == 1


def test_aggregate_without_durations_keeps_everything() -> None:
    sessions = [Session("Florian", "Der Pate", datetime(2024, 1, 1), None, None)] * 2
    res = aggregate_sessions(sessions, source="netflix")
    assert len(res.events) == 1
    assert res.events[0].sessions == 2
    assert res.events[0].total_watch_seconds is None


def test_watched_fraction_and_year_are_kept() -> None:
    sessions = [Session("Florian", "Soul", None, None, None, year=2020, watched_fraction=0.4)]
    ev = aggregate_sessions(sessions, source="csv", min_watch_seconds=None).events[0]
    assert ev.year == 2020
    assert ev.hints["watched_fraction"] == pytest.approx(0.4)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Date Watched (UTC)", "datewatchedutc"),
        ("Profil-Name", "profilname"),
        ("Größe", "groesse"),
        ("﻿Title", "title"),
    ],
)
def test_normalize_header(header: str, expected: str) -> None:
    assert normalize_header(header) == expected


def test_read_csv_rows_bom_and_semicolon(tmp_path: Path) -> None:
    p = tmp_path / "a.csv"
    p.write_text("﻿Titel;Datum\nDas Boot;01.04.2024\n\n", encoding="utf-8")
    headers, rows = read_csv_rows(p)
    assert headers == ["Titel", "Datum"]
    assert rows == [{"Titel": "Das Boot", "Datum": "01.04.2024"}]
    q = tmp_path / "b.csv"
    q.write_bytes("Title,Date\nG\xfcnter,1\n".encode("cp1252"))
    headers, rows = read_csv_rows(q)
    assert rows[0]["Title"] == "Günter"
