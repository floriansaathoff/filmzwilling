from __future__ import annotations

import pytest

from conftest import load_json
from filmzwilling.providers import default_provider_ids, is_default_provider, resolve_provider_names
from filmzwilling.tmdb import parse_provider_list


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Netflix", True),
        ("Netflix basic with Ads", True),
        ("Amazon Prime Video", True),
        ("Amazon Prime Video with Ads", True),
        ("Disney Plus", True),
        ("Joyn", True),
        ("Joyn Plus", True),
        ("ARD Mediathek", True),
        ("ZDF", True),
        ("ZDFtivi", True),
        ("Arte", True),
        ("ARTE", True),
        ("3sat", True),
        ("Apple TV", False),
        ("Amazon Video", False),
        ("WOW", False),
        ("Smartes Kino", False),
        ("MagentaTV", False),
        ("Amazon Prime Video Free with Ads", True),
        ("Netflix Kids", True),
        ("ZDF Herzkino Amazon Channel", False),
        ("ZDFtivi Amazon channel", False),
        ("Arte Amazon Channel", False),
    ],
)
def test_is_default_provider(name: str, expected: bool) -> None:
    assert is_default_provider(name) is expected


def test_default_ids_from_provider_list() -> None:
    providers = parse_provider_list(load_json("providers_de.json"))
    ids = default_provider_ids(providers)
    assert set(ids) == {8, 9, 337, 304, 219, 537, 234, 1990, 1796, 2100, 421}
    assert ids == sorted(
        ids, key=lambda i: next(p.display_priority for p in providers if p.provider_id == i)
    )


def test_resolve_names() -> None:
    providers = parse_provider_list(load_json("providers_de.json"))
    assert set(resolve_provider_names(["netflix"], providers)) == {8, 1796}
    assert set(resolve_provider_names(["Apple TV", "wow"], providers)) == {2, 30}
    assert resolve_provider_names([], providers) == []
