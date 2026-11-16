from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from filmzwilling.importers.prime import (
    ColumnMapping,
    detect_mapping,
    inspect_file,
    load_mapping,
    parse_prime,
    read_records,
)


@pytest.fixture
def prime_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "prime"


def events(result) -> dict[tuple[str, str], object]:
    return {(e.profile, e.raw_title): e for e in result.events}


def test_detect_english_headers() -> None:
    m = detect_mapping(
        [
            "Date Watched (UTC)",
            "Title",
            "Profile Name",
            "Content Type",
            "Watch Duration (Seconds)",
            "Playback Position (Seconds)",
        ]
    )
    assert m.title == "Title"
    assert m.date == "Date Watched (UTC)"
    assert m.profile == "Profile Name"
    assert m.kind == "Content Type"
    assert m.duration == "Watch Duration (Seconds)"
    assert m.position == "Playback Position (Seconds)"
    assert m.units.get("duration", "seconds") == "seconds"


def test_detect_german_headers() -> None:
    m = detect_mapping(
        ["Datum", "Titel", "Profilname", "Typ", "Wiedergabedauer", "Wiedergabeposition"]
    )
    assert (m.title, m.date, m.profile, m.kind, m.duration, m.position) == (
        "Titel",
        "Datum",
        "Profilname",
        "Typ",
        "Wiedergabedauer",
        "Wiedergabeposition",
    )


def test_detect_units_from_header() -> None:
    m = detect_mapping(["Title", "Playback Duration (ms)"])
    assert m.duration == "Playback Duration (ms)"
    assert m.units["duration"] == "ms"
    m2 = detect_mapping(["Title", "Minutes Watched"])
    assert m2.units["duration"] == "minutes"


def test_detect_exporter_headers() -> None:
    m = detect_mapping(
        [
            "Date Watched",
            "Type",
            "Title",
            "Episode Title",
            "Global Title Identifier",
            "Path",
            "Image URL",
        ]
    )
    assert (m.title, m.date, m.kind, m.episode) == (
        "Title",
        "Date Watched",
        "Type",
        "Episode Title",
    )
    assert m.profile is None


def test_parse_english_variant(prime_dir: Path) -> None:
    res = parse_prime(prime_dir / "PrimeVideo.ViewingHistory.csv")
    ev = events(res)
    assert set(ev) == {("Florian", "Das Boot"), ("Lena", "Knives Out")}
    boot = ev[("Florian", "Das Boot")]
    assert boot.sessions == 2  # type: ignore[attr-defined]
    assert boot.total_watch_seconds == 8400  # type: ignore[attr-defined]
    assert boot.max_position_seconds == 8400  # type: ignore[attr-defined]
    assert boot.first_seen == datetime(2024, 4, 1, 20)  # type: ignore[attr-defined]
    assert res.skipped_series == 2  # The Boys (type Episode) + Jack Ryan (pattern)
    assert res.skipped_short == 1
    assert all(e.source == "prime" for e in res.events)


def test_parse_german_variant(prime_dir: Path) -> None:
    res = parse_prime(prime_dir / "PrimeVideo.WatchEvent.csv")
    ev = events(res)
    assert set(ev) == {
        ("Florian", "Das Boot"),
        ("Lena", "Der Schuh des Manitu"),
        ("Florian", "Good Bye, Lenin!"),
    }
    assert ev[("Florian", "Das Boot")].total_watch_seconds == 8400  # type: ignore[attr-defined]
    lenin = ev[("Florian", "Good Bye, Lenin!")]
    assert lenin.max_position_seconds == 7080  # type: ignore[attr-defined]
    assert lenin.first_seen == datetime(2024, 4, 4, 19)  # type: ignore[attr-defined]


def test_parse_exporter_csv(prime_dir: Path) -> None:
    res = parse_prime(prime_dir / "watch-history-exporter.csv")
    ev = events(res)
    assert set(ev) == {("Prime Video", "Oppenheimer"), ("Prime Video", "Saltburn")}
    assert res.skipped_series == 1


def test_parse_exporter_json(prime_dir: Path) -> None:
    fmt, headers, records = read_records(prime_dir / "watch-history-exporter.json")
    assert fmt == "json"
    assert "title" in headers and "episodeTitle" in headers
    assert len(records) == 4
    res = parse_prime(prime_dir / "watch-history-exporter.json")
    ev = events(res)
    assert set(ev) == {("Prime Video", "Oppenheimer"), ("Prime Video", "Anatomie eines Falls")}
    opp = ev[("Prime Video", "Oppenheimer")]
    assert opp.sessions == 2  # type: ignore[attr-defined]
    assert opp.last_seen == datetime(2024, 5, 4, 20)  # type: ignore[attr-defined]


def test_parse_json_wrapped_object(tmp_path: Path) -> None:
    p = tmp_path / "history.json"
    p.write_text(
        '{"movies": [{"title": "Oppenheimer", "date": "2024-05-01"}],'
        ' "episodes": [{"title": "The Boys", "episodeTitle": "Pilot", "date": "2024-05-01"}]}',
        encoding="utf-8",
    )
    res = parse_prime(p)
    assert [e.raw_title for e in res.events] == ["Oppenheimer"]


def test_mapping_override(prime_dir: Path) -> None:
    base = detect_mapping(["Wann", "Sendung", "Wer", "Minuten", "Bemerkung"])
    assert base.title is None
    mapping = load_mapping(prime_dir / "mapping.toml", base)
    assert mapping.title == "Sendung"
    assert mapping.units["duration"] == "minutes"
    res = parse_prime(prime_dir / "custom.csv", mapping)
    ev = events(res)
    assert ev[("Florian", "Das Boot")].total_watch_seconds == 150 * 60  # type: ignore[attr-defined]
    assert ev[("Florian", "Toni Erdmann")].total_watch_seconds == 40 * 60  # type: ignore[attr-defined]


def test_missing_title_column_is_an_error(prime_dir: Path) -> None:
    with pytest.raises(ValueError, match="Titel"):
        parse_prime(prime_dir / "custom.csv")


def test_invalid_mapping_column(prime_dir: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('[columns]\ntitle = "Gibtsnicht"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Gibtsnicht"):
        parse_prime(
            prime_dir / "custom.csv", load_mapping(bad, detect_mapping(["Wann", "Sendung"]))
        )


def test_inspect(prime_dir: Path) -> None:
    report = inspect_file(prime_dir / "PrimeVideo.WatchEvent.csv")
    assert report.format == "csv"
    assert report.headers == [
        "Datum",
        "Titel",
        "Profilname",
        "Typ",
        "Wiedergabedauer",
        "Wiedergabeposition",
    ]
    assert report.mapping.title == "Titel"
    assert report.row_count == 4
    assert len(report.sample) <= 5
    with_mapping = inspect_file(prime_dir / "custom.csv", prime_dir / "mapping.toml")
    assert with_mapping.mapping.title == "Sendung"
    assert with_mapping.mapping.as_dict()["title"] == "Sendung"


def test_default_profile(prime_dir: Path) -> None:
    m = ColumnMapping(title="Title", default_profile="Wohnzimmer")
    res = parse_prime(prime_dir / "watch-history-exporter.csv", m)
    assert {e.profile for e in res.events} == {"Wohnzimmer"}


def test_prime_import_idempotent(service, prime_dir: Path) -> None:
    res = parse_prime(prime_dir / "PrimeVideo.ViewingHistory.csv")
    assert service.store_import(res).inserted == 2
    again = service.store_import(parse_prime(prime_dir / "PrimeVideo.ViewingHistory.csv"))
    assert again.inserted == 0 and again.unchanged == 2
