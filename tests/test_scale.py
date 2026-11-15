from __future__ import annotations

import math

import numpy as np
import pytest

from filmzwilling.scale import from_ml, from_ml_array, to_ml, to_ml_array


def test_bounds() -> None:
    assert to_ml(0) == pytest.approx(0.5)
    assert to_ml(10) == pytest.approx(5.0)
    assert to_ml(5) == pytest.approx(2.75)


def test_from_ml_bounds() -> None:
    assert from_ml(0.5) == pytest.approx(0.0)
    assert from_ml(5.0) == pytest.approx(10.0)
    assert from_ml(2.75) == pytest.approx(5.0)


@pytest.mark.parametrize("note", range(11))
def test_roundtrip(note: int) -> None:
    assert from_ml(to_ml(note)) == pytest.approx(note)


def test_from_ml_clips_to_range() -> None:
    assert from_ml(0.0) == 0.0
    assert from_ml(-3.0) == 0.0
    assert from_ml(5.5) == 10.0
    assert from_ml(99.0) == 10.0


def test_integral_float_is_accepted() -> None:
    assert to_ml(7.0) == pytest.approx(3.65)  # type: ignore[arg-type]
    assert to_ml(np.int64(3)) == pytest.approx(1.85)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [-1, 11, 7.5, 0.1, 100, float("nan"), math.inf, "7", None, True])
def test_invalid_notes_raise(bad: object) -> None:
    with pytest.raises(ValueError):
        to_ml(bad)  # type: ignore[arg-type]


def test_array_versions() -> None:
    np.testing.assert_allclose(to_ml_array([0, 5, 10]), [0.5, 2.75, 5.0])
    np.testing.assert_allclose(from_ml_array([0.5, 2.75, 5.0, 6.0, 0.0]), [0, 5, 10, 10, 0])
    with pytest.raises(ValueError):
        to_ml_array([1, 2, 11])
    with pytest.raises(ValueError):
        to_ml_array([1.5])


def test_linear_formula() -> None:
    for note in range(11):
        assert to_ml(note) == pytest.approx(0.5 + 0.45 * note)
    assert from_ml(3.0) == pytest.approx((3.0 - 0.5) / 0.45)
