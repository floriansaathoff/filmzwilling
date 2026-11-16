from __future__ import annotations

from pathlib import Path

import pytest

from filmzwilling.importers.generic_csv import parse_fraction, parse_generic_csv


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.85", 0.85),
        ("0,85", 0.85),
        ("85%", 0.85),
        ("85 %", 0.85),
        ("85", 0.85),
        ("1", 1.0),
        ("", None),
        (None, None),
        ("abc", None),
        ("150", 1.0),
    ],
)
def test_parse_fraction(value: str | None, expected: float | None) -> None:
    result = parse_fraction(value)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_parse_generic(fixtures_dir: Path) -> None:
    res = parse_generic_csv(fixtures_dir / "csv" / "disney.csv")
    ev = {(e.profile, e.raw_title): e for e in res.events}
    assert set(ev) == {
        ("Florian", "Das Leben der Anderen"),
        ("Florian", "Der Schuh des Manitu"),
        ("Kinder", "Soul"),
        ("Manuell", "Encanto"),
        ("Florian", "Toni Erdmann"),
    }
    lda = ev[("Florian", "Das Leben der Anderen")]
    assert lda.year == 2006  # type: ignore[attr-defined]
    assert lda.hints["watched_fraction"] == pytest.approx(1.0)  # type: ignore[attr-defined]
    assert ev[("Manuell", "Encanto")].hints["watched_fraction"] == pytest.approx(0.85)  # type: ignore[attr-defined]
    assert "watched_fraction" not in ev[("Kinder", "Soul")].hints  # type: ignore[attr-defined]
    assert ev[("Kinder", "Soul")].year == 2020  # type: ignore[attr-defined]
    assert res.skipped_invalid == 1
    assert res.skipped_series == 1
    assert all(e.source == "csv" for e in res.events)


def test_semicolon_and_bom(fixtures_dir: Path) -> None:
    res = parse_generic_csv(fixtures_dir / "csv" / "semicolon.csv")
    ev = {e.raw_title: e for e in res.events}
    assert ev["Das Leben der Anderen"].hints["watched_fraction"] == pytest.approx(0.95)
    assert ev["Ratatouille"].profile == "Kinder"


def test_custom_source(fixtures_dir: Path) -> None:
    res = parse_generic_csv(fixtures_dir / "csv" / "semicolon.csv", source="disney")
    assert {e.source for e in res.events} == {"disney"}


def test_missing_title_column(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    p.write_text("name,year\nA,2000\n", encoding="utf-8")
    with pytest.raises(ValueError, match="title"):
        parse_generic_csv(p)


def test_generic_import_idempotent(service, fixtures_dir: Path) -> None:
    first = service.store_import(parse_generic_csv(fixtures_dir / "csv" / "disney.csv"))
    assert first.inserted == 5
    second = service.store_import(parse_generic_csv(fixtures_dir / "csv" / "disney.csv"))
    assert second.inserted == 0
    assert service.repo.count_watch_events() == 5
