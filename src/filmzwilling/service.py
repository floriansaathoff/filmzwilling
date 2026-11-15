"""Application service: glues repository, MovieLens data, TMDB and the recommender together."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from rapidfuzz import fuzz, process

from filmzwilling import matching
from filmzwilling.config import RecommenderConfig, Settings
from filmzwilling.db import Database
from filmzwilling.evaluate import EvalResult, cross_validate
from filmzwilling.filters import RecFilter, RecItem, apply_filters, filter_to_params, parse_filter
from filmzwilling.importers.common import ImportReport, ParseResult, store_events
from filmzwilling.importers.generic_csv import parse_generic_csv
from filmzwilling.importers.netflix import parse_netflix
from filmzwilling.importers.prime import detect_mapping, load_mapping, parse_prime, read_records
from filmzwilling.movielens import (
    ProcessedData,
    clean_ml_title,
    load_processed,
    move_article,
    parse_ml_title,
)
from filmzwilling.providers import default_provider_ids
from filmzwilling.rating_queue import Progress, QueueEntry, build_queue, queue_progress
from filmzwilling.recommender import recommend
from filmzwilling.repository import (
    Film,
    MovieLensFilm,
    Offer,
    Repository,
    StoredRecommendation,
    StoredTwin,
)
from filmzwilling.scale import from_ml, validate_note
from filmzwilling.tmdb import MovieDetails, Provider, TMDBClient, poster_url

log = logging.getLogger(__name__)

NO_DATA_MESSAGE = "MovieLens-Daten fehlen. Bitte zuerst 'filmzwilling setup' ausführen."
OFFLINE_MESSAGE = "TMDB ist nicht verfügbar (Offline- oder Demo-Modus)."
TMDB_MOVIE_URL = "https://www.themoviedb.org/movie/{}"
CATEGORY_LABELS = {
    "flatrate": "Abo",
    "free": "Gratis",
    "ads": "Mit Werbung",
    "rent": "Leihen",
    "buy": "Kaufen",
}


class ServiceError(Exception):
    """User-facing error with a German message."""


class TMDBUnavailableError(ServiceError):
    """TMDB cannot be used (offline or demo mode)."""


@dataclass(frozen=True)
class CheckResult:
    query: str
    found: bool
    movielens_id: int | None = None
    title: str | None = None
    year: int | None = None
    tmdb_id: int | None = None
    rating_count: int | None = None
    mean_rating: float | None = None
    popularity_rank: int | None = None
    total_movies: int | None = None
    queue_position: int | None = None
    queue_size: int | None = None
    own_rating: int | None = None
    note: str | None = None


def german_number(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def offer_dict(offer: Offer) -> dict[str, Any]:
    return {
        "provider_id": offer.provider_id,
        "name": offer.provider_name,
        "category": offer.category,
        "category_label": CATEGORY_LABELS.get(offer.category, offer.category),
        "logo_url": poster_url(offer.logo_path, "w92"),
    }


class FilmService:
    def __init__(
        self,
        settings: Settings,
        *,
        repo: Repository | None = None,
        data: ProcessedData | None = None,
        config: RecommenderConfig | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.config = config or RecommenderConfig()
        if repo is None:
            database = Database(settings.db_path)
            database.initialize()
            repo = Repository(database)
        self.repo = repo
        if not settings.offline and repo.get_setting("demo_mode"):
            # Demo data uses made-up TMDB ids: never ask the real API about them.
            self.settings = replace(settings, offline=True)
        self._data = data
        self._data_checked = data is not None
        self._data_lock = threading.Lock()
        self._transport = transport
        self._threads: dict[str, threading.Thread] = {}
        self._thread_lock = threading.Lock()
        self._compute_lock = threading.Lock()
        self._items_cache: list[RecItem] | None = None
        self._title_index: tuple[list[str], list[int]] | None = None
        self.last_error: str | None = None
        self._action_lock = threading.RLock()
        self._done_client_ids: OrderedDict[str, None] = OrderedDict()

    # --- infrastructure -------------------------------------------------------------------
    def data(self) -> ProcessedData | None:
        if self._data_checked:
            return self._data
        with self._data_lock:
            if not self._data_checked:
                meta = Path(self.settings.processed_dir) / "meta.json"
                self._data = load_processed(self.settings.processed_dir) if meta.exists() else None
                self._data_checked = True
        return self._data

    def require_data(self) -> ProcessedData:
        data = self.data()
        if data is None:
            raise ServiceError(NO_DATA_MESSAGE)
        return data

    @property
    def online(self) -> bool:
        return not self.settings.offline

    def tmdb(self) -> TMDBClient | None:
        if self.settings.offline:
            return None
        return TMDBClient(
            self.settings.tmdb_token,
            base_url=self.settings.tmdb_base_url,
            cache=self.repo,
            transport=self._transport,
        )

    def _client(self) -> TMDBClient:
        client = self.tmdb()
        if client is None:
            raise TMDBUnavailableError(OFFLINE_MESSAGE)
        return client

    def sync_movielens_films(self) -> int:
        data = self.require_data()
        movies = data.movies
        tmdb = movies["tmdbId"].astype("Float64").to_numpy(dtype=np.float64, na_value=np.nan)
        years = movies["year"].astype("Float64").to_numpy(dtype=np.float64, na_value=np.nan)
        means = movies["mean"].to_numpy(dtype=np.float64)
        films = [
            MovieLensFilm(
                movielens_id=int(mid),
                tmdb_id=None if math.isnan(tmdb[i]) else int(tmdb[i]),
                title=str(title),
                year=None if math.isnan(years[i]) else int(years[i]),
                genres=[str(g) for g in genres],
                count=int(count),
                mean=None if math.isnan(means[i]) else float(means[i]),
                popularity_rank=int(rank),
            )
            for i, (mid, title, genres, count, rank) in enumerate(
                zip(
                    movies["movieId"],
                    movies["title"],
                    movies["genres"],
                    movies["count"],
                    movies["popularity_rank"],
                    strict=True,
                )
            )
        ]
        n = self.repo.upsert_movielens_films(films)
        self.repo.relink_movielens_ids()
        self._items_cache = None
        return n

    def _run_in_background(self, name: str, target: Any) -> bool:
        with self._thread_lock:
            running = self._threads.get(name)
            if running is not None and running.is_alive():
                return False

            def runner() -> None:
                try:
                    target()
                except Exception as exc:  # pragma: no cover - logged, never raised in a thread
                    self.last_error = str(exc)
                    log.exception("Hintergrundaufgabe %s fehlgeschlagen", name)

            thread = threading.Thread(target=runner, name=f"filmzwilling-{name}", daemon=True)
            self._threads[name] = thread
            thread.start()
            return True

    def wait_for_background(self, timeout: float | None = None) -> None:
        for thread in list(self._threads.values()):
            thread.join(timeout)

    # --- rating queue ---------------------------------------------------------------------
    def film_card(self, film: Film, entry: QueueEntry | None = None) -> dict[str, Any]:
        original = film.original_title
        if not original and film.ml_title and film.title:
            original = clean_ml_title(film.ml_title)
        return {
            "film_id": film.id,
            "tmdb_id": film.tmdb_id,
            "movielens_id": film.movielens_id,
            "title": film.display_title,
            "original_title": original if original and original != film.display_title else None,
            "year": film.display_year,
            "runtime": film.runtime,
            "genres": film.display_genres,
            "poster_url": poster_url(film.poster_path) or f"/poster/{film.id}.svg",
            "tmdb_url": TMDB_MOVIE_URL.format(film.tmdb_id) if film.tmdb_id else None,
            "vote_average": film.vote_average,
            "source": entry.source if entry else None,
            "hints": list(entry.hints) if entry else [],
            "highlight_low": bool(entry.highlight_low) if entry else False,
        }

    def queue_items(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        entries = build_queue(self.repo)
        window = entries[offset : offset + limit]
        films = self.repo.get_films(e.film_id for e in window)
        if self.online:
            upcoming = [e.film_id for e in entries[offset : offset + limit * 3]]
            self._prefetch_metadata(upcoming)
        return [self.film_card(films[e.film_id], e) for e in window if e.film_id in films]

    def _prefetch_metadata(self, film_ids: list[int]) -> None:
        missing = self.repo.films_missing_metadata(film_ids)
        if missing:
            self._run_in_background("prefetch", lambda: asyncio.run(self.sync_metadata(missing)))

    def progress(self) -> Progress:
        return queue_progress(self.repo)

    def rate(self, film_id: int, score: int, *, from_queue: bool = True) -> bool:
        """Store a rating; returns True if a background recomputation was started."""
        self.repo.set_rating(film_id, validate_note(score), log_action=from_queue)
        return self.maybe_recompute_in_background()

    DUPLICATE: Any = object()

    def run_action(self, client_id: str | None, action: Callable[[], Any]) -> Any:
        """Run a queue action once per client id (the browser may resend it after a page close).

        Actions are serialised, so a rating and a following undo never overtake each other.
        Returns `FilmService.DUPLICATE` if the client id was already processed.
        """
        with self._action_lock:
            if client_id and client_id in self._done_client_ids:
                return self.DUPLICATE
            result = action()
            if client_id:
                self._done_client_ids[client_id] = None
                while len(self._done_client_ids) > 5000:
                    self._done_client_ids.popitem(last=False)
            return result

    def not_seen(self, film_id: int) -> None:
        self.repo.mark_not_seen(film_id)

    def later(self, film_id: int) -> None:
        self.repo.defer(film_id)

    def not_interested(self, film_id: int) -> None:
        self.repo.mark_not_interested(film_id)

    def undo(self) -> dict[str, Any] | None:
        undone = self.repo.undo_last()
        if undone is None:
            return None
        film = self.repo.get_film(undone["film_id"])
        entry = next((e for e in build_queue(self.repo) if e.film_id == undone["film_id"]), None)
        return {**undone, "item": self.film_card(film, entry) if film else None}

    # --- recommendations ------------------------------------------------------------------
    def recompute(self) -> dict[str, Any]:
        data = self.require_data()
        with self._compute_lock:
            started = time.perf_counter()
            total_ratings = self.repo.count_ratings()
            ratings = self.repo.ratings_for_cf()
            statuses = self.repo.statuses()
            hidden = [f for f, s in statuses.items() if s == "not_interested"]
            excluded_ml = [
                f.movielens_id for f in self.repo.get_films(hidden).values() if f.movielens_id
            ]
            result = recommend(data, ratings, self.config, exclude_movie_ids=excluded_ml)
            ml_map = self.repo.movielens_film_map()
            stored = [
                StoredRecommendation(
                    movielens_id=r.movielens_id,
                    film_id=ml_map.get(r.movielens_id),
                    score=r.score,
                    support=r.support,
                    twin_mean=r.twin_mean,
                    rank=rank,
                )
                for rank, r in enumerate(result.recommendations, start=1)
            ]
            duration = time.perf_counter() - started
            meta = {
                "computed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "rating_count": total_ratings,
                "cf_rating_count": len(ratings),
                "n_twins": len(result.twins),
                "count": len(stored),
                "duration_seconds": round(duration, 2),
            }
            self.repo.save_recommendations(stored, meta)
            self.repo.save_twins(self._twin_rows(data, ratings, result.twins, ml_map))
            self._items_cache = None
        if self.online and stored:
            self._run_in_background(
                "availability", lambda: asyncio.run(self.refresh_availability(force=False))
            )
        return {
            "count": len(stored),
            "rating_count": len(ratings),
            "n_twins": len(result.twins),
            "duration": round(duration, 2),
        }

    def _twin_rows(
        self, data: ProcessedData, ratings: dict[int, int], twins: Any, ml_map: dict[int, int]
    ) -> list[StoredTwin]:
        index = data.movie_index
        own = {index[m]: n for m, n in ratings.items() if m in index}
        if not own:
            return []
        own_mean = float(np.mean([from_ml_note(n) for n in own.values()]))
        rows: list[StoredTwin] = []
        top = list(
            zip(twins.user_indices[:20], twins.similarities[:20], twins.overlaps[:20], strict=True)
        )
        film_ids: list[int] = []
        details: list[tuple[int, float, int, list[tuple[int, float, float]]]] = []
        for user, sim, overlap in top:
            start, end = data.matrix.indptr[user], data.matrix.indptr[user + 1]
            cols = data.matrix.indices[start:end]
            vals = data.matrix.data[start:end]
            common = [
                (int(c), float(v), (from_ml_note(own[int(c)]) - own_mean) * float(v))
                for c, v in zip(cols, vals, strict=True)
                if int(c) in own
            ]
            common.sort(key=lambda x: (-x[2], x[0]))
            picks = [(c, v, float(data.user_means[user])) for c, v, _ in common[:3]]
            details.append((int(user), float(sim), int(overlap), picks))
            film_ids.extend(ml_map.get(int(data.movie_ids[c]), -1) for c, _, _ in picks)
        films = self.repo.get_films(f for f in film_ids if f > 0)
        for rank, (user, sim, overlap, picks) in enumerate(details, start=1):
            movies = []
            for col, centered, mean in picks:
                ml_id = int(data.movie_ids[col])
                film = films.get(ml_map.get(ml_id, -1))
                title = (
                    film.display_title
                    if film
                    else clean_ml_title(str(data.movies.iloc[col]["title"]))
                )
                movies.append(
                    {
                        "title": title,
                        "film_id": film.id if film else None,
                        "your_score": own[col],
                        "their_score": round(from_ml(centered + mean), 1),
                    }
                )
            rows.append(
                StoredTwin(
                    rank=rank,
                    ml_user_id=int(data.user_ids[user]),
                    similarity=sim,
                    overlap=overlap,
                    top_movies=movies,
                )
            )
        return rows

    def maybe_recompute_in_background(self) -> bool:
        if self.data() is None:
            return False
        count = self.repo.count_ratings()
        if count < self.config.min_own_ratings:
            return False
        meta = self.repo.get_setting("recs_meta")
        if (
            meta is not None
            and count - int(meta.get("rating_count", 0)) < self.config.recompute_after_new_ratings
        ):
            return False
        return self._run_in_background("recompute", self.recompute)

    def recommendation_items(self) -> list[RecItem]:
        cached = self._items_cache
        if cached is not None:
            return cached
        recs = self.repo.load_recommendations()
        films = self.repo.get_films(r.film_id for r in recs if r.film_id is not None)
        offers = self.repo.all_offers()
        items: list[RecItem] = []
        for rec in recs:
            film = films.get(rec.film_id) if rec.film_id is not None else None
            if film is None:
                continue
            film_offers = offers.get(film.id, [])
            card = self.film_card(film)
            card.update(
                {
                    "score": rec.score,
                    "score_text": german_number(rec.score),
                    "support": rec.support,
                    "support_text": f"{rec.support} Zwilling" + ("" if rec.support == 1 else "e"),
                    "twin_mean": rec.twin_mean,
                    "reason": f"{rec.support} Zwilling{'' if rec.support == 1 else 'e'}, "
                    f"im Schnitt {german_number(rec.twin_mean)}",
                    "offers": [offer_dict(o) for o in film_offers],
                    "personalized": True,
                }
            )
            items.append(
                RecItem(
                    film_id=film.id,
                    title=film.display_title,
                    score=rec.score,
                    support=rec.support,
                    year=film.display_year,
                    runtime=film.runtime,
                    genres=tuple(film.display_genres),
                    offers=tuple((o.provider_id, o.category) for o in film_offers),
                    vote_average=film.vote_average,
                    extra=card,
                )
            )
        self._items_cache = items
        return items

    def default_provider_ids(self) -> list[int]:
        settings = self.repo.get_user_settings()
        if settings.my_providers is not None:
            return list(settings.my_providers)
        return default_provider_ids(self.repo.list_providers())

    def parse_filter(self, params: dict[str, Any]) -> RecFilter:
        defaults = self.default_provider_ids()
        if "providers" not in params and not defaults:
            params = {**params, "providers": "any"}
        return parse_filter(params, defaults)

    def _excluded_film_ids(self) -> set[int]:
        statuses = self.repo.statuses()
        return self.repo.rated_film_ids() | {
            f for f, s in statuses.items() if s == "not_interested"
        }

    def recommendations(self, flt: RecFilter, *, limit: int = 120) -> dict[str, Any]:
        base: dict[str, Any] = {
            "items": [],
            "total": 0,
            "computed_at": None,
            "filter": filter_to_params(flt),
            "message": None,
        }
        count = self.repo.count_ratings()
        base["rating_count"] = count
        if self.data() is None:
            return {**base, "status": "no_data", "message": NO_DATA_MESSAGE}
        if count < self.config.min_own_ratings:
            needed = self.config.min_own_ratings
            return {
                **base,
                "status": "too_few_ratings",
                "message": f"Bewerte mindestens {needed} Filme, dann erscheinen hier Empfehlungen. "
                f"Bisher: {count}.",
            }
        meta = self.repo.get_setting("recs_meta")
        if meta is None:
            self.recompute()
            meta = self.repo.get_setting("recs_meta") or {}
        excluded = self._excluded_film_ids()
        items = [i for i in self.recommendation_items() if i.film_id not in excluded]
        chosen = apply_filters(items, flt)
        return {
            **base,
            "status": "ok",
            "items": [i.extra for i in chosen[:limit]],
            "total": len(chosen),
            "computed_at": meta.get("computed_at"),
        }

    def new_release_items(self, flt: RecFilter, *, limit: int = 60) -> list[dict[str, Any]]:
        ids = self.repo.list_new_releases()
        if not ids:
            return []
        excluded = self._excluded_film_ids()
        films = self.repo.get_films(ids)
        offers = self.repo.film_offers(ids)
        items = []
        for film_id in ids:
            film = films.get(film_id)
            if film is None or film_id in excluded:
                continue
            film_offers = offers.get(film_id, [])
            card = self.film_card(film)
            card.update({"offers": [offer_dict(o) for o in film_offers], "personalized": False})
            items.append(
                RecItem(
                    film_id=film_id,
                    title=film.display_title,
                    score=None,
                    support=0,
                    year=film.display_year,
                    runtime=film.runtime,
                    genres=tuple(film.display_genres),
                    offers=tuple((o.provider_id, o.category) for o in film_offers),
                    vote_average=film.vote_average,
                    extra=card,
                )
            )
        tmdb_sorted = RecFilter(**{**flt.__dict__, "sort": "tmdb"})
        chosen = apply_filters(items, tmdb_sorted, personalized=False)
        return [i.extra for i in chosen[:limit]]

    def twins(self) -> list[dict[str, Any]]:
        return [
            {
                "rank": t.rank,
                "label": f"Zwilling {t.rank}",
                "user_label": f"MovieLens-Nutzer {t.ml_user_id}",
                "similarity": round(t.similarity, 3),
                "similarity_text": german_number(t.similarity, 2),
                "overlap": t.overlap,
                "top_movies": t.top_movies,
            }
            for t in self.repo.load_twins()
        ]

    def evaluate(self) -> EvalResult:
        data = self.require_data()
        ratings = self.repo.ratings_for_cf()
        if len(ratings) < 10:
            raise ServiceError(
                f"Für den Selbsttest braucht es mindestens 10 Bewertungen von MovieLens-Filmen "
                f"(bisher {len(ratings)})."
            )
        try:
            result = cross_validate(data, ratings, self.config, folds=5)
        except ValueError as exc:
            raise ServiceError(str(exc)) from exc
        stored = result.to_dict()
        stored["evaluated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        self.repo.set_setting("evaluation", stored)
        return result

    def top_recommendations(self, n: int = 20) -> list[dict[str, Any]]:
        self.recompute()
        result = self.recommendations(RecFilter(), limit=n)
        return list(result["items"])

    # --- check ----------------------------------------------------------------------------
    def _titles(self, data: ProcessedData) -> tuple[list[str], list[int]]:
        """Normalised title variants (main title and alternative titles in parentheses)."""
        if self._title_index is None:
            choices: list[str] = []
            owners: list[int] = []
            for col, full in enumerate(data.movies["title"].astype(str)):
                name, _ = parse_ml_title(full)
                variants = {clean_ml_title(full)}
                for inner in re.findall(r"\(([^()]*)\)", name):
                    inner = re.sub(r"^(a\.k\.a\.|aka)\s+", "", inner.strip(), flags=re.IGNORECASE)
                    if inner and not inner.isdigit():
                        variants.add(move_article(inner))
                for variant in variants:
                    norm = matching.normalize_title(variant)
                    if norm:
                        choices.append(norm)
                        owners.append(col)
            self._title_index = (choices, owners)
        return self._title_index

    def _local_lookup(self, data: ProcessedData, title: str, year: int | None) -> int | None:
        choices, owners = self._titles(data)
        query = matching.normalize_title(title)
        if not query:
            return None
        years = data.movies["year"]
        best: tuple[float, int] | None = None
        for _, score, idx in process.extract(
            query, choices, scorer=fuzz.ratio, score_cutoff=85, limit=25
        ):
            col = owners[idx]
            movie_year = years.iloc[col]
            bonus = 0.0
            if year is not None and str(movie_year) != "<NA>":
                diff = abs(int(movie_year) - year)
                bonus = 5.0 if diff == 0 else 2.0 if diff == 1 else -30.0
            total = float(score) + bonus + float(np.log10(1 + data.movie_counts[col]))
            if best is None or total > best[0]:
                best = (total, col)
        if best is None or best[0] < 85:
            return None
        return best[1]

    def check_title(self, title: str, year: int | None = None) -> CheckResult:
        data = self.require_data()
        year = year or matching.year_from_title(title)
        title = matching.clean_query(title)
        col: int | None = None
        note = None
        client = self.tmdb()
        if client is not None:
            try:
                col = asyncio.run(self._tmdb_lookup(client, data, title, year))
            except Exception as exc:  # network problems only reduce the lookup to local search
                note = f"TMDB-Suche nicht möglich: {exc}"
        if col is None:
            col = self._local_lookup(data, title, year)
        if col is None:
            return CheckResult(
                query=title, found=False, note=note or "Nicht in MovieLens gefunden."
            )
        row = data.movies.iloc[col]
        ml_id = int(row["movieId"])
        tmdb_id = None if str(row["tmdbId"]) == "<NA>" else int(row["tmdbId"])
        film_id = self.repo.film_id_for_movielens(ml_id)
        position = None
        own = None
        if film_id is not None:
            own = self.repo.get_rating(film_id)
            queue = build_queue(self.repo)
            position = next((i + 1 for i, e in enumerate(queue) if e.film_id == film_id), None)
        if note is None:
            if tmdb_id is None:
                note = "Keine tmdbId in links.csv: der Film kann nicht in die Warteschlange."
            elif own is not None:
                note = "Schon bewertet."
            elif position is None:
                status = self.repo.statuses().get(film_id or -1)
                note = (
                    "Als „nicht gesehen“ markiert."
                    if status == "not_seen"
                    else "Nicht in der Warteschlange (Größe der Warteschlange erhöhen)."
                )
        mean = row["mean"]
        return CheckResult(
            query=title,
            found=True,
            movielens_id=ml_id,
            title=clean_ml_title(str(row["title"])),
            year=None if str(row["year"]) == "<NA>" else int(row["year"]),
            tmdb_id=tmdb_id,
            rating_count=int(row["count"]),
            mean_rating=None if mean != mean else round(float(mean), 2),
            popularity_rank=int(row["popularity_rank"]),
            total_movies=data.n_movies,
            queue_position=position,
            queue_size=len(build_queue(self.repo)) if film_id is not None else None,
            own_rating=own,
            note=note,
        )

    async def _tmdb_lookup(
        self, client: TMDBClient, data: ProcessedData, title: str, year: int | None
    ) -> int | None:
        async with client:
            outcome = await matching.match_title(
                client, title, year=year, threshold=self.settings.match_threshold
            )
        if outcome.tmdb_id is None:
            return None
        matches = np.flatnonzero(
            data.movies["tmdbId"].to_numpy(dtype="float64", na_value=np.nan) == outcome.tmdb_id
        )
        return int(matches[0]) if matches.size else None

    # --- imports --------------------------------------------------------------------------
    def store_import(
        self, result: ParseResult, thumbs: Iterable[dict[str, Any]] = ()
    ) -> ImportReport:
        report = store_events(self.repo, result.events)
        report.parse = result
        for thumb in thumbs:
            if self.repo.merge_event_hints(
                "netflix", thumb["profile"], thumb["title"], {"netflix_thumbs": thumb["thumbs"]}
            ):
                report.inserted += 1
        self.repo.relink_movielens_ids()
        return report

    def import_file(self, kind: str, path: Any, **options: Any) -> ImportReport:
        """kind in netflix|prime|csv; parses, stores and (if TMDB available) matches titles."""
        path = Path(path)
        thumbs: list[dict[str, Any]] = []
        if kind == "netflix":
            result, thumbs = parse_netflix(path, profile=options.get("profile"))
        elif kind == "prime":
            mapping = None
            if options.get("mapping"):
                _, headers, _ = read_records(path)
                mapping = load_mapping(Path(options["mapping"]), detect_mapping(headers))
            result = parse_prime(path, mapping)
        elif kind == "csv":
            result = parse_generic_csv(path)
        else:
            raise ValueError(f"Unbekannter Import-Typ: {kind}")
        report = self.store_import(result, thumbs)
        if self.online:
            stats = asyncio.run(self.match_pending())
            report.matched, report.unmatched, report.series = (
                stats.matched,
                stats.unmatched,
                stats.series,
            )
            tmdb_ids = [e.tmdb_id for e in self.repo.events_with_films() if e.tmdb_id is not None]
            film_ids = self.repo.film_ids_for_tmdb(tmdb_ids)
            asyncio.run(self.sync_metadata(film_ids.values()))
        else:
            report.notes.append(
                "TMDB nicht verfügbar: Die Titel werden mit 'filmzwilling tmdb-sync' zugeordnet."
            )
        return report

    # --- TMDB -----------------------------------------------------------------------------
    async def match_pending(self) -> matching.MatchStats:
        async with self._client() as client:
            stats = await matching.match_pending(
                self.repo, client, threshold=self.settings.match_threshold
            )
        self.repo.relink_movielens_ids()
        return stats

    def _store_details(self, details: MovieDetails) -> int:
        film_id = self.repo.upsert_tmdb_details(details)
        if details.offers is not None:
            self.repo.set_film_offers(film_id, details.offers)
        return film_id

    async def sync_metadata(self, film_ids: Iterable[int], *, force: bool = False) -> int:
        ids = list(film_ids)
        todo = ids if force else self.repo.films_missing_metadata(ids)
        if not todo:
            return 0
        films = self.repo.get_films(todo)
        tmdb_ids = [f.tmdb_id for f in films.values() if f.tmdb_id is not None]
        async with self._client() as client:
            details = await client.movies(tmdb_ids, force=force)
        for item in details.values():
            self._store_details(item)
        self._items_cache = None
        return len(details)

    async def sync_queue_metadata(self, limit: int | None = None) -> int:
        entries = build_queue(self.repo)
        if limit is not None:
            entries = entries[:limit]
        return await self.sync_metadata([e.film_id for e in entries])

    async def refresh_providers(self) -> list[Provider]:
        async with self._client() as client:
            providers = await client.provider_list()
        if providers:
            self.repo.upsert_providers(providers)
        return providers

    async def refresh_availability(self, limit: int | None = None, *, force: bool = True) -> int:
        limit = limit or self.config.provider_candidates
        recs = self.repo.load_recommendations()
        excluded = self._excluded_film_ids()
        candidate_ids = [
            r.film_id for r in recs if r.film_id is not None and r.film_id not in excluded
        ]
        films = self.repo.get_films(candidate_ids)
        chosen = [fid for fid in candidate_ids if films[fid].tmdb_id is not None][:limit]
        if not force:
            chosen = self.repo.films_missing_offers(chosen)
        if not chosen:
            return 0
        async with self._client() as client:
            offers = await asyncio.gather(
                *(client.movie_offers(films[fid].tmdb_id or 0, force=force) for fid in chosen)
            )
        for film_id, film_offers in zip(chosen, offers, strict=True):
            self.repo.set_film_offers(film_id, film_offers)
        self._items_cache = None
        return len(chosen)

    async def refresh_new_releases(self) -> int:
        providers = self.default_provider_ids()
        async with self._client() as client:
            results = await client.discover_new(providers)
            details = await client.movies([r.tmdb_id for r in results])
        film_ids = []
        for result in results:
            item = details.get(result.tmdb_id)
            if item is not None:
                film_ids.append(self._store_details(item))
        self.repo.save_new_releases(film_ids)
        return len(film_ids)

    async def search_tmdb(self, query: str, year: int | None = None) -> list[dict[str, Any]]:
        async with self._client() as client:
            results = await client.search_movie(query, year)
        return [
            {
                "tmdb_id": r.tmdb_id,
                "title": r.title,
                "original_title": r.original_title,
                "year": r.year,
                "poster_url": poster_url(r.poster_path, "w92"),
                "vote_average": r.vote_average,
            }
            for r in results
            if r.media_type == "movie"
        ]

    async def resolve_unmatched(self, unmatched_id: int, tmdb_id: int) -> int:
        if self.repo.get_unmatched(unmatched_id) is None:
            raise KeyError(unmatched_id)
        film_id: int | None = None
        if self.online:
            async with self._client() as client:
                details = await client.movie(tmdb_id)
            if details is not None:
                film_id = self._store_details(details)
        if film_id is None:
            film_id = self.repo.ensure_film(tmdb_id)
        self.repo.resolve_unmatched(unmatched_id, tmdb_id)
        return film_id


def from_ml_note(note: int) -> float:
    """MovieLens value of a note (helper for centering in the twin overview)."""
    return 0.5 + 0.45 * note
