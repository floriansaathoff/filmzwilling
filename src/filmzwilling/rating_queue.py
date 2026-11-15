"""The rating queue: imported films first, then popular MovieLens films."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SOURCE_OWN_FINISHED = 1
SOURCE_OWN_OTHER = 2
SOURCE_FAMILY = 3
SOURCE_POPULAR = 4


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


def build_queue(repo: Any, *, include_done: bool = False) -> list[QueueEntry]:
    """Ordered queue (sources 1-4, deferred films at the end, no duplicates).

    With include_done=True also rated/not-seen films of the queue set are returned (for progress).
    """
    raise NotImplementedError


def queue_progress(repo: Any) -> Progress:
    raise NotImplementedError
