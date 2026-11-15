from __future__ import annotations

from datetime import datetime

import pytest

from filmzwilling.importers.common import WatchEvent
from filmzwilling.rating_queue import (
    SOURCE_FAMILY,
    SOURCE_OWN_FINISHED,
    SOURCE_OWN_OTHER,
    SOURCE_POPULAR,
    build_queue,
    queue_progress,
)
from filmzwilling.repository import MovieLensFilm, Repository
from filmzwilling.tmdb import MovieDetails


def ml(i: int, tmdb: int | None) -> MovieLensFilm:
    return MovieLensFilm(i, tmdb, f"Film {i}", 2000, ["Drama"], 1000 - i, 3.5, i)


@pytest.fixture
def qrepo(repo: Repository) -> Repository:
    films = [ml(i, 500 + i) for i in range(1, 31)]
    films[4] = ml(5, None)  # no tmdb id -> never in source 4
    repo.upsert_movielens_films(films)
    runtimes = {"A": 100, "B": 120, "C": 100, "E": 90}
    tmdb_for = {"A": 520, "B": 521, "C": 522, "D": 9001, "E": 523}
    for key, tmdb in tmdb_for.items():
        repo.upsert_tmdb_details(
            MovieDetails(
                tmdb_id=tmdb,
                title=f"Titel {key}",
                original_title=key,
                runtime=runtimes.get(key),
                genres=["Drama"],
                poster_path=None,
                vote_average=7.0,
                vote_count=10,
                release_date="2001-01-01",
            )
        )

    def add(title: str, profile: str, last: datetime, pos_min: int | None, tmdb: int) -> None:
        repo.upsert_watch_event(
            WatchEvent(
                source="netflix",
                profile=profile,
                raw_title=title,
                first_seen=last,
                last_seen=last,
                total_watch_seconds=(pos_min or 0) * 60 or None,
                max_position_seconds=pos_min * 60 if pos_min is not None else None,
                sessions=1,
            )
        )
        repo.assign_title(title, tmdb)

    add("A", "Florian", datetime(2024, 3, 10), 98, 520)  # finished
    add("B", "Florian", datetime(2024, 4, 1), 118, 521)  # finished, newer
    add("C", "Florian", datetime(2024, 2, 1), 28, 522)  # abandoned
    add("D", "Florian", datetime(2024, 1, 1), 50, 9001)  # unknown runtime, not in MovieLens
    add("E", "Kinder", datetime(2024, 3, 1), 90, 523)  # family
    repo.upsert_watch_event(
        WatchEvent(
            source="netflix",
            profile="Kinder",
            raw_title="A",
            last_seen=datetime(2024, 5, 1),
            total_watch_seconds=6000,
        )
    )
    repo.assign_title("A", 520)
    repo.update_user_settings(my_profiles=["Florian"], queue_size=5)
    return repo


def fid(repo: Repository, tmdb: int) -> int:
    f = repo.film_id_for_tmdb(tmdb)
    assert f is not None
    return f


def test_order_of_sources(qrepo: Repository) -> None:
    q = build_queue(qrepo)
    ids = [e.film_id for e in q]
    a, b, c, d, e = (fid(qrepo, t) for t in (520, 521, 522, 9001, 523))
    assert ids[:5] == [b, a, c, d, e]
    assert [x.source for x in q[:5]] == [
        SOURCE_OWN_FINISHED,
        SOURCE_OWN_FINISHED,
        SOURCE_OWN_OTHER,
        SOURCE_OWN_OTHER,
        SOURCE_FAMILY,
    ]
    popular = q[5:]
    assert len(popular) == 5
    assert all(x.source == SOURCE_POPULAR for x in popular)
    expected_popular = [fid(qrepo, 500 + i) for i in (1, 2, 3, 4, 6)]
    assert [x.film_id for x in popular] == expected_popular
    assert len(ids) == len(set(ids))


def test_source4_requires_both_ids(qrepo: Repository) -> None:
    q = build_queue(qrepo)
    no_tmdb = qrepo.film_id_for_movielens(5)
    assert no_tmdb not in {e.film_id for e in q}
    d = fid(qrepo, 9001)
    assert [e.source for e in q if e.film_id == d] == [SOURCE_OWN_OTHER]


def test_exclusions(qrepo: Repository) -> None:
    b, c, e = fid(qrepo, 521), fid(qrepo, 522), fid(qrepo, 523)
    p1 = fid(qrepo, 501)
    qrepo.set_rating(b, 9)
    qrepo.mark_not_seen(c)
    qrepo.mark_not_interested(e)
    qrepo.mark_not_seen(p1)
    ids = [x.film_id for x in build_queue(qrepo)]
    assert not {b, c, e, p1} & set(ids)
    # Source 4 still contains queue_size films in total (rated / not seen ones count as done)
    full = build_queue(qrepo, include_done=True)
    assert sum(1 for x in full if x.source == SOURCE_POPULAR) == 5
    assert p1 in {x.film_id for x in full}


def test_later_moves_to_end_and_undo(qrepo: Repository) -> None:
    a, b = fid(qrepo, 520), fid(qrepo, 521)
    qrepo.defer(b)
    ids = [x.film_id for x in build_queue(qrepo)]
    assert ids[-1] == b
    qrepo.defer(a)
    ids = [x.film_id for x in build_queue(qrepo)]
    assert ids[-2:] == [b, a]
    original = [x for x in ids if x not in (a, b)]
    qrepo.set_rating(ids[0], 5)
    qrepo.mark_not_seen(ids[1])
    assert [x.film_id for x in build_queue(qrepo)] == ids[2:]
    qrepo.undo_last()
    qrepo.undo_last()
    assert [x.film_id for x in build_queue(qrepo)] == ids
    qrepo.undo_last()
    qrepo.undo_last()
    restored = [x.film_id for x in build_queue(qrepo)]
    assert restored[:2] == [b, a]
    assert [x for x in restored if x not in (a, b)] == original


def test_progress(qrepo: Repository) -> None:
    p = queue_progress(qrepo)
    assert (p.rated, p.not_seen, p.remaining, p.total) == (0, 0, 10, 10)
    ids = [x.film_id for x in build_queue(qrepo)]
    qrepo.set_rating(ids[0], 8)
    qrepo.set_rating(ids[1], 2)
    qrepo.mark_not_seen(ids[2])
    p = queue_progress(qrepo)
    assert (p.rated, p.not_seen, p.remaining) == (2, 1, 7)
    assert p.as_dict() == {"rated": 2, "not_seen": 1, "remaining": 7, "total": 10}


def test_queue_size_setting(qrepo: Repository) -> None:
    qrepo.update_user_settings(queue_size=2)
    assert sum(1 for x in build_queue(qrepo) if x.source == SOURCE_POPULAR) == 2
    qrepo.update_user_settings(queue_size=0)
    assert all(x.source != SOURCE_POPULAR for x in build_queue(qrepo))


def test_family_profile_film_watched_by_me_counts_as_mine(qrepo: Repository) -> None:
    a = fid(qrepo, 520)
    entry = next(x for x in build_queue(qrepo) if x.film_id == a)
    assert entry.source == SOURCE_OWN_FINISHED
    texts = " ".join(h["text"] for h in entry.hints)
    assert "Florian" in texts and "Kinder" in texts


def test_without_configured_profiles_all_are_mine(qrepo: Repository) -> None:
    qrepo.update_user_settings(my_profiles=[])
    e = fid(qrepo, 523)
    entry = next(x for x in build_queue(qrepo) if x.film_id == e)
    assert entry.source == SOURCE_OWN_FINISHED


def test_hints_for_abandoned(qrepo: Repository) -> None:
    c = fid(qrepo, 522)
    entry = next(x for x in build_queue(qrepo) if x.film_id == c)
    assert entry.highlight_low is True
    assert any(
        h["kind"] == "abandoned" and h["text"].startswith("Abgebrochen bei 28 %")
        for h in entry.hints
    )
    assert any(h["kind"] == "source" for h in entry.hints)
    a = fid(qrepo, 520)
    entry_a = next(x for x in build_queue(qrepo) if x.film_id == a)
    assert entry_a.highlight_low is False


def test_thumbs_hint(qrepo: Repository) -> None:
    qrepo.merge_event_hints("netflix", "Florian", "B", {"netflix_thumbs": "love"})
    b = fid(qrepo, 521)
    entry = next(x for x in build_queue(qrepo) if x.film_id == b)
    thumbs = [h for h in entry.hints if h["kind"] == "thumbs"]
    assert thumbs and "Florian" in thumbs[0]["text"]
