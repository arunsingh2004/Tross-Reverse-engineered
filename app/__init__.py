from __future__ import annotations

import logging
import secrets
import time
import uuid
from typing import Any

from flask import Flask, g, request

from app.api import api
from app.config import Settings
from app.errors import register_error_handlers
from app.scrapers.base import ProfileScraper
from app.scrapers.voyager import LinkedInVoyagerScraper
from app.services.profile_service import ProfileService


def create_app(
    config_override: dict[str, Any] | None = None,
    *,
    scraper: ProfileScraper | None = None,
) -> Flask:
    """Create and configure the Flask application."""
    settings = Settings.from_env()
    app = Flask(__name__)
    app.config.update(settings.to_flask_config())
    if config_override:
        app.config.update(config_override)

    logging.basicConfig(
        level=getattr(logging, str(app.config["LOG_LEVEL"]).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    active_scraper = scraper or LinkedInVoyagerScraper.from_config(app.config)
    app.extensions["profile_service"] = ProfileService(
        scraper=active_scraper,
        cache_ttl_seconds=int(app.config["CACHE_TTL_SECONDS"]),
    )

    @app.before_request
    def add_request_context() -> None:
        supplied_id = request.headers.get("X-Request-ID", "").strip()
        g.request_id = supplied_id[:128] if supplied_id else str(uuid.uuid4())
        g.request_started_at = time.perf_counter()

    @app.before_request
    def require_api_key() -> None:
        expected = str(app.config.get("API_KEY") or "")
        if not expected or not request.path.startswith("/v1/"):
            return

        bearer = request.headers.get("Authorization", "")
        supplied = (
            bearer.removeprefix("Bearer ").strip()
            if bearer.startswith("Bearer ")
            else request.headers.get("X-API-Key", "").strip()
        )
        if not supplied or not secrets.compare_digest(supplied, expected):
            from app.errors import ApiError

            raise ApiError(
                status=401,
                code="unauthorized",
                title="Unauthorized",
                detail="Provide a valid Bearer token or X-API-Key header.",
            )

    @app.after_request
    def add_response_headers(response):
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    app.register_blueprint(api)
    register_error_handlers(app)
    return app
