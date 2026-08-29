from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.models import Profile


@dataclass
class ScrapeResult:
    profile: Profile
    warnings: list[str]


class ProfileScraper(Protocol):
    name: str
    session_configured: bool

    def scrape(self, profile_url: str, public_id: str) -> ScrapeResult: ...

