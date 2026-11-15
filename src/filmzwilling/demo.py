"""`filmzwilling demo`: synthetic data dir with MovieLens-like data, metadata and providers."""

from __future__ import annotations

from pathlib import Path

from filmzwilling.config import Settings


def prepare_demo(
    data_dir: Path, *, seed: int = 7, n_users: int = 600, n_movies: int = 400
) -> Settings:
    """Create processed synthetic data, a database with metadata, providers and imports."""
    raise NotImplementedError
