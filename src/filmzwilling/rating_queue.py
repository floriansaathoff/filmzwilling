"""The rating queue: imported films first, then popular MovieLens films.

Order: (1) own profiles, watched to the end, newest first; (2) own profiles, abandoned, unclear or
unknown; (3) family profiles; (4) MovieLens films by number of ratings until `queue_size` films
from source 4 are part of the queue. Deferred films ("Später") move to the end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from filmzwilling.abandonment import (
    ABANDONED,
    FINISHED,
    UNCLEAR,
    classify,
    describe,
    watch_fraction,
)

SOURCE_OWN_FINISHED = 1
SOURCE_OWN_OTHER = 2
SOURCE_FAMILY = 3
SOURCE_POPULAR = 4

SOURCE_LABELS = {
    "netflix": "Netflix",
    "prime": "Prime Video",
    "csv": "Liste",
    "disney": "Disney+",
    "demo": "Demo",
}
THUMB_TEXT = {"down": "Daumen runter", "up": "Daumen hoch", "love": "Zwei Daumen hoch"}


@dataclass
class QueueEntry:
    film_id: int
    source: int
    last_seen: str | None = None
    hints: list[dict[str, Any]] = field(default_factory=list)
    highlight_low: bool = False


@dataclass(frozen=True)
class Progress:
    rated: int
    not_seen: int
    remaining: int
    total: int

    def as_dict(self) -> dict[str, int]:
        return {
            "rated": self.rated,
            "not_seen": self.not_seen,
            "remaining": self.remaining,
            "total": self.total,
        }


def source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source.capitalize())


def _imported_entries(repo: Any) -> list[QueueEntry]:
    events = repo.events_with_films()
    if not events:
        return []
    film_for_tmdb = repo.film_ids_for_tmdb({e.tmdb_id for e in events})
    films = repo.get_films(film_for_tmdb.values())
    settings = repo.get_user_settings()
    mine = set(settings.my_profiles) or {e.profile for e in events}

    grouped: dict[int, list[Any]] = {}
    for event in events:
        film_id = film_for_tmdb.get(event.tmdb_id)
        if film_id is not None:
            grouped.setdefault(film_id, []).append(event)

    entries: list[QueueEntry] = []
    for film_id, film_events in grouped.items():
        film = films.get(film_id)
        runtime = film.runtime if film else None
        own = [e for e in film_events if e.profile in mine]
        decisive = own or film_events
        hints: list[dict[str, Any]] = []
        statuses = []
        for event in sorted(film_events, key=lambda e: (e.profile not in mine, e.profile)):
            hints.append(
                {"kind": "source", "text": f"{source_label(event.source)} · Profil {event.profile}"}
            )
            fraction = watch_fraction(
                event.max_position_seconds,
                event.total_watch_seconds,
                runtime,
                event.hints.get("watched_fraction"),
            )
            status = classify(fraction) if event.sessions or fraction is not None else "unknown"
            if event in decisive:
                statuses.append(status)
            if status in (ABANDONED, UNCLEAR):
                hints.append(
                    {"kind": status, "text": describe(status, fraction, runtime, event.profile)}
                )
            thumbs = event.hints.get("netflix_thumbs")
            if thumbs in THUMB_TEXT:
                hints.append(
                    {"kind": "thumbs", "text": f"Netflix: {THUMB_TEXT[thumbs]} ({event.profile})"}
                )
        if own:
            source = SOURCE_OWN_FINISHED if FINISHED in statuses else SOURCE_OWN_OTHER
        else:
            source = SOURCE_FAMILY
        last_seen = max((e.last_seen for e in decisive if e.last_seen), default=None)
        entries.append(
            QueueEntry(
                film_id=film_id,
                source=source,
                last_seen=last_seen,
                hints=hints,
                highlight_low=ABANDONED in statuses and FINISHED not in statuses,
            )
        )
    entries.sort(key=lambda e: (e.source, _desc(e.last_seen), e.film_id))
    return entries


def _desc(value: str | None) -> tuple[int, str]:
    """Sort key for 'newest first, missing dates last'."""
    if not value:
        return (1, "")
    inverted = "".join(chr(0x10FFFF - ord(c)) for c in value)
    return (0, inverted)


def build_queue(repo: Any, *, include_done: bool = False) -> list[QueueEntry]:
    """Ordered queue (sources 1-4, deferred films at the end, no duplicates).

    With include_done=True also rated/not-seen films of the queue set are returned (for progress).
    """
    settings = repo.get_user_settings()
    statuses = repo.statuses()
    rated = repo.rated_film_ids()
    not_interested = {f for f, s in statuses.items() if s == "not_interested"}
    done = rated | {f for f, s in statuses.items() if s == "not_seen"}

    imported = [e for e in _imported_entries(repo) if e.film_id not in not_interested]
    seen = {e.film_id for e in imported}
    popular: list[QueueEntry] = []
    if settings.queue_size > 0:
        limit = settings.queue_size + len(seen) + len(not_interested)
        for film_id in repo.popular_film_ids(limit):
            if film_id in seen or film_id in not_interested:
                continue
            popular.append(QueueEntry(film_id=film_id, source=SOURCE_POPULAR))
            seen.add(film_id)
            if len(popular) >= settings.queue_size:
                break
    entries = imported + popular
    if not include_done:
        entries = [e for e in entries if e.film_id not in done]
    deferred = repo.deferred_order()
    regular = [e for e in entries if e.film_id not in deferred]
    later = sorted((e for e in entries if e.film_id in deferred), key=lambda e: deferred[e.film_id])
    return regular + later


def queue_progress(repo: Any) -> Progress:
    full = build_queue(repo, include_done=True)
    statuses = repo.statuses()
    rated = repo.rated_film_ids()
    done = rated | {f for f, s in statuses.items() if s == "not_seen"}
    remaining = sum(1 for e in full if e.film_id not in done)
    return Progress(
        rated=len(rated),
        not_seen=sum(1 for s in statuses.values() if s == "not_seen"),
        remaining=remaining,
        total=len(full),
    )
