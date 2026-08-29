from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.errors import ScraperAuthenticationRequired, UpstreamRateLimited
from app.scrapers.voyager import LinkedInVoyagerScraper, parse_profile_response

FIXTURE = Path(__file__).parent / "fixtures" / "voyager_profile.json"


def load_payload() -> dict:
    return json.loads(FIXTURE.read_text())


def make_scraper(handler, *, li_at="session-token", jsessionid='"ajax:123"'):
    return LinkedInVoyagerScraper(
        li_at=li_at,
        jsessionid=jsessionid,
        user_agent="test-agent",
        base_url="https://www.linkedin.com/voyager/api",
        timeout_seconds=2,
        max_concurrent_requests=1,
        acquire_timeout_seconds=0.1,
        min_upstream_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )


def test_parses_normalized_graph_without_leaking_unrelated_entities():
    profile = parse_profile_response(
        load_payload(),
        "https://www.linkedin.com/in/ada-lovelace",
        "ada-lovelace",
    )

    assert profile.name == "Ada Lovelace"
    assert profile.headline == "Computing pioneer"
    assert profile.location == "London, United Kingdom"
    assert profile.about == "Mathematician & writer."
    assert profile.profile_image_url == "https://media.licdn.com/large.jpg"
    assert profile.follower_count == 12_300
    assert [item.title for item in profile.experience] == ["Analyst"]
    assert profile.experience[0].company == "Independent"
    assert profile.experience[0].start_date == "1842-01"
    assert profile.education[0].field_of_study == "Computation"
    assert profile.skills == ["Mathematics", "Algorithms"]
    assert profile.certifications[0].credential_id == "ABC-123"
    assert profile.languages[0].proficiency == "Native Or Bilingual"


def test_direct_request_uses_voyager_endpoint_headers_and_query():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/voyager/api/identity/dash/profiles"
        assert request.url.params["q"] == "memberIdentity"
        assert request.url.params["memberIdentity"] == "ada-lovelace"
        assert "FullProfileWithEntities-101" in request.url.params["decorationId"]
        assert request.headers["csrf-token"] == "ajax:123"
        assert request.headers["x-restli-protocol-version"] == "2.0.0"
        assert "li_at=session-token" in request.headers["cookie"]
        assert 'JSESSIONID="ajax:123"' in request.headers["cookie"]
        return httpx.Response(200, json=load_payload())

    result = make_scraper(handler).scrape(
        "https://www.linkedin.com/in/ada-lovelace", "ada-lovelace"
    )

    assert result.profile.name == "Ada Lovelace"
    assert result.warnings == []


@pytest.mark.parametrize("status", [401, 403])
def test_maps_authentication_failures(status):
    scraper = make_scraper(lambda request: httpx.Response(status))

    with pytest.raises(ScraperAuthenticationRequired):
        scraper.scrape("https://www.linkedin.com/in/ada", "ada")


def test_requires_both_session_cookies_without_making_request():
    called = False

    def handler(request):
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    scraper = make_scraper(handler, jsessionid="")
    with pytest.raises(ScraperAuthenticationRequired):
        scraper.scrape("https://www.linkedin.com/in/ada", "ada")
    assert called is False


def test_does_not_retry_rate_limits():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(429)

    with pytest.raises(UpstreamRateLimited):
        make_scraper(handler).scrape("https://www.linkedin.com/in/ada", "ada")
    assert calls == 1


def test_session_validation_uses_direct_me_endpoint():
    def handler(request):
        assert request.url.path == "/voyager/api/me"
        return httpx.Response(200, json={"data": {}, "included": [{}, {}]})

    assert make_scraper(handler).validate_session() == 2
