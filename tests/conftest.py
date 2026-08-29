from __future__ import annotations

import pytest

from app import create_app
from app.models import (
    Certification,
    Education,
    Experience,
    Language,
    Profile,
)
from app.scrapers.base import ScrapeResult


class FakeScraper:
    name = "fake"
    session_configured = True

    def __init__(self):
        self.calls = 0

    def scrape(self, profile_url: str, public_id: str) -> ScrapeResult:
        self.calls += 1
        return ScrapeResult(
            profile=Profile(
                profile_url=profile_url,
                public_identifier=public_id,
                name="Ada Lovelace",
                headline="Computing pioneer",
                location="London, United Kingdom",
                about="Mathematician and writer.",
                profile_image_url="https://media.licdn.com/example.jpg",
                background_image_url=None,
                follower_count=12_300,
                connection_count=500,
                experience=[
                    Experience(
                        title="Analyst",
                        company="Independent",
                        start_date="Jan 1842",
                        end_date="Dec 1843",
                    )
                ],
                education=[Education(school="Self-directed")],
                skills=["Mathematics", "Algorithms"],
                certifications=[Certification(name="Example credential")],
                languages=[Language(name="English", proficiency="Native")],
            ),
            warnings=[],
        )


@pytest.fixture
def fake_scraper():
    return FakeScraper()


@pytest.fixture
def app(fake_scraper):
    return create_app(
        {
            "TESTING": True,
            "API_KEY": "",
            "CACHE_TTL_SECONDS": 60,
            "LOG_LEVEL": "WARNING",
        },
        scraper=fake_scraper,
    )


@pytest.fixture
def client(app):
    return app.test_client()

