# Changelog

## 2026-09-28 — minor

Security fixes for the Mist API session. Install steps, the four `.env`
keys, and the allowlisted cloud hosts are unchanged. Operators who
previously reached Mist through a proxy, or with a custom CA bundle from
the environment, need a direct connection to the cloud.

### Security

- The API host allowlist now decides the URL the token is sent to. After
  the hostname check, the session base is `https://` plus that allowlisted
  hostname, so a backslash or other extra authority in `MIST_API_URL`
  cannot send the token to a different host (#2, #26).
- `.env` loads only `MIST_API_TOKEN`, `MIST_ORG_ID`, `MIST_API_URL`, and
  `MIST_CLOUD`. Mist API calls leave proxy and CA environment variables
  unused (`trust_env` is off), so a `.env` cannot send an existing token
  through an injected proxy or CA (#3, #27).

### Changed

- Username, password, port, path, and query on `MIST_API_URL` are dropped.
  Use a host-only `https://` URL from the allowlist, or `MIST_CLOUD`.
- `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`,
  `REQUESTS_CA_BUNDLE`, and `CURL_CA_BUNDLE` have no effect on Mist API
  calls. This tool has no setting to apply a proxy or a custom CA. Reach
  the Mist cloud directly. TLS verification still uses the default
  requests CA bundle.
