"""Paths, environment and the central recommender configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RecommenderConfig:
    """All collaborative-filtering parameters in one place."""

    min_overlap: int = 10
    shrinkage: float = 25.0
    k: int = 50
    min_support: int = 5
    prior_weight: float = 3.0
    min_own_ratings: int = 30
    recompute_after_new_ratings: int = 25
    provider_candidates: int = 3000


@dataclass(frozen=True)
class Settings:
    """Runtime settings derived from environment variables and `.env`."""

    data_dir: Path
    tmdb_token: str | None = None
    tmdb_base_url: str = "https://api.themoviedb.org/3"
    offline: bool = False
    ca_bundle: Path | None = None
    match_threshold: float = 85.0

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "filmzwilling.sqlite"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"


def load_settings(data_dir: Path | None = None, env_file: Path | None = None) -> Settings:
    """Build settings from `.env`, environment variables and explicit overrides."""
    raise NotImplementedError
