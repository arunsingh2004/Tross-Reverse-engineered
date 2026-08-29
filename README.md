# LinkedIn Profile API

A browserless Flask API for the Tross engineering hiring challenge. It accepts a LinkedIn member profile URL and directly calls LinkedIn's reverse-engineered Voyager/Dash HTTP endpoint, then returns normalized profile JSON.

No Playwright, Selenium, Chromium, DOM scraping, HTML parsing, AI model, or model API key is used.

## Assignment fit

The runtime makes this direct request:

```http
GET https://www.linkedin.com/voyager/api/identity/dash/profiles
    ?q=memberIdentity
    &memberIdentity={public_identifier}
    &decorationId=com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-101
```

It authenticates with `li_at` and `JSESSIONID` cookies supplied as environment secrets and requests LinkedIn normalized JSON using Rest.li headers.

## Features

- Pure HTTP reverse-engineered Voyager integration using HTTPX
- No browser in development, tests, Docker, or production
- Persistent pooled HTTP/2 client per Gunicorn worker
- Correct URN-based normalized response graph traversal
- Name, headline, location, about, experience, education, skills, certifications, languages, and image URLs
- Strict LinkedIn URL allow-listing and canonicalization
- Pydantic request/response contracts
- TTL cache, concurrency cap, and conservative upstream pacing
- Immediate stop on LinkedIn `429`; no unsafe retry loop
- Optional API-key protection for the public Flask API
- Problem+JSON errors, request IDs, health endpoints, and OpenAPI 3.1
- Docker, Render blueprint, GitHub Actions, tests, and synthetic Voyager fixture

## Architecture

```text
client -> Flask -> URL validator -> TTL cache -> pacing/concurrency guard
       -> HTTPX -> LinkedIn Voyager endpoint -> URN graph resolver
       -> Pydantic profile -> JSON
```

See [docs/architecture.md](docs/architecture.md) for the complete design and [docs/reverse-engineering.md](docs/reverse-engineering.md) for the endpoint/authentication/response analysis.

## Prerequisites

- Python 3.11 or newer; Python 3.12 recommended
- Your own valid LinkedIn session cookies
- Permission to access and process the requested profile data

This uses an undocumented internal interface. LinkedIn can change it without notice, restrict the account, or prohibit the activity under its terms. Use only for authorized evaluation and review applicable law and privacy obligations before any production use.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

There is no browser dependency to install.

## Configure LinkedIn cookies

The direct endpoint requires two values from your own authenticated LinkedIn session:

```dotenv
LINKEDIN_LI_AT=replace-with-li_at-value
LINKEDIN_JSESSIONID=ajax:replace-with-value
```

You can copy these once from an existing logged-in browser's developer tools under Application/Storage -> Cookies -> `https://www.linkedin.com`. The application itself never launches or controls that browser. Treat `li_at` like a password.

Do not commit `.env`, paste cookie values into source code, include them in screenshots, or store live Voyager responses in test fixtures.

Validate the cookies through a direct HTTP call:

```bash
python scripts/validate_session.py
```

Expected shape:

```json
{"status": "ok", "included_entities": 2}
```

## Run locally

```bash
source .venv/bin/activate
flask --app wsgi:app run --debug --port 8000
```

Readiness:

```bash
curl http://localhost:8000/health/ready
```

Expected:

```json
{
  "authenticated_session_configured": true,
  "scraper": "voyager_http",
  "status": "ready"
}
```

## API request

`API_KEY` can remain empty locally. It protects your service when deployed publicly; it is not an AI/model key.

```bash
curl --request POST http://localhost:8000/v1/profiles \
  --header 'Content-Type: application/json' \
  --data '{"profile_url":"https://www.linkedin.com/in/example-person"}'
```

When `API_KEY` is configured:

```bash
curl --request POST https://your-service.example.com/v1/profiles \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer your-service-api-key' \
  --data '{"profile_url":"https://www.linkedin.com/in/example-person"}'
```

Example response:

```json
{
  "data": {
    "profile_url": "https://www.linkedin.com/in/example-person",
    "public_identifier": "example-person",
    "name": "Example Person",
    "headline": "Staff Software Engineer",
    "location": "Bengaluru, India",
    "about": "I build reliable systems.",
    "profile_image_url": "https://media.licdn.com/...",
    "background_image_url": null,
    "follower_count": 1200,
    "connection_count": 500,
    "experience": [],
    "education": [],
    "skills": ["Python", "System Design"],
    "certifications": [],
    "languages": []
  },
  "meta": {
    "request_id": "f4c9a39c-4bd0-4ac1-a9b6-76c42fd6a3aa",
    "scraped_at": "2026-08-29T10:00:00Z",
    "source": "linkedin_voyager_api",
    "cached": false,
    "partial": false,
    "warnings": []
  }
}
```

The complete contract is [docs/openapi.yaml](docs/openapi.yaml), also served at `/docs/openapi.yaml`.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `API_KEY` | empty | Optional protection for public `/v1/*` endpoints |
| `CACHE_TTL_SECONDS` | `900` | Successful result cache TTL; `0` disables |
| `MAX_CONCURRENT_REQUESTS` | `4` | Direct LinkedIn request slots per process |
| `REQUEST_ACQUIRE_TIMEOUT_SECONDS` | `5` | Capacity wait before `503` |
| `HTTP_TIMEOUT_SECONDS` | `20` | Direct endpoint timeout |
| `MIN_UPSTREAM_INTERVAL_SECONDS` | `0.6` | Minimum delay between upstream requests per process |
| `LINKEDIN_LI_AT` | empty | Required authenticated session cookie secret |
| `LINKEDIN_JSESSIONID` | empty | Required CSRF/session cookie secret |
| `LINKEDIN_USER_AGENT` | Chrome-like | HTTP User-Agent; keep aligned with the session origin |
| `LINKEDIN_VOYAGER_BASE_URL` | LinkedIn Voyager URL | Transport base URL; configurable for tests only |
| `LINKEDIN_CA_BUNDLE` | empty | Optional organization/custom CA PEM file |

### TLS certificate troubleshooting

The HTTP client uses the operating system's native certificate store through `truststore`. This is important on managed macOS systems where organization certificates are installed in Keychain but are not present in Python's static CA bundle.

If validation still reports `CERTIFICATE_VERIFY_FAILED`, ask your IT/network administrator for the organization CA certificate as a PEM bundle and configure:

```dotenv
LINKEDIN_CA_BUNDLE=/absolute/path/to/organization-ca.pem
```

Do not disable TLS verification and do not add `verify=False`; that would expose LinkedIn session cookies to interception.

## Errors

| Status | Code | Meaning |
|---:|---|---|
| 400 | `invalid_request` | Bad JSON or unexpected fields |
| 401 | `unauthorized` | Optional service API key missing/invalid |
| 404 | `profile_not_found` | Requested profile was not returned |
| 415 | `unsupported_media_type` | Body is not JSON |
| 422 | `invalid_profile_url` | Not an allowed LinkedIn `/in/` URL |
| 429 | `linkedin_rate_limited` | Stop calls and retry substantially later |
| 502 | `upstream_scrape_failed` | Transport, LinkedIn, or response-schema failure |
| 503 | `linkedin_authentication_required` | Cookies missing or expired |
| 503 | `scraper_busy` | Local concurrency capacity exhausted |

## Tests

```bash
pytest -q
ruff check .
```

Tests use `httpx.MockTransport` and a synthetic normalized Voyager response. They verify the exact path, query parameters, cookies, CSRF header, Rest.li version, graph traversal, unrelated-entity isolation, URL security, caching, authentication errors, and rate-limit behavior without contacting LinkedIn.

## Production server

```bash
gunicorn --config gunicorn.conf.py wsgi:app
```

The included Docker image contains only Python and HTTP dependencies; it does not install Chromium.

```bash
docker build -t linkedin-profile-api .
docker run --rm -p 8000:8000 \
  -e API_KEY='long-random-service-secret' \
  -e LINKEDIN_LI_AT='linkedin-session-secret' \
  -e LINKEDIN_JSESSIONID='ajax:csrf-value' \
  linkedin-profile-api
```

## Deploy publicly over HTTPS

The repository includes `render.yaml`:

1. Push the source to a public GitHub repository, confirming `.env` is absent.
2. Create a Render Blueprint from the repository.
3. Add `API_KEY`, `LINKEDIN_LI_AT`, and `LINKEDIN_JSESSIONID` as secrets.
4. Deploy and wait for `/health/ready`.
5. Test one profile you are authorized to access.
6. Confirm the endpoint works over the generated HTTPS URL.

Render terminates HTTPS at the platform edge and forwards traffic to Gunicorn inside the container.

## Design decisions

- **One decorated HTTP call:** minimizes upstream traffic and latency while returning the full normalized entity graph.
- **URN traversal:** follows ownership references instead of collecting every entity by type, preventing unrelated positions from leaking into a result.
- **No automatic `429` retry:** repeated retries can worsen restrictions; the caller receives a clear signal to stop.
- **Pooled HTTP client:** reuses connections without maintaining a browser process.
- **Cookie-only backend authentication:** no password or MFA automation and no credential endpoint.
- **Stable public schema:** internal LinkedIn response drift remains isolated inside the Voyager adapter.

## Known limitations

- Voyager/Dash is undocumented and may change its endpoint, decoration ID, response graph, or authentication behavior.
- Cookies expire and can trigger checkpoints or account restrictions.
- Results depend on the visibility available to the authenticated account.
- Some fields may be absent from the selected decoration or hidden by the member.
- Internal TLS/HTTP fingerprints differ from a normal browser and can be detected.
- The TTL cache, pacing clock, and concurrency guard are per Gunicorn process, not distributed.
- The in-memory cache is not size-bounded; Redis or a bounded TTL cache is recommended for sustained public traffic.
- Live responses contain personal data and must not be committed or retained without a defined purpose and policy.

## Repository layout

```text
app/
  api.py                         HTTP endpoints
  config.py                      environment settings
  errors.py                      problem+json errors
  models.py                      public schema
  services/profile_service.py    URL validation and cache
  scrapers/voyager.py            direct HTTP client and graph parser
docs/
  architecture.md                system design
  reverse-engineering.md         endpoint and response analysis
  openapi.yaml                   API contract
scripts/validate_session.py      direct /voyager/api/me check
tests/
  fixtures/voyager_profile.json  synthetic normalized response
  test_voyager.py                direct transport/parser tests
Dockerfile                       browserless deployment image
render.yaml                      HTTPS hosting blueprint
```

## Submission checklist

- [ ] `pytest -q` and `ruff check .` pass
- [ ] Repository contains no Playwright, Selenium, Chromium, or browser setup
- [ ] Repository contains no cookies, `.env`, or live response captures
- [ ] `python scripts/validate_session.py` succeeds
- [ ] Public HTTPS endpoint returns a real authorized profile
- [ ] `meta.source` is `linkedin_voyager_api`
- [ ] Public GitHub repository and API URL work for the reviewer
