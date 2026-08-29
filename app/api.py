from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request, send_from_directory

from app.errors import ApiError
from app.models import ProfileRequest, ProfileResponse, ResponseMeta
from app.services.profile_service import ProfileService

api = Blueprint("api", __name__)


@api.get("/")
def index():
    return jsonify(
        {
            "name": "LinkedIn Profile API",
            "version": "1.0.0",
            "documentation": "/docs/openapi.yaml",
            "health": "/health/ready",
        }
    )


@api.get("/docs/openapi.yaml")
def openapi_spec():
    docs_directory = Path(current_app.root_path).parent / "docs"
    return send_from_directory(docs_directory, "openapi.yaml", mimetype="application/yaml")


@api.get("/health/live")
def health_live():
    return jsonify({"status": "ok"})


@api.get("/health/ready")
def health_ready():
    service: ProfileService = current_app.extensions["profile_service"]
    return jsonify(
        {
            "status": "ready",
            "scraper": service.scraper_name,
            "authenticated_session_configured": service.session_configured,
        }
    )


@api.post("/v1/profiles")
def get_profile():
    if not request.is_json:
        raise ApiError(
            415,
            "unsupported_media_type",
            "Unsupported media type",
            "Content-Type must be application/json.",
        )
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            400,
            "invalid_json",
            "Invalid JSON",
            "The request body must be a JSON object.",
        )

    profile_request = ProfileRequest.model_validate(payload)
    service: ProfileService = current_app.extensions["profile_service"]
    result = service.fetch(profile_request.profile_url)
    response = ProfileResponse(
        data=result.profile,
        meta=ResponseMeta(
            request_id=g.request_id,
            scraped_at=result.scraped_at,
            cached=result.cached,
            partial=bool(result.warnings),
            warnings=result.warnings,
        ),
    )
    return jsonify(response.model_dump(mode="json"))
