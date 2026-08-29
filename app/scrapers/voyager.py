from __future__ import annotations

import html
import logging
import re
import ssl
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
import truststore

from app.errors import (
    ProfileNotFound,
    ScrapeFailed,
    ScraperAuthenticationRequired,
    ScraperBusy,
    UpstreamRateLimited,
)
from app.models import Certification, Education, Experience, Language, Profile
from app.scrapers.base import ScrapeResult

logger = logging.getLogger(__name__)

_PROFILE_ENDPOINT = "/identity/dash/profiles"
_FULL_PROFILE_DECORATION = (
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-101"
)
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def _ssl_context(ca_bundle: str = "") -> ssl.SSLContext:
    """Use an explicit CA bundle or the operating system's native trust store."""
    if ca_bundle:
        bundle = Path(ca_bundle).expanduser()
        if not bundle.is_file():
            raise ValueError(f"LINKEDIN_CA_BUNDLE does not exist: {bundle}")
        return ssl.create_default_context(cafile=str(bundle))
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _text(value: Any) -> str | None:
    """Unwrap plain strings and LinkedIn AttributedText/localized values."""
    if isinstance(value, str):
        cleaned = html.unescape(re.sub(r"\s+", " ", value)).strip()
        return cleaned or None
    if not isinstance(value, dict):
        return None
    for key in ("text", "defaultLocalizedName", "localizedName", "name", "value"):
        result = _text(value.get(key))
        if result:
            return result
    for key in ("localized", "multiLocaleText"):
        localized = value.get(key)
        if isinstance(localized, dict):
            for locale in ("en_US", "en_GB"):
                result = _text(localized.get(locale))
                if result:
                    return result
            for candidate in localized.values():
                result = _text(candidate)
                if result:
                    return result
    return None


def _date(value: Any) -> str | None:
    if not isinstance(value, dict) or not value.get("year"):
        return None
    year = int(value["year"])
    month = value.get("month")
    return f"{year:04d}-{int(month):02d}" if month else f"{year:04d}"


def _date_range(entity: dict[str, Any]) -> tuple[str | None, str | None]:
    value = entity.get("dateRange") or entity.get("timePeriod") or {}
    if not isinstance(value, dict):
        return None, None
    start = _date(value.get("start"))
    end = _date(value.get("end"))
    return start, end or ("present" if start else None)


def _image_url(value: Any) -> str | None:
    """Find the largest URL in a nested LinkedIn VectorImage object."""
    if not isinstance(value, dict):
        return _text(value) if isinstance(value, str) and value.startswith("http") else None
    root_url = value.get("rootUrl")
    artifacts = value.get("artifacts")
    if isinstance(root_url, str) and isinstance(artifacts, list) and artifacts:
        usable = [artifact for artifact in artifacts if isinstance(artifact, dict)]
        if usable:
            largest = max(
                usable,
                key=lambda item: int(item.get("width", 0)) * int(item.get("height", 0)),
            )
            segment = largest.get("fileIdentifyingUrlPathSegment")
            if isinstance(segment, str):
                return f"{root_url}{segment}"
    for child in value.values():
        result = _image_url(child)
        if result:
            return result
    return None


class VoyagerGraph:
    """Resolve LinkedIn normalized JSON references through included[]."""

    def __init__(self, payload: dict[str, Any]):
        included = payload.get("included") or []
        self.index: dict[str, dict[str, Any]] = {
            entity["entityUrn"]: entity
            for entity in included
            if isinstance(entity, dict) and isinstance(entity.get("entityUrn"), str)
        }

    def resolve(self, value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return None
        entity = self.index.get(value)
        if entity:
            return entity
        aliases = (
            value.replace(":collectionResponse:", ":fsd_collectionResponse:"),
            value.replace(":fsd_collectionResponse:", ":collectionResponse:"),
        )
        return next((self.index[item] for item in aliases if item in self.index), None)

    def collection(self, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            values = value
        else:
            resolved = self.resolve(value)
            if not resolved:
                return []
            values = resolved.get("*elements") or resolved.get("elements") or []
        output: list[dict[str, Any]] = []
        for item in values:
            resolved_item = self.resolve(item)
            if resolved_item:
                output.append(resolved_item)
        return output

    def profile_collection(
        self, profile: dict[str, Any], keys: Iterable[str]
    ) -> list[dict[str, Any]]:
        for key in keys:
            if key in profile:
                return self.collection(profile[key])
        return []


def _target_profile(payload: dict[str, Any], graph: VoyagerGraph) -> dict[str, Any]:
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise ScrapeFailed("LinkedIn returned an invalid normalized response.")
    refs = data.get("*elements") or data.get("elements") or []
    if not refs:
        nested = data.get("identityDashProfilesByMemberIdentity") or {}
        refs = nested.get("*elements") or nested.get("elements") or []
    if not refs:
        raise ProfileNotFound()
    profile = graph.resolve(refs[0])
    if not profile:
        raise ScrapeFailed("LinkedIn returned a profile reference without its entity.")
    return profile


def _location(profile: dict[str, Any], graph: VoyagerGraph) -> str | None:
    direct = _text(profile.get("locationName")) or _text(profile.get("geoLocationName"))
    if direct:
        return direct
    geo = profile.get("geoLocation") or {}
    geo_ref = geo.get("geoUrn") if isinstance(geo, dict) else None
    geo_entity = graph.resolve(geo_ref or profile.get("*geoLocation"))
    return _text(geo_entity) if geo_entity else None


def _position_entities(
    profile: dict[str, Any], graph: VoyagerGraph
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    groups = graph.profile_collection(
        profile, ("*profilePositionGroups", "profilePositionGroups")
    )
    for group in groups:
        positions = graph.profile_collection(
            group,
            (
                "*profilePositionInPositionGroup",
                "profilePositionInPositionGroup",
                "*profilePositions",
            ),
        )
        pairs.extend((position, group) for position in positions)
    if not pairs:
        direct = graph.profile_collection(
            profile, ("*profilePositions", "profilePositions")
        )
        pairs.extend((position, {}) for position in direct)
    return pairs


def _experience(profile: dict[str, Any], graph: VoyagerGraph) -> list[Experience]:
    items: list[Experience] = []
    seen: set[str] = set()
    for position, group in _position_entities(profile, graph):
        urn = str(position.get("entityUrn") or "")
        if urn and urn in seen:
            continue
        if urn:
            seen.add(urn)
        title = _text(position.get("title"))
        if not title:
            continue
        company = _text(position.get("companyName")) or _text(group.get("companyName"))
        if not company:
            company_entity = graph.resolve(position.get("*company") or group.get("*company"))
            company = _text(company_entity) if company_entity else None
        start, end = _date_range(position)
        position_skills = graph.profile_collection(
            position, ("*skills", "*profileSkills", "skills")
        )
        skills = [name for item in position_skills if (name := _text(item.get("name")))]
        items.append(
            Experience(
                title=title,
                company=company,
                employment_type=_text(position.get("employmentType")),
                location=_text(position.get("locationName"))
                or _text(position.get("geoLocationName")),
                start_date=start,
                end_date=end,
                description=_text(position.get("description")),
                skills=skills,
            )
        )
    items.sort(key=lambda item: item.start_date or "", reverse=True)
    return items


def _education(profile: dict[str, Any], graph: VoyagerGraph) -> list[Education]:
    entities = graph.profile_collection(
        profile, ("*profileEducations", "profileEducations", "*educations")
    )
    items: list[Education] = []
    for entity in entities:
        school = _text(entity.get("schoolName"))
        if not school:
            school_entity = graph.resolve(entity.get("*school"))
            school = _text(school_entity) if school_entity else None
        if not school:
            continue
        start, end = _date_range(entity)
        items.append(
            Education(
                school=school,
                degree=_text(entity.get("degreeName")),
                field_of_study=_text(entity.get("fieldOfStudy")),
                start_year=start,
                end_year=end,
                grade=_text(entity.get("grade")),
                description=_text(entity.get("description"))
                or _text(entity.get("activities")),
            )
        )
    items.sort(key=lambda item: item.start_year or "", reverse=True)
    return items


def _skills(profile: dict[str, Any], graph: VoyagerGraph) -> list[str]:
    entities = graph.profile_collection(
        profile, ("*profileSkills", "profileSkills", "*skills")
    )
    output: list[str] = []
    for entity in entities:
        name = _text(entity.get("name")) or _text(entity.get("skill"))
        if name and name not in output:
            output.append(name)
    return output


def _certifications(profile: dict[str, Any], graph: VoyagerGraph) -> list[Certification]:
    entities = graph.profile_collection(
        profile,
        ("*profileCertifications", "profileCertifications", "*certifications"),
    )
    output: list[Certification] = []
    for entity in entities:
        name = _text(entity.get("name"))
        if not name:
            continue
        start, end = _date_range(entity)
        output.append(
            Certification(
                name=name,
                issuer=_text(entity.get("authority")) or _text(entity.get("issuer")),
                issue_date=start,
                expiration_date=None if end == "present" else end,
                credential_id=_text(entity.get("licenseNumber"))
                or _text(entity.get("credentialId")),
                credential_url=_text(entity.get("url")),
            )
        )
    return output


def _languages(profile: dict[str, Any], graph: VoyagerGraph) -> list[Language]:
    entities = graph.profile_collection(
        profile, ("*profileLanguages", "profileLanguages", "*languages")
    )
    output: list[Language] = []
    for entity in entities:
        name = _text(entity.get("name"))
        if not name:
            continue
        proficiency = _text(entity.get("proficiency"))
        if proficiency:
            proficiency = proficiency.replace("_", " ").title()
        output.append(Language(name=name, proficiency=proficiency))
    return output


def parse_profile_response(
    payload: dict[str, Any], profile_url: str, public_id: str
) -> Profile:
    graph = VoyagerGraph(payload)
    raw_profile = _target_profile(payload, graph)
    first_name = _text(raw_profile.get("firstName")) or ""
    last_name = _text(raw_profile.get("lastName")) or ""
    name = f"{first_name} {last_name}".strip()
    if not name:
        name = _text(raw_profile.get("name")) or ""
    if not name:
        raise ScrapeFailed("LinkedIn returned a profile without a name.")

    return Profile(
        profile_url=profile_url,
        public_identifier=_text(raw_profile.get("publicIdentifier")) or public_id,
        name=name,
        headline=_text(raw_profile.get("headline")),
        location=_location(raw_profile, graph),
        about=_text(raw_profile.get("summary")),
        profile_image_url=_image_url(
            raw_profile.get("profilePicture") or raw_profile.get("picture")
        ),
        background_image_url=_image_url(
            raw_profile.get("backgroundPicture") or raw_profile.get("backgroundImage")
        ),
        follower_count=raw_profile.get("followerCount"),
        connection_count=raw_profile.get("connectionCount")
        or raw_profile.get("connectionsCount"),
        experience=_experience(raw_profile, graph),
        education=_education(raw_profile, graph),
        skills=_skills(raw_profile, graph),
        certifications=_certifications(raw_profile, graph),
        languages=_languages(raw_profile, graph),
    )


class LinkedInVoyagerScraper:
    name = "voyager_http"

    def __init__(
        self,
        *,
        li_at: str,
        jsessionid: str,
        user_agent: str,
        base_url: str,
        timeout_seconds: float,
        max_concurrent_requests: int,
        acquire_timeout_seconds: float,
        min_upstream_interval_seconds: float,
        ca_bundle: str = "",
        transport: httpx.BaseTransport | None = None,
    ):
        self.li_at = self._validate_secret(li_at, "LINKEDIN_LI_AT")
        self.jsessionid = self._validate_secret(jsessionid, "LINKEDIN_JSESSIONID")
        self.acquire_timeout_seconds = acquire_timeout_seconds
        self.min_upstream_interval_seconds = max(0.0, min_upstream_interval_seconds)
        self._capacity = threading.BoundedSemaphore(max(1, max_concurrent_requests))
        self._pace_lock = threading.Lock()
        self._last_request_at = 0.0
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            http2=True,
            transport=transport,
            verify=_ssl_context(ca_bundle),
            headers={
                "accept": "application/vnd.linkedin.normalized+json+2.1",
                "accept-language": "en-US,en;q=0.9",
                "csrf-token": self.jsessionid.strip('"'),
                "user-agent": user_agent,
                "x-li-lang": "en_US",
                "x-restli-protocol-version": "2.0.0",
                "cookie": self._cookie_header(),
            },
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> LinkedInVoyagerScraper:
        return cls(
            li_at=str(config.get("LINKEDIN_LI_AT") or ""),
            jsessionid=str(config.get("LINKEDIN_JSESSIONID") or ""),
            user_agent=str(config["LINKEDIN_USER_AGENT"]),
            base_url=str(config["LINKEDIN_VOYAGER_BASE_URL"]),
            timeout_seconds=float(config["HTTP_TIMEOUT_SECONDS"]),
            max_concurrent_requests=int(config["MAX_CONCURRENT_REQUESTS"]),
            acquire_timeout_seconds=float(config["REQUEST_ACQUIRE_TIMEOUT_SECONDS"]),
            min_upstream_interval_seconds=float(config["MIN_UPSTREAM_INTERVAL_SECONDS"]),
            ca_bundle=str(config.get("LINKEDIN_CA_BUNDLE") or ""),
        )

    @staticmethod
    def _validate_secret(value: str, name: str) -> str:
        cleaned = value.strip()
        if _CONTROL_CHARACTERS.search(cleaned) or ";" in cleaned:
            raise ValueError(f"{name} contains unsafe characters")
        return cleaned

    @property
    def session_configured(self) -> bool:
        return bool(self.li_at and self.jsessionid)

    def _cookie_header(self) -> str:
        jsessionid = self.jsessionid
        if jsessionid and not (jsessionid.startswith('"') and jsessionid.endswith('"')):
            jsessionid = f'"{jsessionid}"'
        return f"li_at={self.li_at}; JSESSIONID={jsessionid}"

    def _pace(self) -> None:
        with self._pace_lock:
            remaining = self.min_upstream_interval_seconds - (
                time.monotonic() - self._last_request_at
            )
            if remaining > 0:
                time.sleep(remaining)
            self._last_request_at = time.monotonic()

    def validate_session(self) -> int:
        """Validate cookies with a direct /me request without exposing profile data."""
        if not self.session_configured:
            raise ScraperAuthenticationRequired()
        self._pace()
        try:
            payload = self._decode_response(self._client.get("/me"))
        except httpx.TimeoutException as exc:
            raise ScrapeFailed("LinkedIn did not respond before the HTTP timeout.") from exc
        except httpx.HTTPError as exc:
            raise ScrapeFailed("The direct LinkedIn session check failed.") from exc
        return len(payload.get("included") or [])

    def scrape(self, profile_url: str, public_id: str) -> ScrapeResult:
        if not self.session_configured:
            raise ScraperAuthenticationRequired()
        if not self._capacity.acquire(timeout=self.acquire_timeout_seconds):
            raise ScraperBusy()
        try:
            self._pace()
            response = self._client.get(
                _PROFILE_ENDPOINT,
                params={
                    "q": "memberIdentity",
                    "memberIdentity": public_id,
                    "decorationId": _FULL_PROFILE_DECORATION,
                },
            )
            payload = self._decode_response(response)
            profile = parse_profile_response(payload, profile_url, public_id)
            return ScrapeResult(profile=profile, warnings=[])
        except httpx.TimeoutException as exc:
            raise ScrapeFailed("LinkedIn did not respond before the HTTP timeout.") from exc
        except httpx.HTTPError as exc:
            logger.warning("Voyager request failed error_type=%s", type(exc).__name__)
            raise ScrapeFailed("The direct LinkedIn request failed.") from exc
        finally:
            self._capacity.release()

    @staticmethod
    def _decode_response(response: httpx.Response) -> dict[str, Any]:
        if response.status_code in {401, 403}:
            raise ScraperAuthenticationRequired()
        if response.status_code == 404:
            raise ProfileNotFound()
        if response.status_code == 429:
            raise UpstreamRateLimited()
        if response.status_code >= 500:
            raise ScrapeFailed(f"LinkedIn returned HTTP {response.status_code}.")
        if response.status_code >= 400:
            raise ScrapeFailed(f"LinkedIn rejected the request with HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            content_type = response.headers.get("content-type", "")
            if "text/html" in content_type:
                raise ScraperAuthenticationRequired() from exc
            raise ScrapeFailed("LinkedIn returned a non-JSON response.") from exc
        if not isinstance(payload, dict):
            raise ScrapeFailed("LinkedIn returned an invalid JSON response.")
        data = payload.get("data") or {}
        embedded_status = data.get("status") if isinstance(data, dict) else None
        if embedded_status in {401, 403}:
            raise ScraperAuthenticationRequired()
        if embedded_status == 404:
            raise ProfileNotFound()
        if embedded_status == 429:
            raise UpstreamRateLimited()
        if embedded_status and int(embedded_status) >= 400:
            raise ScrapeFailed(f"LinkedIn returned embedded status {embedded_status}.")
        return payload
