from __future__ import annotations

from dataclasses import dataclass

from flask import Flask, g, jsonify, request
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException


@dataclass
class ApiError(Exception):
    status: int
    code: str
    title: str
    detail: str


class InvalidProfileUrl(ApiError):
    def __init__(self, detail: str):
        super().__init__(422, "invalid_profile_url", "Invalid LinkedIn profile URL", detail)


class ScraperAuthenticationRequired(ApiError):
    def __init__(self):
        super().__init__(
            503,
            "linkedin_authentication_required",
            "LinkedIn authentication required",
            "The LinkedIn li_at/JSESSIONID cookies are missing or expired. "
            "Refresh the configured secret values.",
        )


class ProfileNotFound(ApiError):
    def __init__(self):
        super().__init__(
            404,
            "profile_not_found",
            "Profile not found",
            "LinkedIn did not return an accessible profile for this URL.",
        )


class ScrapeFailed(ApiError):
    def __init__(self, detail: str = "LinkedIn could not be read at this time."):
        super().__init__(502, "upstream_scrape_failed", "Upstream scrape failed", detail)


class ScraperBusy(ApiError):
    def __init__(self):
        super().__init__(
            503,
            "scraper_busy",
            "Scraper capacity reached",
            "All LinkedIn request slots are busy. Retry after a short delay.",
        )


class UpstreamRateLimited(ApiError):
    def __init__(self):
        super().__init__(
            429,
            "linkedin_rate_limited",
            "LinkedIn rate limit reached",
            "LinkedIn rejected the request rate. Stop requests and retry later.",
        )


def _problem(error: ApiError):
    body = {
        "type": f"urn:problem:{error.code}",
        "title": error.title,
        "status": error.status,
        "detail": error.detail,
        "instance": request.path,
        "code": error.code,
        "request_id": getattr(g, "request_id", ""),
    }
    response = jsonify(body)
    response.status_code = error.status
    response.content_type = "application/problem+json"
    if error.status == 401:
        response.headers["WWW-Authenticate"] = "Bearer"
    if error.status == 429:
        response.headers["Retry-After"] = "300"
    elif error.status == 503:
        response.headers["Retry-After"] = "10"
    return response


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return _problem(error)

    @app.errorhandler(ValidationError)
    def handle_validation_error(error: ValidationError):
        fields = ", ".join(
            ".".join(str(part) for part in item["loc"]) for item in error.errors()
        )
        return _problem(
            ApiError(400, "invalid_request", "Invalid request", f"Invalid field(s): {fields}.")
        )

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        return _problem(
            ApiError(
                error.code or 500,
                error.name.lower().replace(" ", "_"),
                error.name,
                error.description,
            )
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        app.logger.exception(
            "Unhandled request failure request_id=%s", getattr(g, "request_id", "")
        )
        return _problem(
            ApiError(
                500,
                "internal_server_error",
                "Internal server error",
                "An unexpected error occurred.",
            )
        )
