from __future__ import annotations

from app import create_app


def test_profile_success_and_cache(client, fake_scraper):
    first = client.post(
        "/v1/profiles",
        json={"profile_url": "linkedin.com/in/ada-lovelace/?trk=ignored"},
        headers={"X-Request-ID": "challenge-test"},
    )
    second = client.post(
        "/v1/profiles",
        json={"profile_url": "https://uk.linkedin.com/in/ada-lovelace"},
    )

    assert first.status_code == 200
    assert first.headers["X-Request-ID"] == "challenge-test"
    assert first.headers["Cache-Control"] == "no-store"
    assert first.json["data"]["name"] == "Ada Lovelace"
    assert first.json["data"]["profile_url"] == "https://www.linkedin.com/in/ada-lovelace"
    assert first.json["data"]["skills"] == ["Mathematics", "Algorithms"]
    assert first.json["meta"]["cached"] is False
    assert second.json["meta"]["cached"] is True
    assert fake_scraper.calls == 1


def test_rejects_non_json(client):
    response = client.post("/v1/profiles", data="profile=anything")

    assert response.status_code == 415
    assert response.content_type == "application/problem+json"
    assert response.json["code"] == "unsupported_media_type"


def test_rejects_unknown_request_field(client):
    response = client.post(
        "/v1/profiles",
        json={"profile_url": "linkedin.com/in/ada", "password": "never"},
    )

    assert response.status_code == 400
    assert response.json["code"] == "invalid_request"


def test_rejects_lookalike_domain_before_scrape(client, fake_scraper):
    response = client.post(
        "/v1/profiles", json={"profile_url": "https://linkedin.com.evil.test/in/ada"}
    )

    assert response.status_code == 422
    assert response.json["code"] == "invalid_profile_url"
    assert fake_scraper.calls == 0


def test_api_key_protection(fake_scraper):
    protected = create_app(
        {"TESTING": True, "API_KEY": "top-secret", "LOG_LEVEL": "WARNING"},
        scraper=fake_scraper,
    ).test_client()

    denied = protected.post(
        "/v1/profiles", json={"profile_url": "linkedin.com/in/ada"}
    )
    allowed = protected.post(
        "/v1/profiles",
        json={"profile_url": "linkedin.com/in/ada"},
        headers={"Authorization": "Bearer top-secret"},
    )

    assert denied.status_code == 401
    assert denied.headers["WWW-Authenticate"] == "Bearer"
    assert denied.json["type"] == "urn:problem:unauthorized"
    assert allowed.status_code == 200


def test_health_and_contract_are_public(client):
    ready = client.get("/health/ready")
    contract = client.get("/docs/openapi.yaml")

    assert ready.status_code == 200
    assert ready.json == {
        "status": "ready",
        "scraper": "fake",
        "authenticated_session_configured": True,
    }
    assert contract.status_code == 200
    assert b"openapi: 3.1.0" in contract.data


def test_rate_limit_problem_includes_retry_after(app):
    from app.errors import UpstreamRateLimited

    @app.get("/test-rate-limit")
    def test_rate_limit():
        raise UpstreamRateLimited()

    response = app.test_client().get("/test-rate-limit")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "300"
    assert response.json["code"] == "linkedin_rate_limited"
