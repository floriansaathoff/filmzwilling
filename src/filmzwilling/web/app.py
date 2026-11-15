"""FastAPI application: HTML pages and JSON API."""

from __future__ import annotations

from fastapi import FastAPI

from filmzwilling.config import Settings
from filmzwilling.service import FilmService


def create_app(service: FilmService) -> FastAPI:
    raise NotImplementedError


def create_app_from_settings(settings: Settings) -> FastAPI:
    raise NotImplementedError
