"""MovieLens 32M: download, checksum, one-time preprocessing and loading.

Processing is designed for an 8 GB laptop: CSVs are read with pyarrow (only the needed columns,
32-bit dtypes), the rating matrix is built directly in CSR form and the intermediate CSV files
are removed afterwards.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import ssl
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
from numpy.typing import NDArray
from scipy import sparse

ML_URL = "https://files.grouplens.org/datasets/movielens/ml-32m.zip"
ML_MD5_URL = "https://files.grouplens.org/datasets/movielens/ml-32m.zip.md5"
KNOWN_MD5 = "d472be332d4daa821edc399621853b57"
ZIP_NAME = "ml-32m.zip"
CSV_NAMES = ("ratings.csv", "movies.csv", "links.csv")
PROCESSED_FILES = ("ratings.parquet", "matrix.npz", "index.npz", "movies.parquet", "meta.json")
FORMAT_VERSION = 1

ProgressCallback = Callable[[str, float], None]

_YEAR_RE = re.compile(r"\((\d{4})(?:\s*[-–]\s*\d{0,4})?\)\s*$")
_TRAILING_PAREN_RE = re.compile(r"\s*\([^()]*\)\s*$")
_ARTICLES = (
    "The",
    "A",
    "An",
    "Der",
    "Die",
    "Das",
    "Ein",
    "Eine",
    "Le",
    "La",
    "Les",
    "L'",
    "Il",
    "El",
    "Los",
    "Las",
    "Lo",
    "Gli",
    "I",
    "Det",
    "Den",
    "De",
    "Het",
    "O",
    "Os",
)
_MANUAL_DOWNLOAD_HINT = (
    "Lade die Datei im Browser von {url} herunter, lege sie als data/raw/ml-32m.zip ab "
    "(oder gib sie mit 'filmzwilling setup --zip PFAD' an) und starte 'filmzwilling setup' erneut."
)


class ChecksumError(Exception):
    """The downloaded file does not match the expected MD5 checksum."""


class DownloadError(Exception):
    """The dataset could not be downloaded (network or certificate problem)."""


@dataclass
class ProcessedData:
    """Preprocessed MovieLens data held in memory."""

    matrix: sparse.csr_matrix
    user_ids: NDArray[np.int32]
    movie_ids: NDArray[np.int32]
    user_means: NDArray[np.float32]
    movie_counts: NDArray[np.int32]
    movie_means: NDArray[np.float32]
    global_mean: float
    movies: pd.DataFrame
    _movie_index: dict[int, int] | None = field(default=None, repr=False)

    @property
    def movie_index(self) -> dict[int, int]:
        """Map movieId -> column index."""
        if self._movie_index is None:
            self._movie_index = {int(m): i for i, m in enumerate(self.movie_ids)}
        return self._movie_index

    @property
    def n_users(self) -> int:
        return int(self.matrix.shape[0])

    @property
    def n_movies(self) -> int:
        return int(self.matrix.shape[1])


# --- checksums and download ----------------------------------------------------------------


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_md5(path: Path, expected: str) -> None:
    """Raise ChecksumError if the file's MD5 differs from `expected`."""
    actual = md5_file(path)
    if actual.lower() != expected.strip().lower():
        raise ChecksumError(
            f"Prüfsumme von {Path(path).name} stimmt nicht: erwartet {expected.lower()}, "
            f"erhalten {actual}. Die Datei ist beschädigt oder unvollständig."
        )


def parse_md5_text(text: str) -> str:
    """Extract the hex digest from a `.md5` file ("<hash>  <name>")."""
    match = re.search(r"\b([0-9a-fA-F]{32})\b", text)
    if not match:
        raise ValueError("Keine MD5-Prüfsumme gefunden")
    return match.group(1).lower()


def _verify_options(ca_bundle: Path | None) -> list[Any]:
    """TLS trust settings to try in order: custom bundle, certifi, the OS trust store."""
    options: list[Any] = []
    if ca_bundle is not None:
        options.append(str(ca_bundle))
    options.append(True)
    options.append(ssl.create_default_context())
    return options


def _is_tls_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "certificate" in text or "ssl" in text or "tls" in text


def _fetch_text(url: str, ca_bundle: Path | None) -> str:
    last: Exception | None = None
    for verify in _verify_options(ca_bundle):
        try:
            with httpx.Client(verify=verify, timeout=30, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.text
        except httpx.HTTPError as exc:
            last = exc
            if not _is_tls_error(exc):
                break
    raise DownloadError(str(last))


def _download_file(
    url: str, target: Path, ca_bundle: Path | None, progress: ProgressCallback | None
) -> None:
    part = target.with_suffix(target.suffix + ".part")
    last: Exception | None = None
    for verify in _verify_options(ca_bundle):
        try:
            with (
                httpx.Client(verify=verify, timeout=60, follow_redirects=True) as client,
                client.stream("GET", url) as response,
            ):
                response.raise_for_status()
                total = int(response.headers.get("content-length") or 0)
                done = 0
                with part.open("wb") as fh:
                    for chunk in response.iter_bytes(1024 * 1024):
                        fh.write(chunk)
                        done += len(chunk)
                        if progress and total:
                            progress("download", done / total)
            part.replace(target)
            return
        except httpx.HTTPError as exc:
            last = exc
            part.unlink(missing_ok=True)
            if not _is_tls_error(exc):
                break
    reason = "Zertifikatsprüfung fehlgeschlagen" if last and _is_tls_error(last) else str(last)
    raise DownloadError(
        f"Download von {url} fehlgeschlagen ({reason}). " + _MANUAL_DOWNLOAD_HINT.format(url=url)
    )


def download_movielens(
    raw_dir: Path,
    *,
    url: str = ML_URL,
    md5_url: str = ML_MD5_URL,
    ca_bundle: Path | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[Path, str]:
    """Download the zip (if needed) and verify it. Returns (zip path, md5)."""
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / ZIP_NAME
    try:
        expected = parse_md5_text(_fetch_text(md5_url, ca_bundle))
    except (DownloadError, ValueError):
        if url != ML_URL:
            raise
        expected = KNOWN_MD5
    if target.exists():
        if md5_file(target) == expected:
            if progress:
                progress("download", 1.0)
            return target, expected
        target.unlink()
    _download_file(url, target, ca_bundle, progress)
    try:
        verify_md5(target, expected)
    except ChecksumError:
        target.unlink(missing_ok=True)
        raise
    return target, expected


def extract_zip(zip_path: Path, target_dir: Path) -> Path:
    """Extract ratings.csv, movies.csv and links.csv; return the directory containing them."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        members = {Path(name).name: name for name in zf.namelist() if Path(name).name in CSV_NAMES}
        missing = [name for name in CSV_NAMES if name not in members]
        if missing:
            raise ValueError(f"Im ZIP fehlen: {', '.join(missing)}")
        for name, member in members.items():
            # Write by base name only (no paths from the archive: protects against zip-slip).
            with zf.open(member) as src, (target_dir / name).open("wb") as dst:
                shutil.copyfileobj(src, dst, 4 * 1024 * 1024)
    return target_dir


# --- reading CSV files ----------------------------------------------------------------------


def read_ratings_csv(path: Path) -> pd.DataFrame:
    """Read ratings.csv with pyarrow: userId int32, movieId int32, rating float32."""
    table = pacsv.read_csv(
        path,
        convert_options=pacsv.ConvertOptions(
            include_columns=["userId", "movieId", "rating"],
            column_types={"userId": pa.int32(), "movieId": pa.int32(), "rating": pa.float32()},
        ),
    )
    return table.to_pandas()


def read_movies_csv(path: Path) -> pd.DataFrame:
    table = pacsv.read_csv(
        path,
        convert_options=pacsv.ConvertOptions(
            include_columns=["movieId", "title", "genres"],
            column_types={"movieId": pa.int32(), "title": pa.string(), "genres": pa.string()},
        ),
    )
    df = table.to_pandas()
    df["title"] = df["title"].fillna("").astype(str)
    df["genres"] = df["genres"].fillna("").astype(str)
    return df


def read_links_csv(path: Path) -> pd.DataFrame:
    """Read links.csv; tmdbId is a nullable Int32 column."""
    table = pacsv.read_csv(
        path,
        convert_options=pacsv.ConvertOptions(
            include_columns=["movieId", "imdbId", "tmdbId"],
            column_types={"movieId": pa.int32(), "imdbId": pa.int32(), "tmdbId": pa.int32()},
        ),
    )
    df = table.to_pandas(types_mapper={pa.int32(): pd.Int32Dtype()}.get)
    df["movieId"] = df["movieId"].astype(np.int32)
    return df


# --- titles ---------------------------------------------------------------------------------


def parse_ml_title(title: str) -> tuple[str, int | None]:
    """Split "Name (Year)" into ("Name", Year)."""
    text = title.strip()
    match = _YEAR_RE.search(text)
    if not match:
        return text, None
    return text[: match.start()].strip(), int(match.group(1))


def _move_article(name: str) -> str:
    for article in _ARTICLES:
        suffix = f", {article}"
        if name.endswith(suffix):
            base = name[: -len(suffix)]
            return f"{article}{base}" if article.endswith("'") else f"{article} {base}"
    return name


def clean_ml_title(title: str) -> str:
    """Human readable title: drop year and alternative titles, move trailing article to front."""
    name, _ = parse_ml_title(title)
    previous = None
    while previous != name:
        previous = name
        stripped = _TRAILING_PAREN_RE.sub("", name).strip()
        if stripped:
            name = stripped
    return _move_article(name.strip())


# --- processing -----------------------------------------------------------------------------


def _dedupe_tmdb(links: pd.Series, counts: NDArray[np.int64]) -> pd.Series:
    """Keep each tmdbId only for the most rated movie (ties: lowest movieId)."""
    tmdb = links.copy()
    frame = pd.DataFrame({"tmdb": tmdb.to_numpy(), "count": counts, "pos": np.arange(len(tmdb))})
    frame = frame[frame["tmdb"].notna()]
    dup = frame["tmdb"].duplicated(keep=False)
    if dup.any():
        sub = frame[dup].sort_values(["tmdb", "count", "pos"], ascending=[True, False, True])
        losers = sub[sub["tmdb"].duplicated(keep="first")]["pos"].to_numpy()
        tmdb.iloc[losers] = pd.NA
    return tmdb


def build_processed(
    ratings: pd.DataFrame, movies: pd.DataFrame, links: pd.DataFrame
) -> ProcessedData:
    """Build ProcessedData in memory (used by processing, tests and the demo)."""
    movie_ids = np.sort(movies["movieId"].to_numpy(dtype=np.int32))
    movie_ids = np.unique(movie_ids)
    r_movie = ratings["movieId"].to_numpy(dtype=np.int32)
    r_user = ratings["userId"].to_numpy(dtype=np.int32)
    r_value = ratings["rating"].to_numpy(dtype=np.float32)

    col = np.searchsorted(movie_ids, r_movie)
    col_clipped = np.minimum(col, len(movie_ids) - 1)
    known = movie_ids[col_clipped] == r_movie
    if not known.all():
        r_movie, r_user, r_value, col = r_movie[known], r_user[known], r_value[known], col[known]
    col = col.astype(np.int32)

    user_ids, row = np.unique(r_user, return_inverse=True)
    user_ids = user_ids.astype(np.int32)
    row = row.astype(np.int32)
    n_users, n_movies = len(user_ids), len(movie_ids)

    user_counts = np.bincount(row, minlength=n_users)
    user_sums = np.bincount(row, weights=r_value, minlength=n_users)
    user_means = (user_sums / np.maximum(user_counts, 1)).astype(np.float32)
    centered = (r_value - user_means[row]).astype(np.float32)

    if len(row) and np.all(row[1:] >= row[:-1]):
        indptr = np.zeros(n_users + 1, dtype=np.int64)
        np.cumsum(user_counts, out=indptr[1:])
        matrix = sparse.csr_matrix((centered, col, indptr), shape=(n_users, n_movies))
        if not matrix.has_sorted_indices:
            matrix.sort_indices()
    else:
        matrix = sparse.csr_matrix((centered, (row, col)), shape=(n_users, n_movies))
        matrix.sort_indices()

    counts = np.bincount(col, minlength=n_movies).astype(np.int64)
    sums = np.bincount(col, weights=r_value, minlength=n_movies)
    with np.errstate(invalid="ignore", divide="ignore"):
        means = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
    global_mean = float(r_value.astype(np.float64).mean()) if len(r_value) else 0.0

    order = np.lexsort((movie_ids, -counts))
    ranks = np.empty(n_movies, dtype=np.int32)
    ranks[order] = np.arange(1, n_movies + 1, dtype=np.int32)

    meta = movies.drop_duplicates("movieId").set_index("movieId").reindex(movie_ids)
    link_frame = links.drop_duplicates("movieId").set_index("movieId").reindex(movie_ids)
    tmdb = (
        link_frame["tmdbId"].astype("Int32")
        if "tmdbId" in link_frame
        else pd.Series(pd.array([pd.NA] * n_movies, dtype="Int32"))
    )
    tmdb = _dedupe_tmdb(tmdb.reset_index(drop=True), counts)
    imdb = (
        link_frame["imdbId"].astype("Int32").reset_index(drop=True)
        if "imdbId" in link_frame
        else pd.Series(pd.array([pd.NA] * n_movies, dtype="Int32"))
    )
    titles = meta["title"].fillna("").astype(str).to_numpy()
    parsed = [parse_ml_title(t) for t in titles]
    genre_lists = [
        [g for g in str(g_str).split("|") if g and g != "(no genres listed)"]
        for g_str in meta["genres"].fillna("").to_numpy()
    ]
    movies_df = pd.DataFrame(
        {
            "movieId": movie_ids,
            "title": titles,
            "name": [p[0] for p in parsed],
            "year": pd.array([p[1] for p in parsed], dtype="Int32"),
            "genres": genre_lists,
            "imdbId": imdb.to_numpy(),
            "tmdbId": pd.array(tmdb.to_numpy(), dtype="Int32"),
            "count": counts.astype(np.int32),
            "mean": means.astype(np.float32),
            "popularity_rank": ranks,
        }
    )
    return ProcessedData(
        matrix=matrix,
        user_ids=user_ids,
        movie_ids=movie_ids,
        user_means=user_means,
        movie_counts=counts.astype(np.int32),
        movie_means=np.nan_to_num(means, nan=global_mean).astype(np.float32),
        global_mean=global_mean,
        movies=movies_df,
    )


def is_processed(processed_dir: Path, checksum: str) -> bool:
    processed_dir = Path(processed_dir)
    if not all((processed_dir / name).exists() for name in PROCESSED_FILES):
        return False
    try:
        meta = json.loads((processed_dir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(meta.get("checksum") == checksum and meta.get("format") == FORMAT_VERSION)


def _write_processed(data: ProcessedData, ratings: pd.DataFrame, out: Path, checksum: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "meta.json").unlink(missing_ok=True)  # invalidate first; written last
    table = pa.table(
        {
            "userId": pa.array(ratings["userId"].to_numpy(dtype=np.int32), type=pa.int32()),
            "movieId": pa.array(ratings["movieId"].to_numpy(dtype=np.int32), type=pa.int32()),
            "rating": pa.array(ratings["rating"].to_numpy(dtype=np.float32), type=pa.float32()),
        }
    )
    pq.write_table(table, out / "ratings.parquet")
    del table
    sparse.save_npz(out / "matrix.npz", data.matrix, compressed=False)
    np.savez(
        out / "index.npz",
        user_ids=data.user_ids,
        movie_ids=data.movie_ids,
        user_means=data.user_means,
    )
    data.movies.to_parquet(out / "movies.parquet", index=False)
    meta = {
        "format": FORMAT_VERSION,
        "checksum": checksum,
        "n_ratings": int(data.matrix.nnz),
        "n_users": data.n_users,
        "n_movies": data.n_movies,
        "global_mean": data.global_mean,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def process_movielens(
    source_dir: Path,
    processed_dir: Path,
    checksum: str,
    *,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> bool:
    """Preprocess CSVs into data/processed. Returns False if skipped (already up to date)."""
    source_dir, processed_dir = Path(source_dir), Path(processed_dir)
    if not force and is_processed(processed_dir, checksum):
        return False

    def step(name: str, fraction: float) -> None:
        if progress:
            progress(name, fraction)

    step("ratings.csv lesen", 0.0)
    ratings = read_ratings_csv(source_dir / "ratings.csv")
    step("movies.csv und links.csv lesen", 0.35)
    movies = read_movies_csv(source_dir / "movies.csv")
    links = read_links_csv(source_dir / "links.csv")
    step("Matrix aufbauen", 0.45)
    data = build_processed(ratings, movies, links)
    step("Dateien schreiben", 0.8)
    _write_processed(data, ratings, processed_dir, checksum)
    step("fertig", 1.0)
    return True


def load_processed(processed_dir: Path) -> ProcessedData:
    processed_dir = Path(processed_dir)
    meta = json.loads((processed_dir / "meta.json").read_text(encoding="utf-8"))
    matrix = sparse.load_npz(processed_dir / "matrix.npz").tocsr()
    with np.load(processed_dir / "index.npz") as index:
        user_ids = index["user_ids"].astype(np.int32)
        movie_ids = index["movie_ids"].astype(np.int32)
        user_means = index["user_means"].astype(np.float32)
    movies = pd.read_parquet(processed_dir / "movies.parquet")
    movies["genres"] = movies["genres"].map(lambda g: [str(x) for x in g] if g is not None else [])
    counts = movies["count"].to_numpy(dtype=np.int32)
    global_mean = float(meta["global_mean"])
    means = movies["mean"].to_numpy(dtype=np.float64)
    return ProcessedData(
        matrix=matrix,
        user_ids=user_ids,
        movie_ids=movie_ids,
        user_means=user_means,
        movie_counts=counts,
        movie_means=np.nan_to_num(means, nan=global_mean).astype(np.float32),
        global_mean=global_mean,
        movies=movies,
    )


def setup_movielens(
    raw_dir: Path,
    processed_dir: Path,
    *,
    zip_path: Path | None = None,
    expected_md5: str | None = None,
    ca_bundle: Path | None = None,
    progress: ProgressCallback | None = None,
) -> bool:
    """Full setup: download/verify/extract/process. Returns True if processing ran.

    With `zip_path` no download happens; the file is checked against `expected_md5` (default:
    the published checksum of ml-32m.zip).
    """
    raw_dir, processed_dir = Path(raw_dir), Path(processed_dir)
    if zip_path is not None:
        if not Path(zip_path).exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {zip_path}")
        checksum = md5_file(zip_path)
        expected = (expected_md5 or KNOWN_MD5).lower()
        if checksum != expected:
            raise ChecksumError(
                f"Prüfsumme von {Path(zip_path).name} stimmt nicht: erwartet {expected}, "
                f"erhalten {checksum}."
            )
    else:
        zip_path, checksum = download_movielens(raw_dir, ca_bundle=ca_bundle, progress=progress)
    if is_processed(processed_dir, checksum):
        return False
    extract_dir = raw_dir / "extracted"
    try:
        if progress:
            progress("entpacken", 0.0)
        source = extract_zip(Path(zip_path), extract_dir)
        process_movielens(source, processed_dir, checksum, force=True, progress=progress)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)
    return True
