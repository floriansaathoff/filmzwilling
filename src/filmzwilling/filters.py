"""Filtering and sorting of recommendation tiles; filters round-trip through URL params."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

INCLUDED_CATEGORIES = ("flatrate", "free", "ads")
PAID_CATEGORIES = ("rent", "buy")
SORT_OPTIONS = ("match", "year", "tmdb")
TRUE_VALUES = {"1", "true", "on", "yes", "ja"}


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
    exclude_genres: tuple[str, ...] = ()
    min_score: float | None = None
    min_support: int | None = None
    year_from: int | None = None
    year_to: int | None = None
    max_runtime: int | None = None
    sort: str = "match"


def _offers_match(item: RecItem, flt: RecFilter) -> bool:
    if flt.providers is None:
        return True
    categories = INCLUDED_CATEGORIES + (PAID_CATEGORIES if flt.include_rent_buy else ())
    return any(pid in flt.providers and cat in categories for pid, cat in item.offers)


def _genres_match(item: RecItem, flt: RecFilter) -> bool:
    have = {g.lower() for g in item.genres}
    if any(g.lower() in have for g in flt.exclude_genres):
        return False
    if not flt.genres:
        return True
    wanted = [g.lower() for g in flt.genres]
    if flt.genre_mode == "and":
        return all(g in have for g in wanted)
    return any(g in have for g in wanted)


def item_matches(item: RecItem, flt: RecFilter, *, personalized: bool = True) -> bool:
    if not _offers_match(item, flt) or not _genres_match(item, flt):
        return False
    if flt.year_from is not None and (item.year is None or item.year < flt.year_from):
        return False
    if flt.year_to is not None and (item.year is None or item.year > flt.year_to):
        return False
    if flt.max_runtime is not None and (item.runtime is None or item.runtime > flt.max_runtime):
        return False
    if personalized:
        if flt.min_score is not None and (item.score is None or item.score < flt.min_score):
            return False
        if flt.min_support is not None and item.support < flt.min_support:
            return False
    return True


def _neg(value: float | None) -> tuple[int, float]:
    return (1, 0.0) if value is None else (0, -float(value))


def sort_items(items: Iterable[RecItem], sort: str) -> list[RecItem]:
    if sort not in SORT_OPTIONS:
        raise ValueError(f"Unbekannte Sortierung: {sort}")
    if sort == "year":
        return sorted(items, key=lambda i: (_neg(i.year), _neg(i.score), i.film_id))
    if sort == "tmdb":
        return sorted(items, key=lambda i: (_neg(i.vote_average), _neg(i.score), i.film_id))
    return sorted(items, key=lambda i: (_neg(i.score), i.film_id))


def apply_filters(
    items: Sequence[RecItem], flt: RecFilter, *, personalized: bool = True
) -> list[RecItem]:
    chosen = [i for i in items if item_matches(i, flt, personalized=personalized)]
    return sort_items(chosen, flt.sort)


def _values(params: Mapping[str, Any], name: str) -> list[str] | None:
    if name not in params:
        return None
    raw = params[name]
    parts = raw if isinstance(raw, list | tuple) else [raw]
    values: list[str] = []
    for part in parts:
        values.extend(v.strip() for v in str(part).split(","))
    return [v for v in values if v]


def _first(params: Mapping[str, Any], name: str) -> str:
    """Scalar parameter (not split at commas, so "7,5" stays a German decimal number)."""
    raw = params.get(name)
    if isinstance(raw, list | tuple):
        raw = raw[0] if raw else ""
    return "" if raw is None else str(raw).strip()


def _int(params: Mapping[str, Any], name: str) -> int | None:
    text = _first(params, name)
    try:
        return int(text)
    except ValueError:
        return None


def _float(params: Mapping[str, Any], name: str) -> float | None:
    text = _first(params, name).replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_filter(
    params: Mapping[str, Any],
    default_providers: Iterable[int],
    default_exclude_genres: Iterable[str] = (),
) -> RecFilter:
    """Build a filter from URL query params; missing `providers` or `exclude_genres` means
    the saved defaults, an empty value means none."""
    provider_values = _values(params, "providers")
    providers: frozenset[int] | None
    if provider_values is None:
        providers = frozenset(int(p) for p in default_providers)
    elif any(v.lower() == "any" for v in provider_values):
        providers = None
    else:
        providers = frozenset(int(v) for v in provider_values if v.lstrip("-").isdigit())
    exclude_values = _values(params, "exclude_genres")
    exclude_genres = tuple(default_exclude_genres if exclude_values is None else exclude_values)
    sort = _first(params, "sort")
    return RecFilter(
        providers=providers,
        include_rent_buy=_first(params, "rent_buy").lower() in TRUE_VALUES,
        genres=tuple(_values(params, "genres") or ()),
        genre_mode="and" if _first(params, "genre_mode").lower() == "and" else "or",
        exclude_genres=exclude_genres,
        min_score=_float(params, "min_score"),
        min_support=_int(params, "min_support"),
        year_from=_int(params, "year_from"),
        year_to=_int(params, "year_to"),
        max_runtime=_int(params, "max_runtime"),
        sort=sort if sort in SORT_OPTIONS else "match",
    )


def filter_to_params(flt: RecFilter) -> dict[str, str]:
    params: dict[str, str] = {
        "providers": "any"
        if flt.providers is None
        else ",".join(str(p) for p in sorted(flt.providers))
    }
    if flt.include_rent_buy:
        params["rent_buy"] = "1"
    if flt.genres:
        params["genres"] = ",".join(flt.genres)
    if flt.genre_mode == "and":
        params["genre_mode"] = "and"
    # Always written, so an empty exclusion is not replaced by the saved defaults.
    params["exclude_genres"] = ",".join(flt.exclude_genres)
    if flt.min_score is not None:
        params["min_score"] = f"{flt.min_score:g}"
    for name in ("min_support", "year_from", "year_to", "max_runtime"):
        value = getattr(flt, name)
        if value is not None:
            params[name] = str(value)
    if flt.sort != "match":
        params["sort"] = flt.sort
    return params
