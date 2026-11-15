"""Streaming providers: default "my providers" resolved by name, never by hard-coded id."""

from __future__ import annotations

from collections.abc import Iterable

from filmzwilling.tmdb import Provider

DEFAULT_PROVIDER_NAMES = (
    "Netflix",
    "Amazon Prime Video",
    "Disney Plus",
    "Joyn",
    "ARD Mediathek",
    "ZDF",
    "Arte",
    "3sat",
)


def is_default_provider(name: str) -> bool:
    raise NotImplementedError


def default_provider_ids(providers: Iterable[Provider]) -> list[int]:
    raise NotImplementedError


def resolve_provider_names(names: Iterable[str], providers: Iterable[Provider]) -> list[int]:
    """Provider ids whose name contains one of `names` (case-insensitive)."""
    raise NotImplementedError
