from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
import respx

from filmzwilling import movielens as ml
from filmzwilling.movielens import (
    ChecksumError,
    DownloadError,
    build_processed,
    clean_ml_title,
    download_movielens,
    extract_zip,
    is_processed,
    load_processed,
    md5_file,
    parse_md5_text,
    parse_ml_title,
    process_movielens,
    read_links_csv,
    read_movies_csv,
    read_ratings_csv,
    setup_movielens,
    verify_md5,
)
from filmzwilling.synthetic import generate_dataset, write_zip

PROCESSED_FILES = ("ratings.parquet", "matrix.npz", "index.npz", "movies.parquet", "meta.json")


@pytest.fixture
def processed_mini(tmp_path: Path, ml_mini_dir: Path) -> Path:
    out = tmp_path / "processed"
    assert process_movielens(ml_mini_dir, out, checksum="mini") is True
    return out


def test_read_ratings_dtypes(ml_mini_dir: Path) -> None:
    df = read_ratings_csv(ml_mini_dir / "ratings.csv")
    assert list(df.columns) == ["userId", "movieId", "rating"]
    assert df["userId"].dtype == np.int32
    assert df["movieId"].dtype == np.int32
    assert df["rating"].dtype == np.float32
    assert len(df) == 596


def test_read_links_missing_tmdb(ml_mini_dir: Path) -> None:
    links = read_links_csv(ml_mini_dir / "links.csv")
    assert str(links["tmdbId"].dtype) == "Int32"
    missing = set(links.loc[links["tmdbId"].isna(), "movieId"])
    assert {3, 39} <= missing
    assert int(links.loc[links.movieId == 1, "tmdbId"].iloc[0]) == 238


def test_read_movies(ml_mini_dir: Path) -> None:
    movies = read_movies_csv(ml_mini_dir / "movies.csv")
    assert movies["movieId"].dtype == np.int32
    row = movies.loc[movies.movieId == 3].iloc[0]
    assert '"Quoted"' in row["title"]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Godfather, The (1972)", ("Godfather, The", 1972)),
        ("Untitled Project", ("Untitled Project", None)),
        ("Babylon 5 (1994-1998)", ("Babylon 5", 1994)),
        ("Toy Story (1995) ", ("Toy Story", 1995)),
        ("Dr. Strangelove (1964)", ("Dr. Strangelove", 1964)),
    ],
)
def test_parse_ml_title(title: str, expected: tuple[str, int | None]) -> None:
    assert parse_ml_title(title) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Godfather, The (1972)", "The Godfather"),
        ("Lives of Others, The (Leben der Anderen, Das) (2006)", "The Lives of Others"),
        ("Untitled Project", "Untitled Project"),
        ("Amelie (Fabuleux destin d'Amélie Poulain, Le) (2001)", "Amelie"),
        ("Matrix, The (1999)", "The Matrix"),
        (
            "City of Lost Children, The (Cité des enfants perdus, La) (1995)",
            "The City of Lost Children",
        ),
    ],
)
def test_clean_ml_title(title: str, expected: str) -> None:
    assert clean_ml_title(title) == expected


def test_processed_files(processed_mini: Path) -> None:
    for name in PROCESSED_FILES:
        assert (processed_mini / name).exists(), name
    schema = pq.read_schema(processed_mini / "ratings.parquet")
    assert schema.names == ["userId", "movieId", "rating"]
    assert str(schema.field("userId").type) == "int32"
    assert str(schema.field("movieId").type) == "int32"
    assert str(schema.field("rating").type) == "float"
    meta = json.loads((processed_mini / "meta.json").read_text())
    assert meta["checksum"] == "mini"
    assert meta["n_ratings"] == 596


def test_matrix_shape_and_centering(processed_mini: Path, ml_mini_dir: Path) -> None:
    data = load_processed(processed_mini)
    ratings = pd.read_csv(ml_mini_dir / "ratings.csv")
    assert data.matrix.format == "csr"
    assert data.matrix.shape == (30, 40)
    assert data.matrix.nnz == 596
    assert data.matrix.dtype == np.float32
    assert data.n_users == 30 and data.n_movies == 40
    means = ratings.groupby("userId")["rating"].mean()
    np.testing.assert_allclose(data.user_means, means.loc[data.user_ids].to_numpy(), rtol=1e-5)
    row_sums = np.asarray(data.matrix.sum(axis=1)).ravel()
    np.testing.assert_allclose(row_sums, 0.0, atol=1e-3)
    # A single entry: centered value = rating - user mean
    first = ratings.iloc[0]
    u = int(np.where(data.user_ids == first.userId)[0][0])
    m = data.movie_index[int(first.movieId)]
    assert data.matrix[u, m] == pytest.approx(first.rating - means.loc[first.userId], abs=1e-5)


def test_movie_stats_and_popularity(processed_mini: Path, ml_mini_dir: Path) -> None:
    data = load_processed(processed_mini)
    ratings = pd.read_csv(ml_mini_dir / "ratings.csv")
    counts = ratings.groupby("movieId").size()
    means = ratings.groupby("movieId")["rating"].mean()
    movies = data.movies.set_index("movieId")
    for movie_id, count in counts.items():
        assert movies.loc[movie_id, "count"] == count
        assert movies.loc[movie_id, "mean"] == pytest.approx(means.loc[movie_id], rel=1e-5)
        assert data.movie_counts[data.movie_index[int(movie_id)]] == count
    assert movies.loc[40, "count"] == 0
    ranks = movies["popularity_rank"].to_numpy()
    assert sorted(ranks) == list(range(1, 41))
    top = int(movies["popularity_rank"].idxmin())
    assert counts.loc[top] == counts.max()
    assert movies.loc[40, "popularity_rank"] == 40
    # Ties are broken by movieId: among equal counts the lower id ranks first.
    by_rank = movies.sort_values("popularity_rank")
    counts_in_rank_order = by_rank["count"].to_numpy()
    assert all(np.diff(counts_in_rank_order) <= 0)
    for (_, a), (_, b) in zip(
        by_rank.iloc[:-1].iterrows(), by_rank.iloc[1:].iterrows(), strict=True
    ):
        if a["count"] == b["count"]:
            assert a.name < b.name
    assert data.global_mean == pytest.approx(ratings["rating"].mean(), rel=1e-5)


def test_movies_parquet_columns(processed_mini: Path) -> None:
    data = load_processed(processed_mini)
    for col in ("movieId", "title", "year", "genres", "tmdbId", "count", "mean", "popularity_rank"):
        assert col in data.movies.columns
    row = data.movies.set_index("movieId").loc[1]
    assert row["year"] == 1972
    assert list(row["genres"]) == ["Crime", "Drama"]
    assert pd.isna(data.movies.set_index("movieId").loc[39, "tmdbId"])


def test_idempotent_processing(processed_mini: Path, ml_mini_dir: Path) -> None:
    mtimes = {n: (processed_mini / n).stat().st_mtime_ns for n in PROCESSED_FILES}
    assert is_processed(processed_mini, "mini")
    assert process_movielens(ml_mini_dir, processed_mini, checksum="mini") is False
    assert mtimes == {n: (processed_mini / n).stat().st_mtime_ns for n in PROCESSED_FILES}
    assert not is_processed(processed_mini, "other")
    assert process_movielens(ml_mini_dir, processed_mini, checksum="other") is True
    assert process_movielens(ml_mini_dir, processed_mini, checksum="other", force=True) is True


def test_missing_file_triggers_reprocessing(processed_mini: Path, ml_mini_dir: Path) -> None:
    (processed_mini / "matrix.npz").unlink()
    assert not is_processed(processed_mini, "mini")
    assert process_movielens(ml_mini_dir, processed_mini, checksum="mini") is True


def test_md5(tmp_path: Path) -> None:
    f = tmp_path / "x.bin"
    f.write_bytes(b"filmzwilling" * 1000)
    assert md5_file(f) == hashlib.md5(f.read_bytes()).hexdigest()
    verify_md5(f, md5_file(f))
    verify_md5(f, md5_file(f).upper())
    with pytest.raises(ChecksumError):
        verify_md5(f, "0" * 32)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("d472be332d4daa821edc399621853b57  ml-32m.zip\n", "d472be332d4daa821edc399621853b57"),
        ("MD5 (ml-32m.zip) = d472be332d4daa821edc399621853b57", "d472be332d4daa821edc399621853b57"),
        ("D472BE332D4DAA821EDC399621853B57", "d472be332d4daa821edc399621853b57"),
    ],
)
def test_parse_md5_text(text: str, expected: str) -> None:
    assert parse_md5_text(text) == expected


def test_parse_md5_text_invalid() -> None:
    with pytest.raises(ValueError):
        parse_md5_text("<html>not found</html>")


@pytest.fixture
def synthetic_zip(tmp_path: Path) -> tuple[bytes, str]:
    ds = generate_dataset(
        n_users=40, n_movies=30, n_clusters=2, min_ratings=10, max_ratings=20, n_favorites=3
    )
    path = write_zip(ds, tmp_path / "src" / "ml-32m.zip")
    content = path.read_bytes()
    return content, hashlib.md5(content).hexdigest()


@respx.mock
def test_download_and_verify(tmp_path: Path, synthetic_zip: tuple[bytes, str]) -> None:
    content, digest = synthetic_zip
    respx.get(ml.ML_MD5_URL).mock(return_value=httpx.Response(200, text=f"{digest}  ml-32m.zip\n"))
    zroute = respx.get(ml.ML_URL).mock(return_value=httpx.Response(200, content=content))
    raw = tmp_path / "raw"
    path, md5 = download_movielens(raw)
    assert path == raw / "ml-32m.zip"
    assert md5 == digest
    assert path.read_bytes() == content
    # Second call: file already there and valid, no new download.
    download_movielens(raw)
    assert zroute.call_count == 1


@respx.mock
def test_download_md5_mismatch(tmp_path: Path, synthetic_zip: tuple[bytes, str]) -> None:
    content, _ = synthetic_zip
    respx.get(ml.ML_MD5_URL).mock(return_value=httpx.Response(200, text="0" * 32 + "  ml-32m.zip"))
    respx.get(ml.ML_URL).mock(return_value=httpx.Response(200, content=content))
    raw = tmp_path / "raw"
    with pytest.raises(ChecksumError):
        download_movielens(raw)
    assert not (raw / "ml-32m.zip").exists()


@respx.mock
def test_download_error_message(tmp_path: Path) -> None:
    respx.get(ml.ML_MD5_URL).mock(side_effect=httpx.ConnectError("boom"))
    respx.get(ml.ML_URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(DownloadError) as exc:
        download_movielens(tmp_path / "raw")
    assert "data/raw" in str(exc.value) or "ml-32m.zip" in str(exc.value)


def test_extract_and_setup_from_zip(tmp_path: Path, synthetic_zip: tuple[bytes, str]) -> None:
    content, digest = synthetic_zip
    zip_path = tmp_path / "given.zip"
    zip_path.write_bytes(content)
    target = extract_zip(zip_path, tmp_path / "extract")
    assert (target / "ratings.csv").exists() and (target / "links.csv").exists()

    raw, processed = tmp_path / "raw", tmp_path / "processed"
    assert setup_movielens(raw, processed, zip_path=zip_path, expected_md5=digest) is True
    assert setup_movielens(raw, processed, zip_path=zip_path, expected_md5=digest) is False
    data = load_processed(processed)
    assert data.n_users == 40
    with pytest.raises(ChecksumError):
        setup_movielens(raw, tmp_path / "p2", zip_path=zip_path, expected_md5="f" * 32)


def test_build_processed_matches_files(processed_mini: Path, ml_mini_dir: Path) -> None:
    in_memory = build_processed(
        read_ratings_csv(ml_mini_dir / "ratings.csv"),
        read_movies_csv(ml_mini_dir / "movies.csv"),
        read_links_csv(ml_mini_dir / "links.csv"),
    )
    loaded = load_processed(processed_mini)
    assert (in_memory.matrix != loaded.matrix).nnz == 0
    np.testing.assert_array_equal(in_memory.movie_ids, loaded.movie_ids)
    np.testing.assert_array_equal(in_memory.user_ids, loaded.user_ids)
    assert in_memory.global_mean == pytest.approx(loaded.global_mean)


def test_duplicate_tmdb_ids_keep_most_popular(ml_mini_dir: Path, tmp_path: Path) -> None:
    ratings = read_ratings_csv(ml_mini_dir / "ratings.csv")
    movies = read_movies_csv(ml_mini_dir / "movies.csv")
    links = read_links_csv(ml_mini_dir / "links.csv")
    counts = ratings.groupby("movieId").size()
    a, b = int(counts.idxmax()), int(counts.idxmin())
    links.loc[links.movieId == a, "tmdbId"] = 777
    links.loc[links.movieId == b, "tmdbId"] = 777
    data = build_processed(ratings, movies, links)
    m = data.movies.set_index("movieId")
    assert int(m.loc[a, "tmdbId"]) == 777
    assert pd.isna(m.loc[b, "tmdbId"])


def test_explicit_zero_after_centering_is_kept(tmp_path: Path) -> None:
    # A user with constant ratings has all centered values == 0; they must stay in the matrix.
    ratings = pd.DataFrame(
        {"userId": [1, 1, 2, 2], "movieId": [1, 2, 1, 2], "rating": [3.0, 3.0, 2.0, 4.0]}
    ).astype({"userId": "int32", "movieId": "int32", "rating": "float32"})
    movies = pd.DataFrame(
        {"movieId": [1, 2], "title": ["A (2000)", "B (2001)"], "genres": ["Drama", "Comedy"]}
    )
    links = pd.DataFrame(
        {"movieId": [1, 2], "imdbId": [1, 2], "tmdbId": pd.array([10, 20], dtype="Int32")}
    )
    data = build_processed(ratings, movies.astype({"movieId": "int32"}), links)
    assert data.matrix.nnz == 4
    out = tmp_path / "p"
    src = tmp_path / "src"
    src.mkdir()
    ratings.assign(timestamp=0).to_csv(src / "ratings.csv", index=False)
    movies.to_csv(src / "movies.csv", index=False)
    links.to_csv(src / "links.csv", index=False)
    process_movielens(src, out, checksum="z")
    assert load_processed(out).matrix.nnz == 4
    shutil.rmtree(out)
