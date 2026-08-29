from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from app.errors import InvalidProfileUrl
from app.models import Profile
from app.scrapers.base import ProfileScraper, ScrapeResult

_PROFILE_PATH = re.compile(r"^/in/([A-Za-z0-9%._~-]+)/?$")


@dataclass
class ServiceResult:
    profile: Profile
    warnings: list[str]
    scraped_at: datetime
    cached: bool


@dataclass
class _CacheEntry:
    result: ServiceResult
    expires_at: float


def normalize_linkedin_profile_url(raw_url: str) -> tuple[str, str]:
    """Validate a LinkedIn /in/ URL and return (canonical URL, public id)."""
    value = raw_url.strip()
    if not value:
        raise InvalidProfileUrl("profile_url cannot be empty.")
    if "://" not in value:
        value = f"https://{value}"

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise InvalidProfileUrl("The URL is malformed.") from exc

    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme.lower() not in {"http", "https"}:
        raise InvalidProfileUrl("Only http and https URLs are accepted.")
    if parsed.username or parsed.password or port not in {None, 80, 443}:
        raise InvalidProfileUrl("Credentials and custom ports are not allowed in the URL.")
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        raise InvalidProfileUrl("The host must be linkedin.com or one of its subdomains.")

    match = _PROFILE_PATH.fullmatch(parsed.path)
    if not match:
        raise InvalidProfileUrl("Expected a LinkedIn profile path like /in/public-identifier.")

    public_id = unquote(match.group(1)).strip()
    if public_id in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._~-]+", public_id):
        raise InvalidProfileUrl("The LinkedIn public identifier is invalid.")

    canonical_path = f"/in/{quote(public_id, safe='._~-')}"
    canonical = urlunsplit(("https", "www.linkedin.com", canonical_path, "", ""))
    return canonical, public_id


class ProfileService:
    def __init__(self, *, scraper: ProfileScraper, cache_ttl_seconds: int):
        self._scraper = scraper
        self._cache_ttl = max(cache_ttl_seconds, 0)
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    @property
    def scraper_name(self) -> str:
        return self._scraper.name

    @property
    def session_configured(self) -> bool:
        return self._scraper.session_configured

    def fetch(self, raw_url: str) -> ServiceResult:
        canonical_url, public_id = normalize_linkedin_profile_url(raw_url)
        now = time.monotonic()

        with self._lock:
            cached = self._cache.get(canonical_url)
            if cached and cached.expires_at > now:
                result = cached.result
                return ServiceResult(
                    profile=result.profile.model_copy(deep=True),
                    warnings=list(result.warnings),
                    scraped_at=result.scraped_at,
                    cached=True,
                )
            if cached:
                self._cache.pop(canonical_url, None)

        scraped: ScrapeResult = self._scraper.scrape(canonical_url, public_id)
        result = ServiceResult(
            profile=scraped.profile,
            warnings=list(scraped.warnings),
            scraped_at=datetime.now(UTC),
            cached=False,
        )
        if self._cache_ttl:
            with self._lock:
                self._cache[canonical_url] = _CacheEntry(
                    result=result,
                    expires_at=time.monotonic() + self._cache_ttl,
                )
        return result
