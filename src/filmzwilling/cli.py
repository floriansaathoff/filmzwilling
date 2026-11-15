"""Command line interface (`filmzwilling ...`)."""

from __future__ import annotations

import asyncio
import tempfile
import threading
import webbrowser
from pathlib import Path
from typing import Annotated, Any

import typer
import uvicorn

from filmzwilling.backup import backup_ratings, export_ratings
from filmzwilling.config import Settings, load_settings
from filmzwilling.importers.common import ImportReport
from filmzwilling.importers.prime import inspect_file
from filmzwilling.movielens import ChecksumError, DownloadError, setup_movielens
from filmzwilling.service import NO_DATA_MESSAGE, FilmService, ServiceError
from filmzwilling.tmdb import TMDBError

app = typer.Typer(
    help="Filmzwilling: Film-Empfehlungen von deinen Geschmackszwillingen.",
    no_args_is_help=True,
    add_completion=False,
)
import_app = typer.Typer(help="Sehverläufe importieren.", no_args_is_help=True)
app.add_typer(import_app, name="import")

DataDirOption = Annotated[
    Path | None,
    typer.Option(
        "--data-dir", help="Datenverzeichnis (Standard: ./data oder FILMZWILLING_DATA_DIR)"
    ),
]


def _fail(message: str) -> typer.Exit:
    typer.echo(message, err=False)
    return typer.Exit(code=1)


def _settings(data_dir: Path | None) -> Settings:
    return load_settings(data_dir=data_dir)


def _service(data_dir: Path | None, *, need_data: bool = True) -> FilmService:
    service = FilmService(_settings(data_dir))
    if need_data and service.data() is None:
        raise _fail(NO_DATA_MESSAGE)
    return service


def _de(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


class _Progress:
    def __init__(self) -> None:
        self.last: tuple[str, int] | None = None

    def __call__(self, stage: str, fraction: float) -> None:
        # Downloads report every 5 %, the processing steps once each.
        key = (stage, int(fraction * 20) if stage == "download" else 0)
        if key != self.last:
            self.last = key
            label = "Download" if stage == "download" else stage
            typer.echo(f"  [{int(fraction * 100):3d} %] {label}")


@app.command()
def setup(
    data_dir: DataDirOption = None,
    zip_path: Annotated[
        Path | None, typer.Option("--zip", help="Bereits geladene ml-32m.zip")
    ] = None,
    md5: Annotated[str | None, typer.Option("--md5", help="Erwartete MD5-Prüfsumme")] = None,
) -> None:
    """MovieLens 32M laden, prüfen und aufbereiten."""
    settings = _settings(data_dir)
    typer.echo(f"Datenverzeichnis: {settings.data_dir}")
    try:
        ran = setup_movielens(
            settings.raw_dir,
            settings.processed_dir,
            zip_path=zip_path,
            expected_md5=md5,
            ca_bundle=settings.ca_bundle,
            progress=_Progress(),
        )
    except ChecksumError as exc:
        raise _fail(f"Prüfsumme falsch: {exc}") from exc
    except (DownloadError, FileNotFoundError, ValueError) as exc:
        raise _fail(str(exc)) from exc
    if ran:
        typer.echo("MovieLens wurde aufbereitet.")
    else:
        typer.echo(
            "MovieLens ist schon aufbereitet und die Prüfsumme passt: Aufbereitung übersprungen."
        )
    service = FilmService(settings)
    count = service.sync_movielens_films()
    typer.echo(f"{_thousands(count)} Filme in der App-Datenbank.")
    typer.echo(
        "Weiter mit: filmzwilling import … und filmzwilling tmdb-sync, dann filmzwilling serve"
    )


@app.command("tmdb-sync")
def tmdb_sync(
    data_dir: DataDirOption = None,
    limit: Annotated[int | None, typer.Option("--limit", help="Höchstens N Filme")] = None,
) -> None:
    """Metadaten für die Warteschlange von TMDB holen."""
    service = _service(data_dir, need_data=False)
    if service.settings.offline:
        raise _fail("TMDB ist im Offline- oder Demo-Modus nicht verfügbar (FILMZWILLING_OFFLINE).")

    async def run() -> dict[str, Any]:
        providers = await service.refresh_providers()
        stats = await service.match_pending()
        metadata = await service.sync_queue_metadata(limit)
        availability = (
            await service.refresh_availability(force=False)
            if service.repo.load_recommendations()
            else 0
        )
        fresh = await service.refresh_new_releases()
        return {
            "providers": len(providers),
            "matched": stats.matched,
            "unmatched": stats.unmatched,
            "series": stats.series,
            "metadata": metadata,
            "availability": availability,
            "new": fresh,
        }

    try:
        result = asyncio.run(run())
    except (TMDBError, ServiceError) as exc:
        raise _fail(str(exc)) from exc
    typer.echo(f"Anbieterliste: {result['providers']} Anbieter für Deutschland.")
    typer.echo(
        f"Importtitel: {result['matched']} zugeordnet, {result['unmatched']} unklar (Seite "
        "„Zuordnung“), "
        f"{result['series']} als Serie verworfen."
    )
    typer.echo(f"Metadaten: {result['metadata']} Filme der Warteschlange aktualisiert.")
    typer.echo(f"Verfügbarkeit: {result['availability']} Empfehlungen aktualisiert.")
    typer.echo(f"Neuerscheinungen seit Oktober 2023: {result['new']} Filme.")


def _print_report(report: ImportReport) -> None:
    parse = report.parse
    typer.echo(
        f"{parse.rows} Zeilen gelesen, {len(parse.events)} Filme erkannt: "
        f"{report.inserted} neu, {report.updated} aktualisiert, {report.unchanged} unverändert."
    )
    skipped = [
        (parse.skipped_series, "Serienfolgen"),
        (parse.skipped_supplemental, "Trailer/Vorschauen"),
        (parse.skipped_short, "kurz angespielt (Autoplay)"),
        (parse.skipped_invalid, "ohne Titel"),
    ]
    details = ", ".join(f"{n} {label}" for n, label in skipped if n)
    if details:
        typer.echo(f"Verworfen: {details}.")
    if report.matched or report.unmatched or report.series:
        typer.echo(
            f"TMDB: {report.matched} zugeordnet, {report.unmatched} unklar (Seite „Zuordnung“), "
            f"{report.series} als Serie verworfen."
        )
    for note in report.notes:
        typer.echo(note)


def _run_import(data_dir: Path | None, kind: str, path: Path, **options: Any) -> None:
    service = _service(data_dir, need_data=False)
    try:
        report = service.import_file(kind, path, **options)
    except FileNotFoundError as exc:
        raise _fail(f"Datei nicht gefunden: {path}") from exc
    except (ValueError, TMDBError, ServiceError) as exc:
        raise _fail(str(exc)) from exc
    _print_report(report)


@import_app.command("netflix")
def import_netflix(
    path: Path,
    data_dir: DataDirOption = None,
    profile: Annotated[
        str | None, typer.Option("--profile", help="Profilname für den einfachen Export")
    ] = None,
) -> None:
    """Netflix-Datenexport oder einfachen Titelverlauf importieren."""
    _run_import(data_dir, "netflix", path, profile=profile)


@import_app.command("prime")
def import_prime(
    path: Path,
    data_dir: DataDirOption = None,
    mapping: Annotated[
        Path | None, typer.Option("--mapping", help="TOML-Datei mit Spaltenzuordnung")
    ] = None,
) -> None:
    """Prime-Video-Verlauf (CSV oder JSON) importieren."""
    _run_import(data_dir, "prime", path, mapping=mapping)


@import_app.command("csv")
def import_csv(path: Path, data_dir: DataDirOption = None) -> None:
    """Generische CSV (title, year, profile, watched_fraction) importieren."""
    _run_import(data_dir, "csv", path)


@import_app.command("inspect")
def import_inspect(
    path: Path, mapping: Annotated[Path | None, typer.Option("--mapping")] = None
) -> None:
    """Erkannte Spalten und vermutete Zuordnung anzeigen."""
    try:
        report = inspect_file(path, mapping)
    except (FileNotFoundError, ValueError) as exc:
        raise _fail(str(exc)) from exc
    typer.echo(f"Datei: {report.path} ({report.format}, {report.row_count} Einträge)")
    typer.echo("Erkannte Spalten: " + ", ".join(report.headers))
    typer.echo("Vermutete Zuordnung:")
    for name, value in report.mapping.as_dict().items():
        if name in ("units", "default_profile"):
            continue
        unit = report.mapping.units.get(name)
        typer.echo(
            f"  {name:<9} → {value if value else '–'}{f' ({unit})' if unit and value else ''}"
        )
    typer.echo(f"  Standardprofil: {report.mapping.default_profile}")
    if report.sample:
        typer.echo("Beispiele:")
        for record in report.sample[:3]:
            typer.echo("  " + "; ".join(f"{k}={v}" for k, v in record.items() if k != "__kind__"))
    if not report.mapping.title:
        typer.echo(
            "Keine Titel-Spalte erkannt: lege eine TOML-Datei an und nutze --mapping (siehe "
            "README)."
        )


@app.command()
def serve(
    data_dir: DataDirOption = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: Annotated[bool, typer.Option("--open", help="Browser öffnen")] = False,
) -> None:
    """Weboberfläche starten."""
    from filmzwilling.web.app import create_app

    service = _service(data_dir, need_data=False)
    backup = backup_ratings(service.repo, service.settings.backups_dir)
    typer.echo(f"Backup der Bewertungen: {backup}")
    if service.data() is None:
        typer.echo(NO_DATA_MESSAGE)
    _start(service, host, port, open_browser, create_app)


def _start(service: FilmService, host: str, port: int, open_browser: bool, factory: Any) -> None:
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"
    typer.echo(f"Filmzwilling läuft auf {url}")
    if host in ("0.0.0.0", "::"):
        typer.echo(
            f"Im WLAN erreichbar über die IP-Adresse dieses Rechners, z. B. http://192.168.x.y:{port}/"
        )
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(factory(service), host=host, port=port, log_level="warning")


@app.command()
def recommend(
    data_dir: DataDirOption = None,
    top: Annotated[int, typer.Option("--top", help="Anzahl")] = 20,
) -> None:
    """Empfehlungen berechnen und die besten 20 zeigen."""
    service = _service(data_dir)
    count = service.repo.count_ratings()
    needed = service.config.min_own_ratings
    if count < needed:
        raise _fail(
            f"Bewerte mindestens {needed} Filme, dann gibt es Empfehlungen (bisher {count})."
        )
    try:
        items = service.top_recommendations(top)
    except ServiceError as exc:
        raise _fail(str(exc)) from exc
    meta = service.repo.get_setting("recs_meta") or {}
    typer.echo(
        f"Top {len(items)} aus {_thousands(int(meta.get('count', 0)))} Kandidaten "
        f"(berechnet in {_de(float(meta.get('duration_seconds', 0)))} s):"
    )
    for i, item in enumerate(items, start=1):
        offers = sorted(
            {o["name"] for o in item["offers"] if o["category"] in ("flatrate", "free", "ads")}
        )
        year = f" ({item['year']})" if item.get("year") else ""
        line = f"{i:3d}. {item['score_text']:>4}  {item['title']}{year} · {item['reason']}"
        if offers:
            line += " · " + ", ".join(offers)
        typer.echo(line)


@app.command()
def evaluate(data_dir: DataDirOption = None) -> None:
    """5-fache Kreuzvalidierung über die eigenen Bewertungen."""
    service = _service(data_dir)
    try:
        result = service.evaluate()
    except ServiceError as exc:
        raise _fail(str(exc)) from exc
    typer.echo(f"Selbsttest: 5-fache Kreuzvalidierung über {result.n_ratings} eigene Bewertungen")
    typer.echo(
        f"  RMSE:     {_de(result.rmse, 2)}  (Baseline Filmdurchschnitt: "
        f"{_de(result.baseline_rmse, 2)}, "
        f"{_de(result.improvement * 100, 0)} % besser)"
    )
    typer.echo(
        f"  Spearman: {_de(result.spearman, 2)}  (Baseline Filmdurchschnitt: "
        f"{_de(result.baseline_spearman, 2)})"
    )
    typer.echo(f"  Abdeckung durch Zwillinge: {_de(result.coverage * 100, 0)} %")


@app.command()
def check(
    title: str,
    data_dir: DataDirOption = None,
    year: Annotated[int | None, typer.Option("--year")] = None,
) -> None:
    """Ist ein Film in MovieLens, wie populär ist er, steht er in der Warteschlange?"""
    service = _service(data_dir)
    result = service.check_title(title, year)
    if not result.found:
        typer.echo(f"„{title}“ wurde in MovieLens nicht gefunden.")
        if result.note and "nicht" not in result.note.lower():
            typer.echo(result.note)
        return
    typer.echo(f"„{result.title}“ ({result.year or 'Jahr unbekannt'})")
    typer.echo(
        f"  In MovieLens: ja (movieId {result.movielens_id}, tmdbId {result.tmdb_id or '–'})"
    )
    mean = (
        f", im Schnitt {_de(result.mean_rating, 2)} von 5 Sternen"
        if result.mean_rating is not None
        else ""
    )
    typer.echo(f"  Bewertungen: {_thousands(result.rating_count or 0)}{mean}")
    typer.echo(
        f"  Popularitätsrang: {_thousands(result.popularity_rank or 0)} von "
        f"{_thousands(result.total_movies or 0)}"
    )
    typer.echo(f"  Warteschlange: {result.queue_status}")
    if result.note:
        typer.echo(f"  Hinweis: {result.note}")


@app.command("export-ratings")
def export_ratings_cmd(path: Path, data_dir: DataDirOption = None) -> None:
    """Eigene Bewertungen als CSV exportieren."""
    service = _service(data_dir, need_data=False)
    count = export_ratings(service.repo, path)
    typer.echo(f"{count} Bewertungen nach {path} exportiert.")


@app.command()
def demo(
    data_dir: DataDirOption = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    no_serve: Annotated[bool, typer.Option("--no-serve", help="Nur Daten erzeugen")] = False,
    open_browser: Annotated[bool, typer.Option("--open", help="Browser öffnen")] = False,
) -> None:
    """App mit synthetischen Daten starten (ohne Netz, ohne Token)."""
    from filmzwilling.demo import prepare_demo
    from filmzwilling.web.app import create_app

    target = data_dir or Path(tempfile.mkdtemp(prefix="filmzwilling-demo-"))
    typer.echo("Erzeuge synthetische Demo-Daten …")
    settings = prepare_demo(target)
    typer.echo(f"Demo-Daten liegen in {target}")
    if no_serve:
        return
    _start(FilmService(settings), host, port, open_browser, create_app)


def main() -> None:
    app()
