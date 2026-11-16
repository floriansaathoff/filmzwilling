"""Paths, environment and the central recommender configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


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


TRUE_VALUES = {"1", "true", "yes", "ja", "on"}


def _env(name: str, file_values: dict[str, str | None]) -> str | None:
    """Environment variables win over values from the `.env` file."""
    value = os.environ.get(name)
    if value is None:
        value = file_values.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def load_settings(data_dir: Path | None = None, env_file: Path | None = None) -> Settings:
    """Build settings from `.env`, environment variables and explicit overrides."""
    path = env_file if env_file is not None else Path.cwd() / ".env"
    file_values: dict[str, str | None] = dict(dotenv_values(path)) if path.exists() else {}
    if data_dir is None:
        env_dir = _env("FILMZWILLING_DATA_DIR", file_values)
        data_dir = Path(env_dir) if env_dir else Path.cwd() / "data"
    ca = _env("FILMZWILLING_CA_BUNDLE", file_values)
    offline = (_env("FILMZWILLING_OFFLINE", file_values) or "").lower() in TRUE_VALUES
    base_url = _env("TMDB_BASE_URL", file_values) or "https://api.themoviedb.org/3"
    return Settings(
        data_dir=Path(data_dir),
        tmdb_token=_env("TMDB_READ_TOKEN", file_values),
        tmdb_base_url=base_url,
        offline=offline,
        ca_bundle=Path(ca) if ca else None,
    )
