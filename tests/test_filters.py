from __future__ import annotations

import pytest

from filmzwilling.filters import (
    RecFilter,
    RecItem,
    apply_filters,
    filter_to_params,
    item_matches,
    parse_filter,
    sort_items,
)

ITEMS = [
    RecItem(1, "Netflix-Drama", 8.7, 23, 1999, 120, ("Drama",), ((8, "flatrate"),), 7.9),
    RecItem(2, "ARD-Krimi", 8.1, 12, 2015, 95, ("Krimi", "Drama"), ((219, "free"),), 7.0),
    RecItem(3, "Werbefilm", 7.5, 6, 2005, 150, ("Komödie",), ((1796, "ads"),), 6.5),
    RecItem(
        4, "Nur leihen", 9.2, 40, 2020, 100, ("Drama", "Thriller"), ((2, "rent"), (2, "buy")), 8.4
    ),
    RecItem(5, "Ohne Anbieter", 7.9, 30, 1980, None, ("Western",), (), None),
    RecItem(
        6,
        "Sci-Fi Mix",
        6.0,
        5,
        2010,
        130,
        ("Science Fiction", "Action"),
        ((8, "flatrate"), (2, "buy")),
        7.7,
    ),
]


def ids(items: list[RecItem]) -> list[int]:
    return [i.film_id for i in items]


def test_no_filter_sorted_by_match() -> None:
    assert ids(apply_filters(ITEMS, RecFilter())) == [4, 1, 2, 5, 3, 6]


def test_provider_filter_includes_free_and_ads() -> None:
    f = RecFilter(providers=frozenset({8, 219, 1796, 2}))
    assert ids(apply_filters(ITEMS, f)) == [1, 2, 3, 6]


def test_rent_buy_toggle() -> None:
    f = RecFilter(providers=frozenset({2}), include_rent_buy=True)
    assert ids(apply_filters(ITEMS, f)) == [4, 6]
    assert ids(apply_filters(ITEMS, RecFilter(providers=frozenset({2})))) == []


def test_empty_provider_set_means_nothing_matches() -> None:
    assert apply_filters(ITEMS, RecFilter(providers=frozenset())) == []


def test_genres_or_and() -> None:
    assert ids(apply_filters(ITEMS, RecFilter(genres=("Drama", "Western")))) == [4, 1, 2, 5]
    assert ids(apply_filters(ITEMS, RecFilter(genres=("Drama", "Krimi"), genre_mode="and"))) == [2]
    assert ids(apply_filters(ITEMS, RecFilter(genres=("drama",)))) == [4, 1, 2]


def test_year_runtime_score_support() -> None:
    assert ids(apply_filters(ITEMS, RecFilter(year_from=2000, year_to=2015))) == [2, 3, 6]
    assert ids(apply_filters(ITEMS, RecFilter(max_runtime=120))) == [4, 1, 2]
    assert ids(apply_filters(ITEMS, RecFilter(min_score=8.0))) == [4, 1, 2]
    assert ids(apply_filters(ITEMS, RecFilter(min_support=20))) == [4, 1, 5]


def test_combinations() -> None:
    f = RecFilter(
        providers=frozenset({8, 219, 1796}),
        genres=("Drama", "Komödie"),
        min_score=7.0,
        max_runtime=130,
        year_from=1990,
    )
    assert ids(apply_filters(ITEMS, f)) == [1, 2]
    f2 = RecFilter(
        providers=frozenset({8, 2}), include_rent_buy=True, genres=("Drama",), min_support=20
    )
    assert ids(apply_filters(ITEMS, f2)) == [4, 1]


def test_sorting() -> None:
    assert ids(sort_items(ITEMS, "year")) == [4, 2, 6, 3, 1, 5]
    assert ids(sort_items(ITEMS, "tmdb")) == [4, 1, 6, 2, 3, 5]
    assert ids(apply_filters(ITEMS, RecFilter(sort="year", max_runtime=120))) == [4, 2, 1]
    with pytest.raises(ValueError):
        sort_items(ITEMS, "random")


def test_not_personalized_ignores_score_filters() -> None:
    items = [RecItem(10, "Neu", None, 0, 2024, 100, ("Drama",), ((8, "flatrate"),), 8.0)]
    f = RecFilter(min_score=9.0, min_support=10, providers=frozenset({8}))
    assert ids(apply_filters(items, f, personalized=False)) == [10]
    assert item_matches(items[0], f, personalized=True) is False


def test_parse_filter_defaults() -> None:
    f = parse_filter({}, default_providers=[8, 9])
    assert f.providers == frozenset({8, 9})
    assert f.sort == "match" and f.genre_mode == "or" and f.include_rent_buy is False


def test_parse_filter_values() -> None:
    f = parse_filter(
        {
            "providers": "8,219",
            "genres": ["Drama", "Komödie"],
            "genre_mode": "and",
            "min_score": "7,5",
            "min_support": "10",
            "year_from": "1990",
            "year_to": "2010",
            "max_runtime": "120",
            "rent_buy": "1",
            "sort": "year",
        },
        default_providers=[1],
    )
    assert f == RecFilter(
        providers=frozenset({8, 219}),
        include_rent_buy=True,
        genres=("Drama", "Komödie"),
        genre_mode="and",
        min_score=7.5,
        min_support=10,
        year_from=1990,
        year_to=2010,
        max_runtime=120,
        sort="year",
    )


def test_parse_filter_any_and_invalid() -> None:
    f = parse_filter(
        {"providers": "any", "min_score": "abc", "sort": "bogus", "year_from": ""},
        default_providers=[1],
    )
    assert f.providers is None
    assert f.min_score is None
    assert f.sort == "match"
    assert f.year_from is None
    assert parse_filter({"providers": ""}, default_providers=[1]).providers == frozenset()
    assert parse_filter({"genres": "Drama,Krimi"}, default_providers=[]).genres == (
        "Drama",
        "Krimi",
    )


def test_roundtrip() -> None:
    f = RecFilter(
        providers=frozenset({9, 8}),
        genres=("Drama",),
        min_score=7.5,
        sort="tmdb",
        include_rent_buy=True,
    )
    params = filter_to_params(f)
    assert params["providers"] == "8,9"
    assert parse_filter(params, default_providers=[]) == f
    assert filter_to_params(RecFilter())["providers"] == "any"


def test_exclude_genres() -> None:
    f = RecFilter(exclude_genres=("Drama",))
    assert ids(apply_filters(ITEMS, f)) == [5, 3, 6]
    f = RecFilter(exclude_genres=("drama", "Science Fiction"))
    assert ids(apply_filters(ITEMS, f)) == [5, 3]
    # Exclusion wins over inclusion.
    f = RecFilter(genres=("Krimi", "Western"), exclude_genres=("Drama",))
    assert ids(apply_filters(ITEMS, f)) == [5]


def test_parse_exclude_genres_defaults_and_override() -> None:
    assert parse_filter({}, default_providers=[]).exclude_genres == ()
    f = parse_filter({}, default_providers=[], default_exclude_genres=["Horror", "Western"])
    assert f.exclude_genres == ("Horror", "Western")
    f = parse_filter(
        {"exclude_genres": "Drama"}, default_providers=[], default_exclude_genres=["Horror"]
    )
    assert f.exclude_genres == ("Drama",)
    f = parse_filter({"exclude_genres": ""}, default_providers=[], default_exclude_genres=["X"])
    assert f.exclude_genres == ()


def test_roundtrip_exclude_genres() -> None:
    f = RecFilter(providers=None, exclude_genres=("Horror", "Western"))
    params = filter_to_params(f)
    assert params["exclude_genres"] == "Horror,Western"
    assert parse_filter(params, default_providers=[], default_exclude_genres=["Drama"]) == f
    # An empty exclusion is written out, so saved defaults do not sneak back in.
    params = filter_to_params(RecFilter())
    assert params["exclude_genres"] == ""
    restored = parse_filter(params, default_providers=[], default_exclude_genres=["Drama"])
    assert restored == RecFilter()
