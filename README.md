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

`.env` keys:

| Key | Value |
|-----|-------|
| `MIST_API_TOKEN` | Mist API token (read-only access is sufficient) |
| `MIST_ORG_ID` | Organization ID |
| `MIST_API_URL` | Full API base URL, e.g. `https://api.mist.com` |
| `MIST_CLOUD` | Alternative to `MIST_API_URL`: shorthand like `global01`, `emea01`, `apac02` |

Set exactly one of `MIST_API_URL`/`MIST_CLOUD` — if both are set they must
agree, otherwise the tool errors out. Real environment variables override
`.env` values. Only known Mist cloud hostnames over https are accepted.
Save `.env` as plain UTF-8 (UTF-8 with BOM also works; UTF-16 — what
PowerShell 5.1 `>` redirection produces — is rejected with a clear error).

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
  APs export with an empty `RADIO_MACS` column, so generate the E911
  upload while APs are connected.
- **Verify site addresses in Mist first.** `SITE_ADDRESS` comes straight
  from the Mist site configuration — the dispatchable location is only as
  accurate as the address entered there, and floor granularity depends on
  APs being placed on their floorplans (`MAP` column).

## Notes

- Only APs assigned to a site are exported (unassigned inventory has no
  radio stats).
- All API calls are read-only GETs; 429/5xx responses are retried with
  backoff.

## Tests

```
python -m unittest discover tests -v
```
