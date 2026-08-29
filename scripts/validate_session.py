from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.scrapers.voyager import LinkedInVoyagerScraper  # noqa: E402


def main() -> None:
    settings = Settings.from_env()
    scraper = LinkedInVoyagerScraper(
        li_at=settings.linkedin_li_at,
        jsessionid=settings.linkedin_jsessionid,
        user_agent=settings.linkedin_user_agent,
        base_url=settings.linkedin_voyager_base_url,
        timeout_seconds=settings.http_timeout_seconds,
        max_concurrent_requests=1,
        acquire_timeout_seconds=settings.request_acquire_timeout_seconds,
        min_upstream_interval_seconds=0,
        ca_bundle=settings.linkedin_ca_bundle,
    )
    if not scraper.session_configured:
        raise SystemExit("Set LINKEDIN_LI_AT and LINKEDIN_JSESSIONID in .env first.")
    included_entities = scraper.validate_session()
    print(json.dumps({"status": "ok", "included_entities": included_entities}))


if __name__ == "__main__":
    main()
