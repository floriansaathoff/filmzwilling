from __future__ import annotations

import pytest

from filmzwilling.abandonment import (
    ABANDONED,
    FINISHED,
    UNCLEAR,
    UNKNOWN,
    classify,
    describe,
    watch_fraction,
)
from filmzwilling.importers.common import Session, aggregate_sessions


@pytest.mark.parametrize(
    ("fraction", "status"),
    [
        (1.0, FINISHED),
        (0.85, FINISHED),
        (0.8499, UNCLEAR),
        (0.7, UNCLEAR),
        (0.6, UNCLEAR),
        (0.5999, ABANDONED),
        (0.0, ABANDONED),
        (None, UNKNOWN),
    ],
)
def test_thresholds(fraction: float | None, status: str) -> None:
    assert classify(fraction) == status


def test_fraction_prefers_position() -> None:
    assert watch_fraction(60 * 60, 30 * 60, 120) == pytest.approx(0.5)
    assert watch_fraction(None, 90 * 60, 120) == pytest.approx(0.75)
    assert watch_fraction(None, None, 120) is None


def test_fraction_without_runtime() -> None:
    assert watch_fraction(3600, 3600, None) is None
    assert watch_fraction(3600, 3600, 0) is None


def test_fraction_capped() -> None:
    assert watch_fraction(None, 4 * 3600, 100) == 1.0


def test_explicit_watched_fraction() -> None:
    assert watch_fraction(None, None, None, watched_fraction=0.4) == pytest.approx(0.4)
    assert watch_fraction(100, 100, 100, watched_fraction=0.9) == pytest.approx(0.9)


def test_sum_of_sessions_counts() -> None:
    sessions = [
        Session("Florian", "Toni Erdmann", None, 40 * 60, None),
        Session("Florian", "Toni Erdmann", None, 50 * 60, None),
        Session("Florian", "Toni Erdmann", None, 50 * 60, None),
    ]
    event = aggregate_sessions(sessions, source="prime").events[0]
    assert event.total_watch_seconds == 140 * 60
    assert event.sessions == 3
    frac = watch_fraction(event.max_position_seconds, event.total_watch_seconds, 162)
    assert frac == pytest.approx(140 / 162)
    assert classify(frac) == FINISHED


def test_descriptions() -> None:
    assert (
        describe(ABANDONED, 34 / 121, 121, "Florian")
        == "Abgebrochen bei 28 % (34 von 121 Min.), Profil Florian"
    )
    assert (
        describe(FINISHED, 1.0, 121, "Florian")
        == "Zu Ende geschaut (121 von 121 Min.), Profil Florian"
    )
    assert (
        describe(UNCLEAR, 0.72, 100, "Kinder")
        == "Unklar: 72 % gesehen (72 von 100 Min.), Profil Kinder"
    )
    assert describe(UNKNOWN, None, None, "Florian") == "Gesehen, Laufzeit unbekannt, Profil Florian"
    assert describe(FINISHED, 0.9, None, "Lena") == "Zu Ende geschaut (90 %), Profil Lena"
