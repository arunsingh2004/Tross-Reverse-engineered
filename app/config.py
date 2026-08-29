from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    log_level: str = "INFO"
    api_key: str = ""
    cache_ttl_seconds: int = 900
    max_concurrent_requests: int = 4
    request_acquire_timeout_seconds: float = 5.0
    http_timeout_seconds: float = 20.0
    min_upstream_interval_seconds: float = 0.6
    linkedin_li_at: str = ""
    linkedin_jsessionid: str = ""
    linkedin_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    )
    linkedin_voyager_base_url: str = "https://www.linkedin.com/voyager/api"
    linkedin_ca_bundle: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            api_key=os.getenv("API_KEY", ""),
            cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "900")),
            max_concurrent_requests=int(os.getenv("MAX_CONCURRENT_REQUESTS", "4")),
            request_acquire_timeout_seconds=float(
                os.getenv("REQUEST_ACQUIRE_TIMEOUT_SECONDS", "5")
            ),
            http_timeout_seconds=float(os.getenv("HTTP_TIMEOUT_SECONDS", "20")),
            min_upstream_interval_seconds=float(
                os.getenv("MIN_UPSTREAM_INTERVAL_SECONDS", "0.6")
            ),
            linkedin_li_at=os.getenv("LINKEDIN_LI_AT", ""),
            linkedin_jsessionid=os.getenv("LINKEDIN_JSESSIONID", ""),
            linkedin_user_agent=os.getenv("LINKEDIN_USER_AGENT", cls.linkedin_user_agent),
            linkedin_voyager_base_url=os.getenv(
                "LINKEDIN_VOYAGER_BASE_URL", cls.linkedin_voyager_base_url
            ),
            linkedin_ca_bundle=os.getenv("LINKEDIN_CA_BUNDLE", ""),
        )

    def to_flask_config(self) -> dict[str, Any]:
        return {key.upper(): value for key, value in asdict(self).items()}
