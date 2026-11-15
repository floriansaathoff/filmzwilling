"""FastAPI application: HTML pages and JSON API."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from filmzwilling import __version__
from filmzwilling.backup import write_ratings_csv
from filmzwilling.config import Settings
from filmzwilling.filters import RecFilter
from filmzwilling.placeholder import placeholder_svg
from filmzwilling.service import FilmService, ServiceError, TMDBUnavailableError
from filmzwilling.tmdb import TMDBError, poster_url

HERE = Path(__file__).parent
FOOTER = (
    "Diese App nutzt die TMDB-API, wird aber nicht von TMDB unterstützt oder zertifiziert. "
    "Streaming-Verfügbarkeit: JustWatch."
)
NAV = [
    ("/", "Bewerten", "rate"),
    ("/empfehlungen", "Empfehlungen", "recs"),
    ("/bewertungen", "Meine Bewertungen", "ratings"),
    ("/zuordnung", "Zuordnung", "matching"),
    ("/zwillinge", "Zwillinge", "twins"),
    ("/einstellungen", "Einstellungen", "settings"),
]

Score = Annotated[int, Field(strict=True, ge=0, le=10)]


class FilmIn(BaseModel):
    film_id: int


class RateIn(BaseModel):
    film_id: int
    score: Score
    context: str = "queue"


class ScoreIn(BaseModel):
    score: Score


class ResolveIn(BaseModel):
    tmdb_id: int


class SettingsIn(BaseModel):
    my_profiles: list[str] | None = None
    my_providers: list[int] | None = None
    queue_size: Annotated[int, Field(ge=0, le=100_000)] | None = None


def _query_dict(request: Request) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for key in request.query_params:
        values = request.query_params.getlist(key)
        params[key] = values if len(values) > 1 else values[0]
    return params


def create_app(service: FilmService) -> FastAPI:
    app = FastAPI(title="Filmzwilling", version=__version__, docs_url="/api/docs", redoc_url=None)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.state.service = service
    repo = service.repo

    @app.exception_handler(TMDBUnavailableError)
    async def _offline(_: Request, exc: TMDBUnavailableError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(TMDBError)
    async def _tmdb_error(_: Request, exc: TMDBError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=502)

    def page(request: Request, template: str, active: str, **context: Any) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            template,
            {"nav": NAV, "active": active, "footer": FOOTER, "version": __version__, **context},
        )

    def not_found(message: str = "Film nicht gefunden") -> HTTPException:
        return HTTPException(status_code=404, detail=message)

    # --- pages ----------------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def rate_page(request: Request) -> HTMLResponse:
        return page(request, "rate.html", "rate", progress=service.progress().as_dict())

    @app.get("/empfehlungen", response_class=HTMLResponse)
    def recs_page(request: Request) -> HTMLResponse:
        count = repo.count_ratings()
        return page(
            request,
            "recommendations.html",
            "recs",
            rating_count=count,
            min_ratings=service.config.min_own_ratings,
            has_data=service.data() is not None,
            providers=[
                {"id": p.provider_id, "name": p.name, "logo_url": poster_url(p.logo_path, "w92")}
                for p in repo.list_providers()
            ],
            default_providers=service.default_provider_ids(),
            genres=repo.genres(),
            meta=repo.get_setting("recs_meta"),
        )

    @app.get("/bewertungen", response_class=HTMLResponse)
    def ratings_page(request: Request) -> HTMLResponse:
        return page(request, "ratings.html", "ratings", count=repo.count_ratings())

    @app.get("/zuordnung", response_class=HTMLResponse)
    def matching_page(request: Request) -> HTMLResponse:
        return page(
            request, "matching.html", "matching", items=repo.list_unmatched(), online=service.online
        )

    @app.get("/zwillinge", response_class=HTMLResponse)
    def twins_page(request: Request) -> HTMLResponse:
        return page(
            request,
            "twins.html",
            "twins",
            twins=service.twins(),
            meta=repo.get_setting("recs_meta"),
        )

    @app.get("/einstellungen", response_class=HTMLResponse)
    def settings_page(request: Request) -> HTMLResponse:
        return page(
            request,
            "settings.html",
            "settings",
            evaluation=repo.get_setting("evaluation"),
            meta=repo.get_setting("recs_meta"),
            online=service.online,
        )

    @app.get("/poster/{film_id}.svg")
    def poster(film_id: int) -> Response:
        film = repo.get_film(film_id)
        if film is None:
            raise not_found()
        svg = placeholder_svg(film.display_title, film.display_year)
        return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "max-age=86400"})

    # --- queue ----------------------------------------------------------------------------
    @app.get("/api/queue")
    def queue(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        return {
            "items": service.queue_items(limit=limit, offset=offset),
            "progress": service.progress().as_dict(),
        }

    @app.get("/api/progress")
    def progress() -> dict[str, int]:
        return service.progress().as_dict()

    @app.post("/api/rate")
    def rate(body: RateIn) -> dict[str, Any]:
        try:
            started = service.rate(body.film_id, body.score, from_queue=body.context == "queue")
        except KeyError as exc:
            raise not_found() from exc
        return {"ok": True, "progress": service.progress().as_dict(), "recompute_started": started}

    def _simple_action(action: Any, film_id: int) -> dict[str, Any]:
        try:
            action(film_id)
        except KeyError as exc:
            raise not_found() from exc
        return {"ok": True, "progress": service.progress().as_dict()}

    @app.post("/api/not-seen")
    def not_seen(body: FilmIn) -> dict[str, Any]:
        return _simple_action(service.not_seen, body.film_id)

    @app.post("/api/later")
    def later(body: FilmIn) -> dict[str, Any]:
        return _simple_action(service.later, body.film_id)

    @app.post("/api/not-interested")
    def not_interested(body: FilmIn) -> dict[str, Any]:
        return _simple_action(service.not_interested, body.film_id)

    @app.post("/api/undo")
    def undo() -> dict[str, Any]:
        undone = service.undo()
        if undone is None:
            raise HTTPException(status_code=404, detail="Nichts zum Rückgängigmachen")
        item = undone.pop("item")
        return {"undone": undone, "item": item, "progress": service.progress().as_dict()}

    # --- recommendations ------------------------------------------------------------------
    @app.get("/api/recommendations")
    def recommendations(
        request: Request, limit: Annotated[int, Query(ge=1, le=1000)] = 120
    ) -> dict[str, Any]:
        params = _query_dict(request)
        params.pop("limit", None)
        return service.recommendations(service.parse_filter(params), limit=limit)

    @app.post("/api/recompute")
    def recompute() -> dict[str, Any]:
        return {"status": "ok", **service.recompute()}

    @app.get("/api/new-releases")
    def new_releases(request: Request) -> dict[str, Any]:
        flt = service.parse_filter(_query_dict(request))
        return {"items": service.new_release_items(flt), "personalized": False}

    @app.post("/api/new-releases/refresh")
    async def refresh_new_releases() -> dict[str, Any]:
        return {"count": await service.refresh_new_releases()}

    @app.post("/api/availability/refresh")
    async def refresh_availability() -> dict[str, Any]:
        await service.refresh_providers()
        return {"updated": await service.refresh_availability()}

    @app.get("/api/twins")
    def twins() -> dict[str, Any]:
        return {"items": service.twins()}

    @app.get("/api/genres")
    def genres() -> dict[str, Any]:
        return {"items": repo.genres()}

    # --- my ratings -----------------------------------------------------------------------
    @app.get("/api/ratings")
    def ratings(q: str | None = None) -> dict[str, Any]:
        items = repo.list_ratings(q)
        for item in items:
            item["poster_url"] = (
                poster_url(item.pop("poster_path"), "w92") or f"/poster/{item['film_id']}.svg"
            )
        return {"items": items, "total": len(items)}

    @app.put("/api/ratings/{film_id}")
    def update_rating(film_id: int, body: ScoreIn) -> dict[str, Any]:
        try:
            service.rate(film_id, body.score, from_queue=False)
        except KeyError as exc:
            raise not_found() from exc
        return {"ok": True}

    @app.delete("/api/ratings/{film_id}")
    def delete_rating(film_id: int) -> dict[str, Any]:
        if not repo.delete_rating(film_id):
            raise not_found("Keine Bewertung für diesen Film")
        return {"ok": True}

    @app.get("/api/ratings/export.csv")
    def export_csv() -> Response:
        buffer = io.StringIO()
        write_ratings_csv(repo, buffer)
        return Response(
            buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="bewertungen.csv"'},
        )

    # --- matching -------------------------------------------------------------------------
    @app.get("/api/unmatched")
    def unmatched() -> dict[str, Any]:
        return {
            "items": [
                {
                    "id": u.id,
                    "raw_title": u.raw_title,
                    "year": u.year,
                    "source": u.source,
                    "best_score": u.best_score,
                    "best_title": u.best_title,
                    "profiles": u.profiles,
                }
                for u in repo.list_unmatched()
            ]
        }

    @app.get("/api/tmdb/search")
    async def tmdb_search(
        q: Annotated[str, Query(min_length=1)], year: int | None = None
    ) -> dict[str, Any]:
        return {"items": await service.search_tmdb(q, year)}

    @app.post("/api/unmatched/{unmatched_id}/resolve")
    async def resolve(unmatched_id: int, body: ResolveIn) -> dict[str, Any]:
        try:
            film_id = await service.resolve_unmatched(unmatched_id, body.tmdb_id)
        except KeyError as exc:
            raise not_found("Eintrag nicht gefunden") from exc
        return {"ok": True, "film_id": film_id}

    @app.post("/api/unmatched/{unmatched_id}/ignore")
    def ignore(unmatched_id: int) -> dict[str, Any]:
        try:
            repo.ignore_unmatched(unmatched_id)
        except KeyError as exc:
            raise not_found("Eintrag nicht gefunden") from exc
        return {"ok": True}

    # --- settings -------------------------------------------------------------------------
    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        settings = repo.get_user_settings()
        mine = set(service.default_provider_ids())
        return {
            "my_profiles": settings.my_profiles,
            "all_profiles": repo.profiles(),
            "my_providers": settings.my_providers
            if settings.my_providers is not None
            else sorted(mine),
            "providers": [
                {
                    "id": p.provider_id,
                    "name": p.name,
                    "logo_url": poster_url(p.logo_path, "w92"),
                    "mine": p.provider_id in mine,
                }
                for p in repo.list_providers()
            ],
            "queue_size": settings.queue_size,
            "evaluation": repo.get_setting("evaluation"),
            "recs": repo.get_setting("recs_meta"),
            "online": service.online,
        }

    @app.put("/api/settings")
    def put_settings(body: SettingsIn) -> dict[str, Any]:
        if body.my_profiles is not None:
            unknown = set(body.my_profiles) - set(repo.profiles())
            if unknown:
                raise HTTPException(
                    status_code=422, detail=f"Unbekannte Profile: {', '.join(sorted(unknown))}"
                )
        repo.update_user_settings(
            my_profiles=body.my_profiles, my_providers=body.my_providers, queue_size=body.queue_size
        )
        return get_settings()

    @app.post("/api/evaluate")
    def evaluate() -> dict[str, Any]:
        return service.evaluate().to_dict()

    return app


def create_app_from_settings(settings: Settings) -> FastAPI:
    return create_app(FilmService(settings))


__all__ = ["RecFilter", "create_app", "create_app_from_settings"]
