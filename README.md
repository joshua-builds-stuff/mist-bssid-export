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
Interactive setup saves `.env` so only the file owner can read and write
it (Unix mode `0600`). A hand-copied file keeps the permissions of that
copy; on a shared Unix host, restrict it to your user before it holds
the token.

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

Interactive setup writes `.env`, then warns when a variable already set
in the OS environment will override that file on the next launch.
`MIST_API_TOKEN` and `MIST_ORG_ID` are compared exactly. `MIST_API_URL` is
compared after stripping whitespace and a trailing `/` — it is not
rewritten into another URL. `MIST_CLOUD` is resolved the same way startup
resolves it (a known shorthand, with case ignored and spaces, underscores,
and hyphens dropped; a bare hostname prefixed with `https://`; or a value
that already starts with `http`), and a trailing `/` on that result is
ignored. The warning names only variables that still differ, so
a shell setting that names the cloud just saved does not warn. Unset the
named variables, or the values just entered do not take effect next
launch. The same rules are in [docs/usage.md](docs/usage.md).

That write also limits who can read the file. Setup creates `.env` with
mode `0600` (owner read and write). When a file is already at that path,
setup sets it to `0600` before writing the new token, org ID, and cloud
URL. First-time setup, menu option 6 (Reconfigure credentials), and
reconfigure after stored credentials fail all use this write. A later
export that only reads `.env` keeps the mode the file already has.

Unquoted values are cut at an inline comment (` #`). A single- or
double-quoted value keeps everything inside the quotes, including `#`, and
a comment after the closing quote is ignored. Quote a token that contains
`#`.

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

Selection rules, paging, and how each column is filled are written out in
[docs/usage.md](docs/usage.md).

```
python bssid_export.py                        # interactive menu
python bssid_export.py --all                  # export the entire org
python bssid_export.py --sites "HQ,Branch 7"  # only these sites (names or IDs)
python bssid_export.py --sites "Dallas, TX"   # one site whose name contains a comma
python bssid_export.py --site-group Campus    # only sites in this site group
python bssid_export.py --list-sites           # show org sites and exit
python bssid_export.py --list-groups          # show org site groups and exit
python bssid_export.py -o C:\exports          # write CSV into a directory
python bssid_export.py -o out.csv             # write CSV to a specific file
python bssid_export.py -o ~/exports           # ~ expands to the home directory
python bssid_export.py --env C:\path\to\.env  # use a specific .env file
```

Site and site-group names match regardless of case. Site IDs and
site-group IDs match regardless of case as well, on the CLI and in the
interactive prompts.

Site names containing commas: an argument that is exactly one site's name
or ID (`--sites "Dallas, TX"`) is kept whole and is not split on the
comma. To combine it with others, wrap the name in double quotes inside
the list (`--sites 'HQ,"Dallas, TX"'`), repeat `--sites` once per site, or
pass the site ID. The interactive site prompt follows the same rules.

`--site-group` takes one name or one ID (it is not a comma-separated
list). Mist does not require group names to be unique. If more than one
group shares that name (compared without regard to case), the tool
errors and prints each group's name and ID instead of exporting the
first match. Pass the group ID. In the menu, the list number or the
group ID selects one group. That error is a configuration error (exit
`1` on the CLI).

With no arguments the tool opens a menu (export entire org / selected
sites / a site group, list sites/groups, reconfigure credentials). If no
valid configuration exists yet, it walks you through org ID, API token,
and cloud selection, validates them against the cloud, and saves `.env`
next to the script. A shell variable that will override that file is
named in a warning, using the comparison in Setup above. Any argument
(other than `--env`) switches to
non-interactive CLI mode. In the menu, a configuration or API error is
printed and the menu stays open; the exit codes below apply to CLI mode.

Default output file: `<OrgName>.bssid-export-<timestamp>.csv` in the current
directory. A `-o` path without a file extension is treated as a directory and
created if needed; a path ending in `.csv` (or any extension) is the exact
output file. A leading `~` in `-o` or in the menu's output prompt expands
to the home directory (`USERPROFILE` on Windows, `HOME` otherwise). The
menu never passes the path through a shell, so type `~/exports` there
when you want the home directory rather than a folder named `~`.

Exit codes: `0` success, `1` configuration error, `2` API error (or invalid
command-line arguments), `3` file error, `130` cancelled.

If a fetch fails after retries — org AP stats on an org-wide export, or
any site's device stats or maps — the CLI exits `2`. The CSV is written
to a temporary file in the destination directory and moved into place
only after that write finishes, so a failed run does not replace an
existing CSV and does not leave the temporary file behind. When the
destination did not exist yet, no CSV is created.

An org-wide export (`--all`, or menu option 1) loads AP stats with one
paged org query. `--sites` and `--site-group` load device stats per site.
Both paths page every list they read. Details are in
[docs/usage.md](docs/usage.md).

## CSV columns

| Column | Contents |
|--------|----------|
| `NAME` | AP name from device stats when that field is a non-empty string; otherwise the inventory `name`, then the inventory `hostname` |
| `MAP` | Floorplan/map the AP is placed on — floor/area granularity for the dispatchable location. Map names come from every page of the site's maps |
| `AP_MAC` | AP Ethernet MAC |
| `SITE` | Site name |
| `SITE_ADDRESS` | Site street address — the civic address for the dispatchable location |
| `RADIO_MACS` | Radio base MACs (2.4 GHz, 5 GHz, 6 GHz) — 16 BSSIDs each |
| `SWITCH_NAME` | LLDP neighbor system name (supports wiremap-based location) |
| `SWITCH_PORT` | LLDP neighbor port (supports wiremap-based location) |

The CSV is UTF-8 with a byte-order mark (BOM) so Excel displays non-ASCII
site names and addresses (e.g. `São Paulo`) correctly. Tools that read
UTF-8 skip the BOM; in Python, open the file with `encoding='utf-8-sig'`.

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

**On-disk token.** Interactive setup used to create `.env` with the
process umask. On a shared Unix host that left `MIST_API_TOKEN` readable
by other local users. Setup now saves the file as owner read/write only
(`0600`), and applies that mode to an existing file before the new token
is written. See [SECURITY.md](SECURITY.md).

Keep using a read-only token. Put one allowlisted cloud in `.env` (or in
the process environment, which wins over `.env` for those four keys).
Quote a `.env` value that contains `#`, so an inline comment does not
cut the token short. The same rules are collected in
[SECURITY.md](SECURITY.md).

## Notes

- Only APs assigned to a site are exported (unassigned inventory has no
  radio stats). Org inventory is requested with `type=ap` and paged like
  the other lists: up to 1000 per page, following `X-Page-Total` and
  `X-Page-Limit`. A non-empty short page does not end the inventory while
  `X-Page-Total` is set and has not been reached. After every page is
  read, a row that is not an AP, has no site, or has no MAC is omitted.
- Org sites, site groups, site maps, device stats, and org inventory are
  read page by page, so a site, floorplan, or AP past the first page is
  still exported.
- A device-stats row whose MAC is null, missing, or not a string is
  skipped. The export continues. An assigned AP that never appears in
  stats is still written, with an empty `RADIO_MACS`.
- All API calls are read-only GETs; 429/5xx responses are retried with
  backoff.

## Tests

```
python -m unittest discover tests -v
```

## License

[MIT](LICENSE)
