"""MovieLens 32M: download, checksum, one-time preprocessing and loading."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy import sparse

ML_URL = "https://files.grouplens.org/datasets/movielens/ml-32m.zip"
ML_MD5_URL = "https://files.grouplens.org/datasets/movielens/ml-32m.zip.md5"
KNOWN_MD5 = "d472be332d4daa821edc399621853b57"

ProgressCallback = Callable[[str, float], None]


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
        raise NotImplementedError

    @property
    def n_users(self) -> int:
        return int(self.matrix.shape[0])

    @property
    def n_movies(self) -> int:
        return int(self.matrix.shape[1])


def md5_file(path: Path) -> str:
    raise NotImplementedError


def verify_md5(path: Path, expected: str) -> None:
    """Raise ChecksumError if the file's MD5 differs from `expected`."""
    raise NotImplementedError


def parse_md5_text(text: str) -> str:
    """Extract the hex digest from a `.md5` file ("<hash>  <name>")."""
    raise NotImplementedError


def download_movielens(
    raw_dir: Path,
    *,
    url: str = ML_URL,
    md5_url: str = ML_MD5_URL,
    ca_bundle: Path | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[Path, str]:
    """Download the zip (if needed) and verify it. Returns (zip path, md5)."""
    raise NotImplementedError


def extract_zip(zip_path: Path, target_dir: Path) -> Path:
    """Extract ratings.csv, movies.csv and links.csv; return the directory containing them."""
    raise NotImplementedError


def read_ratings_csv(path: Path) -> pd.DataFrame:
    """Read ratings.csv with pyarrow: userId int32, movieId int32, rating float32."""
    raise NotImplementedError


def read_movies_csv(path: Path) -> pd.DataFrame:
    raise NotImplementedError


def read_links_csv(path: Path) -> pd.DataFrame:
    """Read links.csv; tmdbId is a nullable Int32 column."""
    raise NotImplementedError


def parse_ml_title(title: str) -> tuple[str, int | None]:
    """Split "Name (Year)" into ("Name", Year)."""
    raise NotImplementedError


def clean_ml_title(title: str) -> str:
    """Human readable title: drop year and alternative titles, move trailing article to front."""
    raise NotImplementedError


def is_processed(processed_dir: Path, checksum: str) -> bool:
    raise NotImplementedError


def process_movielens(
    source_dir: Path,
    processed_dir: Path,
    checksum: str,
    *,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> bool:
    """Preprocess CSVs into data/processed. Returns False if skipped (already up to date)."""
    raise NotImplementedError


def load_processed(processed_dir: Path) -> ProcessedData:
    raise NotImplementedError


def build_processed(
    ratings: pd.DataFrame, movies: pd.DataFrame, links: pd.DataFrame
) -> ProcessedData:
    """Build ProcessedData in memory (used by processing, tests and the demo)."""
    raise NotImplementedError


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
    raise NotImplementedError
