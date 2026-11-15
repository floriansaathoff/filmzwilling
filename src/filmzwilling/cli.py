"""Command line interface (`filmzwilling ...`)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(help="Filmzwilling: Film-Empfehlungen von deinen Geschmackszwillingen.")
import_app = typer.Typer(help="Sehverläufe importieren.")
app.add_typer(import_app, name="import")

DataDirOption = Annotated[
    Path | None,
    typer.Option(
        "--data-dir", help="Datenverzeichnis (Standard: ./data oder FILMZWILLING_DATA_DIR)"
    ),
]


@app.command()
def setup(
    data_dir: DataDirOption = None,
    zip_path: Annotated[
        Path | None, typer.Option("--zip", help="Bereits geladene ml-32m.zip")
    ] = None,
    md5: Annotated[str | None, typer.Option("--md5", help="Erwartete MD5-Prüfsumme")] = None,
) -> None:
    """MovieLens 32M laden, prüfen und aufbereiten."""
    raise NotImplementedError


@app.command("tmdb-sync")
def tmdb_sync(
    data_dir: DataDirOption = None,
    limit: Annotated[int | None, typer.Option("--limit", help="Höchstens N Filme")] = None,
) -> None:
    """Metadaten für die Warteschlange von TMDB holen."""
    raise NotImplementedError


@import_app.command("netflix")
def import_netflix(
    path: Path,
    data_dir: DataDirOption = None,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
) -> None:
    """Netflix-Datenexport oder einfachen Titelverlauf importieren."""
    raise NotImplementedError


@import_app.command("prime")
def import_prime(
    path: Path,
    data_dir: DataDirOption = None,
    mapping: Annotated[Path | None, typer.Option("--mapping")] = None,
) -> None:
    """Prime-Video-Verlauf (CSV oder JSON) importieren."""
    raise NotImplementedError


@import_app.command("csv")
def import_csv(path: Path, data_dir: DataDirOption = None) -> None:
    """Generische CSV (title, year, profile, watched_fraction) importieren."""
    raise NotImplementedError


@import_app.command("inspect")
def import_inspect(
    path: Path, mapping: Annotated[Path | None, typer.Option("--mapping")] = None
) -> None:
    """Erkannte Spalten und vermutete Zuordnung anzeigen."""
    raise NotImplementedError


@app.command()
def serve(
    data_dir: DataDirOption = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: Annotated[bool, typer.Option("--open")] = False,
) -> None:
    """Weboberfläche starten."""
    raise NotImplementedError


@app.command()
def recommend(
    data_dir: DataDirOption = None,
    top: Annotated[int, typer.Option("--top")] = 20,
) -> None:
    """Empfehlungen berechnen und die besten 20 zeigen."""
    raise NotImplementedError


@app.command()
def evaluate(data_dir: DataDirOption = None) -> None:
    """5-fache Kreuzvalidierung über die eigenen Bewertungen."""
    raise NotImplementedError


@app.command()
def check(
    title: str,
    data_dir: DataDirOption = None,
    year: Annotated[int | None, typer.Option("--year")] = None,
) -> None:
    """Ist ein Film in MovieLens, wie populär ist er, steht er in der Warteschlange?"""
    raise NotImplementedError


@app.command("export-ratings")
def export_ratings_cmd(path: Path, data_dir: DataDirOption = None) -> None:
    """Eigene Bewertungen als CSV exportieren."""
    raise NotImplementedError


@app.command()
def demo(
    data_dir: DataDirOption = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    no_serve: Annotated[bool, typer.Option("--no-serve", help="Nur Daten erzeugen")] = False,
    open_browser: Annotated[bool, typer.Option("--open")] = False,
) -> None:
    """App mit synthetischen Daten starten (ohne Netz, ohne Token)."""
    raise NotImplementedError


def main() -> None:
    app()
