# Mist BSSID Export

Standalone CLI that exports AP radio MACs (BSSIDs) from a Juniper Mist
organization to CSV for **E911 integration**. E911 / dispatchable-location
platforms (RedSky, Intrado, Bandwidth, and similar) map Wi-Fi BSSIDs to
civic addresses and floors so that an emergency call from a Wi-Fi device
reports a dispatchable location — a requirement driven by regulations such
as RAY BAUM'S Act and Kari's Law in the US. This export produces the
AP-to-location data those platforms consume: each AP's radio base MACs
alongside its site street address, floorplan, and wired uplink.

Inspired by [mist-get_bssid](https://github.com/allynjcrowe/mist-get_bssid)
by [Allyn Crowe](https://github.com/allynjcrowe), Principal Engineer @ Nexum.

## Disclaimer

This tool is provided **as is**, without warranty of any kind. It is a
community project and is **not** an official Hewlett Packard Enterprise
(HPE) product. The Mist platform is part of HPE Juniper Networking
(formerly Juniper Networks, acquired by HPE in 2025) — this tool is not
endorsed or supported by HPE, HPE Juniper Networking, or their technical
support organizations (TAC). Use at your own risk.

The tool only issues read-only (GET) API calls and never modifies any
configuration. For added assurance, run it with an API token created with
**Read privileges only** (e.g., an Observer-role token) — with such a token,
configuration changes are impossible at the API level regardless of what any
script does.

This tool extracts data only — it does not by itself provide or guarantee
E911 regulatory compliance. Validate all exported data with your E911
service provider.

## Setup

Requires Python 3.10+.

```
pip install -r requirements.txt
python bssid_export.py    # first run walks you through creating .env
```

Or configure by hand: `copy .env.example .env` and edit it with your values.

`.env` keys (these are the only keys the loader copies into the environment):

| Key | Value |
|-----|-------|
| `MIST_API_TOKEN` | Mist API token (read-only access is sufficient) |
| `MIST_ORG_ID` | Organization ID |
| `MIST_API_URL` | `https://` URL of a known Mist cloud host, e.g. `https://api.mist.com` |
| `MIST_CLOUD` | Alternative to `MIST_API_URL`: shorthand like `global01`, `emea01`, `apac02` |

Any other line in `.env` is left unread. That includes `HTTP_PROXY`,
`HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, `REQUESTS_CA_BUNDLE`, and
`CURL_CA_BUNDLE`.

Set exactly one of `MIST_API_URL` / `MIST_CLOUD`. If both are set they must
agree, otherwise the tool errors out. Process environment values for those
four keys override `.env`. Save `.env` as plain UTF-8 (UTF-8 with BOM also
works; UTF-16 — what PowerShell 5.1 `>` redirection produces — is rejected
with a clear error).

### API URL allowlist

`MIST_API_URL` must use `https://`. The hostname must be one of the hosts
in the table below. The check runs before any request. After it passes,
the session base is `https://` plus that hostname alone, and every API
path is appended to that base. A username, password, port, path, query,
or backslash in the original URL stays out of that base. The token is
sent to that Mist host.

| Cloud | `MIST_CLOUD` | API URL |
|-------|--------------|---------|
| Global 01 | `global01` | `https://api.mist.com` |
| Global 02 | `global02` | `https://api.gc1.mist.com` |
| Global 03 | `global03` | `https://api.ac2.mist.com` |
| Global 04 | `global04` | `https://api.gc2.mist.com` |
| Global 05 | `global05` | `https://api.gc4.mist.com` |
| EMEA 01 | `emea01` | `https://api.eu.mist.com` |
| EMEA 02 | `emea02` | `https://api.gc3.mist.com` |
| EMEA 03 | `emea03` | `https://api.ac6.mist.com` |
| EMEA 04 | `emea04` | `https://api.gc6.mist.com` |
| APAC 01 | `apac01` | `https://api.ac5.mist.com` |
| APAC 02 | `apac02` | `https://api.gc5.mist.com` |
| APAC 03 | `apac03` | `https://api.gc7.mist.com` |

`MIST_CLOUD` accepts those shorthands. It also accepts a bare allowlisted
hostname (`api.eu.mist.com`) or the same `https://` URL. A value that is
not one of those hosts is rejected before a request is sent.

Use a host-only URL from the table. An explicit port is dropped (the call
uses the hostname on the default HTTPS port). A path such as `/api/v1` is
dropped as well; the tool adds its own `/api/v1/...` paths.

### Safe environment configuration

API calls use a direct connection. The requests session sets `trust_env`
off, so these variables have no effect on the Mist session, whether they
are in `.env` or already set in the process:

- `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`
- `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`

TLS verification stays at the requests default (the certifi CA bundle).
This tool has no proxy setting and no custom-CA setting. Reach the Mist
cloud directly from the host that runs the export.

## Usage

```
python bssid_export.py                        # interactive menu
python bssid_export.py --all                  # export the entire org
python bssid_export.py --sites "HQ,Branch 7"  # only these sites (names or IDs)
python bssid_export.py --site-group Campus    # only sites in this site group
python bssid_export.py --list-sites           # show org sites and exit
python bssid_export.py --list-groups          # show org site groups and exit
python bssid_export.py -o C:\exports          # write CSV into a directory
python bssid_export.py -o out.csv             # write CSV to a specific file
python bssid_export.py --env C:\path\to\.env  # use a specific .env file
```

Site names containing commas: an argument that is exactly one site's name
(`--sites "Dallas, TX"`) is taken as that site. To combine it with others,
wrap it in double quotes inside the list (`--sites 'HQ,"Dallas, TX"'`),
repeat `--sites` once per site, or pass the site ID. The interactive site
prompt follows the same rules.

With no arguments the tool opens a menu (export entire org / selected
sites / a site group, list sites/groups, reconfigure credentials). If no
valid configuration exists yet, it walks you through org ID, API token,
and cloud selection, validates them against the cloud, and saves `.env`
next to the script. Any argument (other than `--env`) switches to
non-interactive CLI mode.

Default output file: `<OrgName>.bssid-export-<timestamp>.csv` in the current
directory. A `-o` path without a file extension is treated as a directory and
created if needed; a path ending in `.csv` (or any extension) is the exact
output file.

Exit codes: `0` success, `1` configuration error, `2` API error (or invalid
command-line arguments), `3` file error, `130` cancelled.

If any API call fails after retries — including a single site's device
stats or maps — the export stops with a non-zero exit code and no CSV is
written; an existing file at the output path is left untouched.

## CSV columns

| Column | Contents |
|--------|----------|
| `NAME` | AP name |
| `MAP` | Floorplan/map the AP is placed on — floor/area granularity for the dispatchable location |
| `AP_MAC` | AP Ethernet MAC |
| `SITE` | Site name |
| `SITE_ADDRESS` | Site street address — the civic address for the dispatchable location |
| `RADIO_MACS` | Radio base MACs (2.4 GHz, 5 GHz, 6 GHz) — 16 BSSIDs each |
| `SWITCH_NAME` | LLDP neighbor system name (supports wiremap-based location) |
| `SWITCH_PORT` | LLDP neighbor port (supports wiremap-based location) |

## E911 integration notes

- **Each radio MAC is a base address.** An AP broadcasts up to 16 BSSIDs
  per radio by varying the last hex digit (0-F) of the radio MAC. Most
  E911 platforms accept masked/wildcard BSSID entries — enter each radio
  MAC with the last digit wildcarded, or expand it to all 16 BSSIDs if
  your provider requires explicit entries.
- **Keep the export current.** BSSIDs change when an AP is replaced (RMA,
  refresh) and appear when APs are added. Re-run the export and re-upload
  to your E911 platform after any hardware change, and consider a
  scheduled re-run as a safety net.
- **Export with APs online.** Radio MACs come from live AP stats; offline
  APs export with an empty `RADIO_MACS` column (the run prints how many),
  so generate the E911 upload while APs are connected.
- **Verify site addresses in Mist first.** `SITE_ADDRESS` comes straight
  from the Mist site configuration — the dispatchable location is only as
  accurate as the address entered there, and floor granularity depends on
  APs being placed on their floorplans (`MAP` column).

## Security

Two session protections shipped on 2026-09-28. Both keep the Mist API
token on an allowlisted Mist host. Setup above is the configuration that
matches the code.

**API URL.** The host check used to read the parsed hostname, then hand
the original URL string to the HTTP client. Those two parsers can disagree
when the authority contains a backslash, so a URL that still names a Mist
host can make the client open a different host and send
`Authorization: Token …` there. The session now builds its base as
`https://` plus the allowlisted hostname after the check, and that base is
what the token is sent to. See [API URL allowlist](#api-url-allowlist).

**Environment.** `.env` used to copy every key into the process, and the
HTTP client trusted proxy and CA variables from the environment. With the
token already set in the process, a `.env` could still add `HTTPS_PROXY`
and `REQUESTS_CA_BUNDLE`, and the token would travel through that proxy
while the URL host stayed a Mist cloud. The loader now copies only
`MIST_API_TOKEN`, `MIST_ORG_ID`, `MIST_API_URL`, and `MIST_CLOUD`. The
session turns `trust_env` off, so proxy and CA variables already in the
process stay unused too. See
[Safe environment configuration](#safe-environment-configuration).

Keep using a read-only token. Put one allowlisted cloud in `.env` (or in
the process environment, which wins over `.env` for those four keys).

## Notes

- Only APs assigned to a site are exported (unassigned inventory has no
  radio stats).
- All API calls are read-only GETs; 429/5xx responses are retried with
  backoff.

## Tests

```
python -m unittest discover tests -v
```

## License

[MIT](LICENSE)
