from __future__ import annotations

import pytest

from app.errors import InvalidProfileUrl
from app.services.profile_service import normalize_linkedin_profile_url


@pytest.mark.parametrize(
    ("value", "expected_id"),
    [
        ("linkedin.com/in/ada-lovelace", "ada-lovelace"),
        ("https://www.linkedin.com/in/ada.lovelace/", "ada.lovelace"),
        ("http://in.linkedin.com/in/ada_lovelace?trk=public", "ada_lovelace"),
    ],
)
def test_normalizes_supported_profile_urls(value, expected_id):
    url, public_id = normalize_linkedin_profile_url(value)

    assert url == f"https://www.linkedin.com/in/{expected_id}"
    assert public_id == expected_id


@pytest.mark.parametrize(
    "value",
    [
        "",
        "javascript:alert(1)",
        "https://example.com/in/ada",
        "https://notlinkedin.com/in/ada",
        "https://linkedin.com.evil.test/in/ada",
        "https://linkedin.com:444/in/ada",
        "https://user:pass@linkedin.com/in/ada",
        "https://linkedin.com/company/openai",
        "https://linkedin.com/in/ada/details/experience",
        "https://linkedin.com/in/ada%2Fadmin",
        "https://linkedin.com/in/%2e%2e",
        "https://linkedin.com/in/ada%20lovelace",
    ],
)
def test_rejects_unsafe_or_unsupported_urls(value):
    with pytest.raises(InvalidProfileUrl):
        normalize_linkedin_profile_url(value)
