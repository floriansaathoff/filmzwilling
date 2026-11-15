"""Filtering and sorting of recommendation tiles; filters round-trip through URL params."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

INCLUDED_CATEGORIES = ("flatrate", "free", "ads")
PAID_CATEGORIES = ("rent", "buy")
SORT_OPTIONS = ("match", "year", "tmdb")


@dataclass(frozen=True)
class RecItem:
    film_id: int
    title: str
    score: float | None
    support: int
    year: int | None = None
    runtime: int | None = None
    genres: tuple[str, ...] = ()
    offers: tuple[tuple[int, str], ...] = ()
    vote_average: float | None = None
    extra: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class RecFilter:
    providers: frozenset[int] | None = None
    include_rent_buy: bool = False
    genres: tuple[str, ...] = ()
    genre_mode: str = "or"
    min_score: float | None = None
    min_support: int | None = None
    year_from: int | None = None
    year_to: int | None = None
    max_runtime: int | None = None
    sort: str = "match"


def item_matches(item: RecItem, flt: RecFilter, *, personalized: bool = True) -> bool:
    raise NotImplementedError


def sort_items(items: Iterable[RecItem], sort: str) -> list[RecItem]:
    raise NotImplementedError


def apply_filters(
    items: Sequence[RecItem], flt: RecFilter, *, personalized: bool = True
) -> list[RecItem]:
    raise NotImplementedError


def parse_filter(params: Mapping[str, Any], default_providers: Iterable[int]) -> RecFilter:
    """Build a filter from URL query params; missing `providers` means the defaults."""
    raise NotImplementedError


def filter_to_params(flt: RecFilter) -> dict[str, str]:
    raise NotImplementedError
