# Reverse-engineering notes

## Why Voyager/Dash

LinkedIn's website uses internal Voyager endpoints and normalized Rest.li responses. The older `/identity/profiles/{id}/profileView` endpoint is now reported as `410 Gone`, so this project uses the current Dash profile collection endpoint with a full-profile decoration.

## Request contract

```http
GET /voyager/api/identity/dash/profiles
q=memberIdentity
memberIdentity={LinkedIn public identifier}
decorationId=com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-101
```

The client sends only the observed minimum session/authentication headers. It does not call an official LinkedIn developer API, load profile HTML, execute JavaScript, or control a browser.

## Authentication contract

- `li_at` is the authenticated session cookie.
- `JSESSIONID` supplies the CSRF value.
- The `csrf-token` header is the `JSESSIONID` value without surrounding quotes.
- `x-restli-protocol-version` is `2.0.0`.
- `accept` requests normalized JSON.

The values are injected from environment secrets. The application does not automate password or MFA entry.

## Response contract

The response is normalized:

```json
{
  "data": {"*elements": ["urn:li:fsd_profile:..."]},
  "included": [
    {"entityUrn": "urn:li:fsd_profile:...", "$type": "...Profile"},
    {"entityUrn": "urn:li:collectionResponse:...", "*elements": []}
  ]
}
```

Parsing rules:

1. Index every `included` entity by exact `entityUrn`.
2. Resolve the target profile through `data.*elements[0]`.
3. Follow profile-owned collection references.
4. Never globally collect all `Position` entities.
5. Unwrap both strings and LinkedIn `AttributedText` objects.
6. Resolve location through its Geo URN when `locationName` is absent.
7. Select the largest artifact in VectorImage responses.

## Drift strategy

The endpoint and decoration ID are internal and can change. Schema/endpoint drift must produce an explicit `502` rather than a misleading empty profile. Maintenance should compare a freshly redacted response with the synthetic fixture, update reference paths, and add a regression test before changing the parser.

Research references:

- [LinkedIn Voyager endpoint reference](https://github.com/vicnaum/linkedin-toolkit/blob/main/references/endpoints.md)
- [2026 raw-HTTP and endpoint verification](https://github.com/gabros20/linkedin-relay/blob/main/docs/ENGINE-RESEARCH.md)
- [LinkedIn Rest.li protocol client](https://github.com/linkedin-developers/linkedin-api-python-client)

