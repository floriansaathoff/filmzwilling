"""Data for the data-science page: 3D taste space, 3D film universe and summary statistics.

Both point clouds come from one truncated SVD (k = 3) of the mean-centered rating matrix,
restricted to a user sample (all top twins plus random MovieLens users) and the most rated films
(plus every film Florian rated). Users are embedded as U·S, films as V·S; Florian is projected
into the same space like a new user row (x·V). Everything is vectorised; no Python loop over
MovieLens users or films.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import sparse
from scipy.sparse.linalg import svds

from filmzwilling.config import RecommenderConfig
from filmzwilling.genres import german_genres
from filmzwilling.movielens import ProcessedData, clean_ml_title
from filmzwilling.recommender import user_arrays
from filmzwilling.scale import from_ml_array
from filmzwilling.similarity import TwinResult, compute_similarities

TitleLookup = Callable[[Sequence[int]], Mapping[int, str]]


@dataclass(frozen=True)
class InsightConfig:
    """Sizes of the samples behind the point clouds (kept small enough for a browser)."""

    sample_users: int = 6000
    top_twins: int = 400
    display_users: int = 2200
    svd_movies: int = 3000
    display_movies: int = 1800
    rating_sample: int = 400_000
    seed: int = 7


@dataclass(frozen=True)
class Embedding:
    users: NDArray[np.int64]
    user_xyz: NDArray[np.float64]
    cols: NDArray[np.int64]
    movie_xyz: NDArray[np.float64]
    you: NDArray[np.float64]
    explained: list[float]


def _r(values: NDArray[np.float64], digits: int = 3) -> list[float]:
    return [round(float(v), digits) for v in values]


def embed(
    data: ProcessedData,
    own_cols: NDArray[np.int64],
    own_ml: NDArray[np.float64],
    twins: TwinResult,
    cfg: InsightConfig,
    extra_cols: NDArray[np.int64] | None = None,
) -> Embedding:
    """Truncated SVD of the sampled, centered rating matrix (3 components)."""
    rng = np.random.default_rng(cfg.seed)
    n_users = data.matrix.shape[0]
    by_count = np.argsort(-data.movie_counts, kind="stable")[: cfg.svd_movies]
    cols = np.union1d(by_count, own_cols)
    if extra_cols is not None:
        cols = np.union1d(cols, extra_cols)
    cols = cols.astype(np.int64)
    top = twins.user_indices[: cfg.top_twins]
    sample = rng.choice(n_users, size=min(cfg.sample_users, n_users), replace=False)
    users = np.union1d(top, sample).astype(np.int64)
    sub = sparse.csr_matrix(data.matrix[users][:, cols], dtype=np.float64)
    k = 3
    if min(sub.shape) <= k or sub.nnz == 0:
        zeros_u = np.zeros((len(users), k))
        return Embedding(users, zeros_u, cols, np.zeros((len(cols), k)), np.zeros(k), [0.0] * k)
    u, s, vt = svds(sub, k=k, random_state=cfg.seed)
    order = np.argsort(-s)
    u, s, vt = u[:, order], s[order], vt[order]
    # Deterministic signs: the largest film loading of every component is positive.
    signs = np.sign(vt[np.arange(k), np.argmax(np.abs(vt), axis=1)])
    signs[signs == 0] = 1.0
    u, vt = u * signs, vt * signs[:, None]
    own_vec = np.zeros(len(cols))
    if len(own_cols):
        positions = np.searchsorted(cols, own_cols)
        own_vec[positions] = own_ml - own_ml.mean()
    total = float(np.sum(np.square(sub.data))) or 1.0
    return Embedding(
        users=users,
        user_xyz=u * s,
        cols=cols,
        movie_xyz=vt.T * s,
        you=own_vec @ vt.T,
        explained=[round(100 * float(x) ** 2 / total, 1) for x in s],
    )


def _scale(points: NDArray[np.float64], center: NDArray[np.float64]) -> float:
    """Factor that puts 95 % of the points inside the unit sphere around `center`."""
    if not len(points):
        return 1.0
    radius = float(np.percentile(np.linalg.norm(points - center, axis=1), 95))
    return 1.0 / radius if radius > 1e-12 else 1.0


def taste_space(
    emb: Embedding, data: ProcessedData, twins: TwinResult, cfg: InsightConfig
) -> dict[str, Any]:
    """Users as points: twins coloured by similarity, a random sample of everyone else."""
    rng = np.random.default_rng(cfg.seed + 1)
    sim = np.zeros(data.n_users)
    rank = np.zeros(data.n_users, dtype=np.int64)
    top = twins.user_indices[: cfg.top_twins]
    sim[top] = twins.similarities[: cfg.top_twins]
    rank[top] = np.arange(1, len(top) + 1)
    is_twin = rank[emb.users] > 0
    others = np.flatnonzero(~is_twin)
    n_others = max(0, cfg.display_users - int(is_twin.sum()))
    keep = np.concatenate(
        [
            np.flatnonzero(is_twin),
            rng.choice(others, size=min(n_others, len(others)), replace=False),
        ]
    )
    keep.sort()
    center = emb.user_xyz.mean(axis=0) if len(emb.user_xyz) else np.zeros(3)
    factor = _scale(emb.user_xyz[keep], center)
    xyz = (emb.user_xyz[keep] - center) * factor
    you = (emb.you - center) * factor
    picked = emb.users[keep]
    order = np.lexsort((picked, -sim[picked]))
    return {
        "you": _r(you),
        "x": _r(xyz[order, 0]),
        "y": _r(xyz[order, 1]),
        "z": _r(xyz[order, 2]),
        "similarity": _r(sim[picked][order]),
        "rank": [int(v) for v in rank[picked][order]],
        "ml_user": [int(v) for v in data.user_ids[picked][order]],
        "n_twins": int(is_twin.sum()),
        "n_sample": len(emb.users),
        "explained": emb.explained,
    }


def film_universe(
    emb: Embedding,
    data: ProcessedData,
    own: Mapping[int, int],
    recs: Mapping[int, float],
    ml_to_film: Mapping[int, int],
    titles: TitleLookup,
    cfg: InsightConfig,
) -> dict[str, Any]:
    """Films as points (popular ones plus rated and recommended), with your note if any."""
    index = data.movie_index
    own_cols = {index[m]: n for m, n in own.items() if m in index}
    rec_cols = {index[m]: s for m, s in recs.items() if m in index}
    position = {int(c): i for i, c in enumerate(emb.cols)}
    by_count = emb.cols[np.argsort(-data.movie_counts[emb.cols], kind="stable")]
    chosen = set(by_count[: cfg.display_movies].tolist())
    chosen |= {c for c in own_cols if c in position}
    chosen |= {c for c in rec_cols if c in position}
    cols = np.array(sorted(chosen), dtype=np.int64)
    rows = np.array([position[int(c)] for c in cols], dtype=np.int64)
    xyz = emb.movie_xyz[rows] if len(rows) else np.zeros((0, 3))
    center = xyz.mean(axis=0) if len(xyz) else np.zeros(3)
    xyz = (xyz - center) * _scale(xyz, center)
    movies = data.movies
    ml_ids = data.movie_ids[cols]
    raw_titles = movies["title"].to_numpy()[cols]
    years = movies["year"].to_numpy()[cols]
    genres = movies["genres"].to_numpy()[cols]
    film_ids = [ml_to_film.get(int(m)) for m in ml_ids.tolist()]
    names = titles([f for f in film_ids if f is not None])
    means = np.round(from_ml_array(data.movie_means[cols].astype(np.float64)), 1)
    # One dict per displayed film (capped by display_movies, not a loop over MovieLens).
    items = []
    for i, (col, film_id) in enumerate(zip(cols.tolist(), film_ids, strict=True)):
        year = years[i]
        title = names.get(film_id, "") if film_id is not None else ""
        items.append(
            {
                "film_id": film_id,
                "title": title or clean_ml_title(str(raw_titles[i])),
                "year": None if year is None or str(year) == "<NA>" else int(year),
                "genres": german_genres(list(genres[i]))[:3],
                "count": int(data.movie_counts[col]),
                "mean": float(means[i]),
                "your": own_cols.get(col),
                "rec": rec_cols.get(col),
            }
        )
    return {
        "x": _r(xyz[:, 0]),
        "y": _r(xyz[:, 1]),
        "z": _r(xyz[:, 2]),
        "films": items,
        "explained": emb.explained,
    }


def rating_histograms(
    data: ProcessedData, own_notes: Iterable[int], cfg: InsightConfig
) -> dict[str, Any]:
    """Share of each note 0–10: yours vs. a random sample of all MovieLens ratings."""
    own = np.bincount(np.asarray(list(own_notes), dtype=np.int64), minlength=11)[:11]
    nnz = data.matrix.nnz
    ml = np.zeros(11, dtype=np.float64)
    if nnz:
        rng = np.random.default_rng(cfg.seed + 2)
        idx = rng.integers(0, nnz, size=min(cfg.rating_sample, nnz))
        rows = np.searchsorted(data.matrix.indptr, idx, side="right") - 1
        raw = data.matrix.data[idx].astype(np.float64) + data.user_means[rows]
        # Half stars do not hit whole notes: split each rating between its two neighbours.
        notes = np.clip(from_ml_array(raw), 0, 10)
        low = np.floor(notes).astype(np.int64)
        frac = notes - low
        high = np.minimum(low + 1, 10)
        ml = np.bincount(low, weights=1 - frac, minlength=11)[:11]
        ml = ml + np.bincount(high, weights=frac, minlength=11)[:11]
    own_total = int(own.sum()) or 1
    ml_total = float(ml.sum()) or 1.0
    return {
        "notes": list(range(11)),
        "yours": [int(v) for v in own],
        "yours_share": [round(float(v) / own_total, 4) for v in own],
        "movielens_share": [round(float(v) / ml_total, 4) for v in ml],
    }


def genre_profile(rated: Sequence[tuple[int, list[str]]], limit: int = 12) -> list[dict[str, Any]]:
    """Your mean note per genre (genres with the most ratings first)."""
    counts: Counter[str] = Counter()
    sums: Counter[str] = Counter()
    for score, genres in rated:
        for genre in genres:
            counts[genre] += 1
            sums[genre] += score
    top = sorted(counts, key=lambda g: (-counts[g], g))[:limit]
    return [{"genre": g, "count": counts[g], "mean": round(sums[g] / counts[g], 2)} for g in top]


def timeline(rated_at: Iterable[str], max_points: int = 300) -> list[dict[str, Any]]:
    """Cumulative number of ratings over time (at most `max_points` points, last one kept)."""
    times = sorted(str(t) for t in rated_at if t)
    total = len(times)
    if not total:
        return []
    step = max(1, -(-total // max_points))
    picks = list(range(step - 1, total, step))
    if picks[-1] != total - 1:
        picks.append(total - 1)
    return [{"at": times[i], "total": i + 1} for i in picks]


def build_insights(
    data: ProcessedData,
    own: Mapping[int, int],
    config: RecommenderConfig,
    *,
    ml_to_film: Mapping[int, int],
    titles: TitleLookup,
    recs: Sequence[tuple[int, float, int]],
    cfg: InsightConfig | None = None,
) -> dict[str, Any]:
    """Point clouds and twin/recommendation scatter data.

    `own` maps movielens_id -> note, `recs` holds (movielens_id, score, support).
    """
    cfg = cfg or InsightConfig()
    cols, vals = user_arrays(data, own)
    twins = compute_similarities(data.matrix, cols, vals, config)
    index = data.movie_index
    rec_cols = np.array([index[m] for m, _, _ in recs if m in index], dtype=np.int64)
    emb = embed(data, cols, vals, twins, cfg, rec_cols)
    n = min(300, len(twins))
    top_recs = list(recs[:300])
    rec_films = [ml_to_film.get(m) for m, _, _ in top_recs]
    rec_names = titles([f for f in rec_films if f is not None])
    return {
        "taste": taste_space(emb, data, twins, cfg),
        "films": film_universe(emb, data, own, {m: s for m, s, _ in recs}, ml_to_film, titles, cfg),
        "twins": {
            "similarity": _r(twins.similarities[:n]),
            "raw": _r(twins.raw_similarities[:n]),
            "overlap": [int(v) for v in twins.overlaps[:n]],
            "total": len(twins),
        },
        "recs": {
            "score": [round(float(s), 1) for _, s, _ in top_recs],
            "support": [int(c) for _, _, c in top_recs],
            "title": [rec_names.get(f, "") if f is not None else "" for f in rec_films],
        },
        "dataset": {
            "users": data.n_users,
            "movies": data.n_movies,
            "ratings": int(data.matrix.nnz),
        },
    }
