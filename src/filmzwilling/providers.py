"""Streaming providers: default "my providers" resolved by name, never by hard-coded id."""

from __future__ import annotations

import re
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

# Long names match as substrings ("Netflix basic with Ads"), short ones only at a word start so
# that e.g. "Smartes Kino" does not count as Arte (see docs/ENTSCHEIDUNGEN.md).
_DEFAULT_PATTERNS = (
    re.compile(r"netflix", re.IGNORECASE),
    re.compile(r"amazon prime video", re.IGNORECASE),
    re.compile(r"disney\s*(plus|\+)", re.IGNORECASE),
    re.compile(r"\bjoyn", re.IGNORECASE),
    re.compile(r"ard\s+mediathek", re.IGNORECASE),
    re.compile(r"\bzdf", re.IGNORECASE),
    re.compile(r"\barte\b", re.IGNORECASE),
    re.compile(r"\b3sat\b", re.IGNORECASE),
)


def is_default_provider(name: str) -> bool:
    return any(p.search(name) for p in _DEFAULT_PATTERNS)


def default_provider_ids(providers: Iterable[Provider]) -> list[int]:
    chosen = [p for p in providers if is_default_provider(p.name)]
    chosen.sort(key=lambda p: (p.display_priority, p.name.lower()))
    return list(dict.fromkeys(p.provider_id for p in chosen))


def resolve_provider_names(names: Iterable[str], providers: Iterable[Provider]) -> list[int]:
    """Provider ids whose name contains one of `names` (case-insensitive)."""
    needles = [n.strip().lower() for n in names if n.strip()]
    if not needles:
        return []
    return [p.provider_id for p in providers if any(n in p.name.lower() for n in needles)]
