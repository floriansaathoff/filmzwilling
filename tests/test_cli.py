from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from filmzwilling import cli
from filmzwilling.config import Settings
from filmzwilling.db import Database
from filmzwilling.demo import prepare_demo
from filmzwilling.repository import Repository
from filmzwilling.synthetic import generate_dataset, write_zip

runner = CliRunner()


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FILMZWILLING_OFFLINE", "1")
    monkeypatch.delenv("TMDB_READ_TOKEN", raising=False)
    monkeypatch.delenv("FILMZWILLING_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture(scope="module")
def demo_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("demo")
    prepare_demo(d)
    return d


@pytest.fixture
def demo_dir(demo_template: Path, tmp_path: Path) -> Path:
    import shutil

    target = tmp_path / "demo-data"
    shutil.copytree(demo_template, target)
    return target


def rate_some(data_dir: Path, n: int = 60) -> Repository:
    repo = Repository(Database(Settings(data_dir=data_dir).db_path))
    from filmzwilling.rating_queue import build_queue

    queue = build_queue(repo)
    for i, entry in enumerate(queue[:n]):
        film = repo.get_film(entry.film_id)
        assert film is not None
        repo.set_rating(entry.film_id, (i * 7) % 11, log_action=False)
    return repo


def test_help() -> None:
    r = runner.invoke(cli.app, ["--help"])
    assert r.exit_code == 0
    for cmd in (
        "setup",
        "tmdb-sync",
        "import",
        "serve",
        "recommend",
        "evaluate",
        "check",
        "export-ratings",
        "demo",
    ):
        assert cmd in r.output


def test_demo_no_serve(tmp_path: Path) -> None:
    target = tmp_path / "d"
    r = runner.invoke(cli.app, ["demo", "--no-serve", "--data-dir", str(target)])
    assert r.exit_code == 0, r.output
    assert (target / "processed" / "matrix.npz").exists()
    assert Settings(data_dir=target).db_path.exists()
    assert str(target) in r.output


def test_demo_serves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fake_run(app, host: str, port: int, **kw):  # type: ignore[no-untyped-def]
        calls.update(host=host, port=port, app=app)

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    r = runner.invoke(cli.app, ["demo", "--data-dir", str(tmp_path / "d2"), "--port", "8123"])
    assert r.exit_code == 0, r.output
    assert calls["port"] == 8123 and calls["host"] == "127.0.0.1"


def test_import_commands(demo_dir: Path, fixtures_dir: Path) -> None:
    args = ["--data-dir", str(demo_dir)]
    r = runner.invoke(
        cli.app, ["import", "netflix", str(fixtures_dir / "netflix" / "CONTENT_INTERACTION"), *args]
    )
    assert r.exit_code == 0, r.output
    assert "10 neu" in r.output
    r = runner.invoke(
        cli.app, ["import", "netflix", str(fixtures_dir / "netflix" / "CONTENT_INTERACTION"), *args]
    )
    assert "0 neu" in r.output
    r = runner.invoke(
        cli.app,
        [
            "import",
            "netflix",
            str(fixtures_dir / "netflix" / "NetflixViewingHistory.csv"),
            "--profile",
            "Lena",
            *args,
        ],
    )
    assert r.exit_code == 0, r.output
    r = runner.invoke(
        cli.app,
        [
            "import",
            "prime",
            str(fixtures_dir / "prime" / "custom.csv"),
            "--mapping",
            str(fixtures_dir / "prime" / "mapping.toml"),
            *args,
        ],
    )
    assert r.exit_code == 0, r.output
    assert "2 neu" in r.output
    r = runner.invoke(cli.app, ["import", "csv", str(fixtures_dir / "csv" / "disney.csv"), *args])
    assert r.exit_code == 0, r.output
    assert "5 neu" in r.output
    repo = Repository(Database(Settings(data_dir=demo_dir).db_path))
    assert "Lena" in repo.profiles()


def test_import_errors(demo_dir: Path, fixtures_dir: Path, tmp_path: Path) -> None:
    r = runner.invoke(
        cli.app,
        [
            "import",
            "prime",
            str(fixtures_dir / "prime" / "custom.csv"),
            "--data-dir",
            str(demo_dir),
        ],
    )
    assert r.exit_code == 1
    assert "Titel" in r.output
    r = runner.invoke(
        cli.app, ["import", "csv", str(tmp_path / "missing.csv"), "--data-dir", str(demo_dir)]
    )
    assert r.exit_code == 1
    assert "nicht gefunden" in r.output


def test_import_inspect(fixtures_dir: Path) -> None:
    r = runner.invoke(
        cli.app,
        ["import", "inspect", str(fixtures_dir / "prime" / "PrimeVideo.ViewingHistory.csv")],
    )
    assert r.exit_code == 0, r.output
    assert "Date Watched (UTC)" in r.output
    assert "title" in r.output and "Title" in r.output
    r = runner.invoke(
        cli.app,
        [
            "import",
            "inspect",
            str(fixtures_dir / "prime" / "custom.csv"),
            "--mapping",
            str(fixtures_dir / "prime" / "mapping.toml"),
        ],
    )
    assert "Sendung" in r.output


def test_recommend_evaluate_check_export(demo_dir: Path, tmp_path: Path) -> None:
    args = ["--data-dir", str(demo_dir)]
    r = runner.invoke(cli.app, ["recommend", *args])
    assert r.exit_code == 1
    assert "30" in r.output
    rate_some(demo_dir, 60)
    r = runner.invoke(cli.app, ["recommend", *args])
    assert r.exit_code == 0, r.output
    lines = [line for line in r.output.splitlines() if "Zwilling" in line]
    assert len(lines) == 20
    r = runner.invoke(cli.app, ["evaluate", *args])
    assert r.exit_code == 0, r.output
    assert "RMSE" in r.output and "Spearman" in r.output and "Filmdurchschnitt" in r.output
    repo = Repository(Database(Settings(data_dir=demo_dir).db_path))
    film = repo.get_film(repo.popular_film_ids(1)[0])
    assert film is not None
    r = runner.invoke(cli.app, ["check", film.ml_title or film.display_title, *args])
    assert r.exit_code == 0, r.output
    assert "MovieLens" in r.output
    assert "Bewertungen" in r.output
    assert "Popularitätsrang" in r.output
    r = runner.invoke(cli.app, ["check", "Diesen Film gibt es nicht 123", *args])
    assert r.exit_code == 0
    assert "nicht" in r.output
    out = tmp_path / "export.csv"
    r = runner.invoke(cli.app, ["export-ratings", str(out), *args])
    assert r.exit_code == 0, r.output
    assert len(out.read_text(encoding="utf-8").splitlines()) == 61


def test_setup_from_zip(tmp_path: Path) -> None:
    ds = generate_dataset(
        n_users=30, n_movies=25, n_favorites=3, min_ratings=10, max_ratings=20, seed=8
    )
    z = write_zip(ds, tmp_path / "ml-32m.zip")
    digest = hashlib.md5(z.read_bytes()).hexdigest()
    data_dir = tmp_path / "data"
    r = runner.invoke(
        cli.app, ["setup", "--zip", str(z), "--md5", digest, "--data-dir", str(data_dir)]
    )
    assert r.exit_code == 0, r.output
    assert (data_dir / "processed" / "matrix.npz").exists()
    repo = Repository(Database(Settings(data_dir=data_dir).db_path))
    assert repo.count_films() == 25
    r = runner.invoke(
        cli.app, ["setup", "--zip", str(z), "--md5", digest, "--data-dir", str(data_dir)]
    )
    assert r.exit_code == 0
    assert "übersprungen" in r.output
    r = runner.invoke(
        cli.app, ["setup", "--zip", str(z), "--md5", "0" * 32, "--data-dir", str(tmp_path / "x")]
    )
    assert r.exit_code == 1
    assert "Prüfsumme" in r.output


def test_tmdb_sync_offline(demo_dir: Path) -> None:
    r = runner.invoke(cli.app, ["tmdb-sync", "--limit", "5", "--data-dir", str(demo_dir)])
    assert r.exit_code == 1
    assert "TMDB" in r.output


def test_commands_without_setup(tmp_path: Path) -> None:
    r = runner.invoke(cli.app, ["recommend", "--data-dir", str(tmp_path / "empty")])
    assert r.exit_code == 1
    assert "setup" in r.output


def test_serve_makes_backup(demo_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rate_some(demo_dir, 3)
    calls: dict[str, object] = {}

    def fake_run(app, host: str, port: int, **kw):  # type: ignore[no-untyped-def]
        calls.update(host=host, port=port)

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    r = runner.invoke(
        cli.app, ["serve", "--host", "0.0.0.0", "--port", "8765", "--data-dir", str(demo_dir)]
    )
    assert r.exit_code == 0, r.output
    assert calls == {"host": "0.0.0.0", "port": 8765}
    backup = demo_dir / "backups" / f"ratings-{date.today().isoformat()}.csv"
    assert backup.exists()
    assert len(backup.read_text(encoding="utf-8").splitlines()) == 4
