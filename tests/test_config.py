from __future__ import annotations

from pathlib import Path

import pytest

from filmzwilling.config import RecommenderConfig, Settings, load_settings


def test_recommender_defaults() -> None:
    cfg = RecommenderConfig()
    assert cfg.min_overlap == 10
    assert cfg.shrinkage == 25
    assert cfg.k == 50
    assert cfg.min_support == 5
    assert cfg.prior_weight == 3
    assert cfg.min_own_ratings == 30
    assert cfg.recompute_after_new_ratings == 25
    assert cfg.provider_candidates == 3000


def test_paths(tmp_path: Path) -> None:
    s = Settings(data_dir=tmp_path)
    assert s.raw_dir == tmp_path / "raw"
    assert s.processed_dir == tmp_path / "processed"
    assert s.db_path.parent == tmp_path
    assert s.backups_dir == tmp_path / "backups"


def test_load_settings_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FILMZWILLING_DATA_DIR", str(tmp_path / "x"))
    monkeypatch.setenv("TMDB_READ_TOKEN", "abc123")
    monkeypatch.delenv("FILMZWILLING_OFFLINE", raising=False)
    s = load_settings(env_file=tmp_path / "missing.env")
    assert s.data_dir == tmp_path / "x"
    assert s.tmdb_token == "abc123"
    assert s.offline is False


def test_empty_token_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMDB_READ_TOKEN", "  ")
    s = load_settings(data_dir=tmp_path, env_file=tmp_path / "missing.env")
    assert s.tmdb_token is None


def test_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMDB_READ_TOKEN", raising=False)
    monkeypatch.delenv("FILMZWILLING_DATA_DIR", raising=False)
    env = tmp_path / ".env"
    env.write_text("TMDB_READ_TOKEN=fromfile\nFILMZWILLING_OFFLINE=1\n", encoding="utf-8")
    s = load_settings(data_dir=tmp_path / "d", env_file=env)
    assert s.tmdb_token == "fromfile"
    assert s.offline is True
    assert s.data_dir == tmp_path / "d"


def test_explicit_data_dir_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FILMZWILLING_DATA_DIR", str(tmp_path / "env"))
    s = load_settings(data_dir=tmp_path / "arg", env_file=tmp_path / "missing.env")
    assert s.data_dir == tmp_path / "arg"


def test_default_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FILMZWILLING_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    s = load_settings(env_file=tmp_path / "missing.env")
    assert s.data_dir.resolve() == (tmp_path / "data").resolve()


def test_ca_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FILMZWILLING_CA_BUNDLE", str(tmp_path / "ca.pem"))
    s = load_settings(data_dir=tmp_path, env_file=tmp_path / "missing.env")
    assert s.ca_bundle == tmp_path / "ca.pem"
