# Changelog

## 2026-09-28 — minor

Security fixes for the Mist API session, and export corrections for
paging, site selection, names, and the CSV. Install steps, the four
`.env` keys, and the allowlisted cloud hosts are unchanged. Operators
who previously reached Mist through a proxy, or with a custom CA bundle
from the environment, need a direct connection to the cloud.

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

### Fixed

- Site device stats are read on every page. An AP past page 1 keeps its
  BSSIDs in `RADIO_MACS` (#18).
- Org sites and site groups are read on every page. A site past page 1
  still fills `SITE` and `SITE_ADDRESS` (#19).
- If org AP stats, a site's device stats, or a site's maps cannot be
  fetched, the CLI exits 2. The CSV is written to a temporary file and
  moved into place only after the write finishes, so a failed run does
  not replace an existing CSV (#20).
- A `--sites` value that is exactly one site's name or ID is kept whole,
  so a name that contains a comma (for example `Dallas, TX`) selects
  that site. Combine sites by quoting (`HQ,"Dallas, TX"`), repeating
  `--sites`, or passing the site ID. The interactive prompt uses the
  same rules (#21).
- The CSV is UTF-8 with a BOM, so Excel shows non-ASCII site names and
  addresses (#22).
- When more than one site group shares a name, the export errors and
  prints each group's name and ID instead of using the first match.
  Pass the group ID (#23).
- Org inventory is requested with `type=ap`. Rows that are not APs,
  have no site, or have no MAC are still omitted (#24).
- An org-wide export loads AP stats with one paged org query (`type=ap`
  and the fields `mac`, `site_id`, `name`, `map_id`, `status`,
  `radio_stat`, `lldp_stat`). `--sites` and `--site-group` still use
  per-site device stats. If a connected AP's org stats omit
  `radio_stat`, that site is read from the per-site endpoint (#25).
- A device-stats row whose MAC is null, missing, or not a string is
  skipped. The export continues (#29).
- A leading `~` in `-o` or in the interactive output path expands to
  the home directory (#30).
- A quoted `.env` value keeps its contents when an inline comment
  follows the closing quote. Unquoted values are still cut at ` #`
  (#31).
- Site maps are read on every page, so a floorplan past page 1 still
  fills `MAP` (#32).
- `NAME` uses the device-stats name when that field is a non-empty
  string; otherwise the inventory `name`, then the inventory `hostname`
  (#33).
- Site IDs and site-group IDs match regardless of case, on the CLI and
  in the interactive prompts (#34).
