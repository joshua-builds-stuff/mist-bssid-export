#!/usr/bin/env python3
"""Mist BSSID Export — standalone CLI

Exports AP radio MACs (BSSIDs) from a Juniper Mist organization to CSV.
Each radio MAC covers up to 16 BSSIDs (last octet 0-F), so the radio MACs
in the export are the base addresses for every BSSID an AP can broadcast.

Run with no arguments for an interactive menu; on first run it walks you
through creating the .env configuration. With arguments it acts as a
non-interactive CLI:

    python bssid_export.py                       # interactive menu
    python bssid_export.py --all                 # entire org
    python bssid_export.py --sites "HQ,Branch 7" # specific sites
    python bssid_export.py --site-group Campus   # sites in a site group
    python bssid_export.py --list-sites          # show org sites
    python bssid_export.py --list-groups         # show org site groups

Configuration comes from a .env file (see .env.example):
    MIST_API_TOKEN  - Mist API token
    MIST_ORG_ID     - organization ID
    MIST_API_URL    - full API base URL (e.g. https://api.mist.com), or
    MIST_CLOUD      - cloud shorthand (global01, emea01, apac02, ...)

Real environment variables take precedence over .env values.
"""

import argparse
import csv
import os
import re
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Some Python installs pair requests with a newer urllib3/charset_normalizer
# than it officially recognizes, which prints a RequestsDependencyWarning on
# import. It is harmless for this tool - silence it before importing requests.
warnings.filterwarnings(
    'ignore', message=r"urllib3 .* doesn't match a supported version")

import requests

# MIST_* values from the actual OS environment, snapshotted before any .env
# loading mutates os.environ — used to warn when a shell export will shadow
# a freshly saved .env on the next launch.
_SHELL_ENV = {k: os.environ[k] for k in
              ('MIST_API_TOKEN', 'MIST_ORG_ID', 'MIST_API_URL', 'MIST_CLOUD')
              if k in os.environ}

# (connect_timeout, read_timeout) in seconds
TIMEOUT = (5, 15)
MAX_RETRIES = 3
INVENTORY_PAGE_SIZE = 1000

CLOUD_ENDPOINTS = {
    'global01': 'https://api.mist.com',
    'global02': 'https://api.gc1.mist.com',
    'global03': 'https://api.ac2.mist.com',
    'global04': 'https://api.gc2.mist.com',
    'global05': 'https://api.gc4.mist.com',
    'emea01':   'https://api.eu.mist.com',
    'emea02':   'https://api.gc3.mist.com',
    'emea03':   'https://api.ac6.mist.com',
    'emea04':   'https://api.gc6.mist.com',
    'apac01':   'https://api.ac5.mist.com',
    'apac02':   'https://api.gc5.mist.com',
    'apac03':   'https://api.gc7.mist.com',
}

# Allowlisted API hostnames (SSRF prevention)
ALLOWED_HOSTS = frozenset(urlparse(u).hostname for u in CLOUD_ENDPOINTS.values())

CSV_FIELDS = [
    'NAME', 'MAP', 'AP_MAC', 'SITE', 'SITE_ADDRESS',
    'RADIO_MACS', 'SWITCH_NAME', 'SWITCH_PORT',
]


class ConfigError(Exception):
    """Raised for missing or invalid configuration."""


# --------------------------------------------------------------------------
# Configuration / .env handling
# --------------------------------------------------------------------------

def load_env(env_path: Path) -> bool:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Existing environment variables are not overridden. Returns True if the
    file existed and was read. Unquoted inline comments (' # ...') are
    stripped; quote a value to keep a literal '#'.
    """
    if not env_path.is_file():
        return False
    try:
        # utf-8-sig: Windows editors often save "UTF-8 with BOM"
        text = env_path.read_text(encoding='utf-8-sig')
    except (UnicodeDecodeError, OSError) as e:
        raise ConfigError(
            f"Could not read {env_path}: {e}\n"
            "Save the file as plain UTF-8 (PowerShell 5.1 '>' redirection "
            "writes UTF-16 - use an editor or Set-Content -Encoding utf8)."
        ) from e
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] in ('"', "'") and value.endswith(value[0]):
            value = value[1:-1]
        else:
            value = re.sub(r'\s+#.*$', '', value).strip()
        if key:
            os.environ.setdefault(key, value)
    return True


def resolve_api_url() -> str:
    """Resolve the Mist API base URL from MIST_API_URL or MIST_CLOUD.

    Errors out if both are set and point at different clouds, so a stale
    MIST_API_URL can never silently override an intended MIST_CLOUD.
    """
    url = os.environ.get('MIST_API_URL', '').strip()
    cloud = os.environ.get('MIST_CLOUD', '').strip()
    cloud_url = ''
    if cloud:
        key = re.sub(r'[\s_-]', '', cloud.lower())
        if key in CLOUD_ENDPOINTS:
            cloud_url = CLOUD_ENDPOINTS[key]
        else:
            # Allow a bare hostname like api.eu.mist.com
            cloud_url = cloud if cloud.lower().startswith('http') else f'https://{cloud}'
    if url and cloud_url and url.rstrip('/') != cloud_url.rstrip('/'):
        raise ConfigError(
            f"MIST_API_URL ({url}) and MIST_CLOUD ({cloud}) point at different "
            "clouds. Set only one of them."
        )
    final = url or cloud_url
    if not final:
        raise ConfigError(
            "No cloud configured. Set MIST_API_URL (e.g. https://api.mist.com) "
            "or MIST_CLOUD (e.g. global01) in your .env file."
        )
    validate_api_url(final)
    return final.rstrip('/')


def validate_api_url(api_url: str) -> None:
    """Raise ConfigError unless api_url is a known Mist cloud endpoint over https."""
    parsed = urlparse(api_url)
    if parsed.scheme != 'https':
        raise ConfigError(
            f"'{api_url}' must use https:// - anything else would send the "
            "API token in cleartext."
        )
    if (parsed.hostname or '') not in ALLOWED_HOSTS:
        valid = ', '.join(sorted(ALLOWED_HOSTS))
        raise ConfigError(
            f"'{api_url}' is not a known Mist cloud endpoint.\n"
            f"Valid hosts: {valid}"
        )


def load_config(env_path: Path | None) -> dict:
    """Load and validate configuration. Returns dict with api_url/api_token/org_id."""
    if env_path is not None:
        if not load_env(env_path):
            raise ConfigError(f".env file not found: {env_path}")
    else:
        # Default search: next to this script, then the current directory
        script_env = Path(__file__).resolve().parent / '.env'
        if not load_env(script_env):
            load_env(Path.cwd() / '.env')

    api_token = os.environ.get('MIST_API_TOKEN', '').strip()
    org_id = os.environ.get('MIST_ORG_ID', '').strip()

    missing = []
    if not api_token or api_token.startswith('your-'):
        missing.append('MIST_API_TOKEN')
    if not org_id or org_id.startswith('your-'):
        missing.append('MIST_ORG_ID')
    if missing:
        raise ConfigError(
            f"Missing configuration: {', '.join(missing)}. "
            "Copy .env.example to .env and fill in your values."
        )

    return {
        'api_url': resolve_api_url(),
        'api_token': api_token,
        'org_id': org_id,
    }


# --------------------------------------------------------------------------
# Mist API session
# --------------------------------------------------------------------------

class MistSession:
    """Mist API session with connection reuse and retry on 429/5xx."""

    def __init__(self, api_url: str, api_token: str):
        validate_api_url(api_url)
        self.base = api_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Token {api_token}',
            'Content-Type': 'application/json',
        })

    def get(self, path: str) -> requests.Response:
        url = f"{self.base}{path}"
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.session.get(url, timeout=TIMEOUT)
            except requests.exceptions.RequestException:
                if attempt == MAX_RETRIES:
                    raise
                delay = 2 ** attempt
                print(f"  Connection problem, retrying in {delay}s...", file=sys.stderr)
                time.sleep(delay)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == MAX_RETRIES:
                    resp.raise_for_status()
                retry_after = resp.headers.get('Retry-After', '')
                delay = int(retry_after) if retry_after.isdigit() else 2 ** attempt
                print(f"  API returned {resp.status_code}, retrying in {delay}s...",
                      file=sys.stderr)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        raise RuntimeError("unreachable")  # pragma: no cover

    def get_json_list(self, path: str) -> list:
        """GET a path and return the JSON body, coerced to a list."""
        data = self.get(path).json()
        return data if isinstance(data, list) else []


# --------------------------------------------------------------------------
# API fetch helpers
# --------------------------------------------------------------------------

def validate_credentials(api: MistSession, org_id: str) -> str:
    """Check the token/org against the cloud. Returns the org name."""
    try:
        resp = api.get(f"/api/v1/orgs/{org_id}")
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        if status == 401:
            raise ConfigError(
                "Authentication failed - the token was rejected. Mist tokens "
                "are cloud-specific: check the token AND that the selected "
                "cloud is the one where the token was created.") from e
        if status == 404:
            raise ConfigError("Organization not found - check MIST_ORG_ID "
                              "and that MIST_API_URL/MIST_CLOUD is the right cloud.") from e
        raise ConfigError(f"API returned status {status} validating credentials.") from e
    except requests.exceptions.ConnectionError as e:
        raise ConfigError(f"Cannot reach {api.base} - check your network/cloud setting.") from e
    except requests.exceptions.Timeout as e:
        raise ConfigError(f"Request to {api.base} timed out.") from e
    return resp.json().get('name', 'Unknown')


def fetch_sites(api: MistSession, org_id: str) -> list[dict]:
    return api.get_json_list(f"/api/v1/orgs/{org_id}/sites")


def fetch_site_groups(api: MistSession, org_id: str) -> list[dict]:
    return api.get_json_list(f"/api/v1/orgs/{org_id}/sitegroups")


def fetch_inventory_aps(api: MistSession, org_id: str) -> dict[str, dict]:
    """Fetch the org inventory (paginated) and return assigned APs.

    Returns {normalized_mac: {'site_id': ..., 'raw_mac': ...}} for APs
    that are assigned to a site. Unassigned APs have no stats or BSSIDs.
    """
    all_devices = []
    page = 1
    while True:
        data = api.get_json_list(
            f"/api/v1/orgs/{org_id}/inventory?limit={INVENTORY_PAGE_SIZE}&page={page}"
        )
        if not data:
            break
        all_devices.extend(data)
        if len(data) < INVENTORY_PAGE_SIZE:
            break
        page += 1

    assigned_aps = {}
    for d in all_devices:
        if d.get('type') != 'ap':
            continue
        site_id = d.get('site_id')
        mac = d.get('mac', '')
        if not site_id or not mac:
            continue
        assigned_aps[normalize_mac(mac)] = {'site_id': site_id, 'raw_mac': mac}
    return assigned_aps


# --------------------------------------------------------------------------
# Data shaping
# --------------------------------------------------------------------------

def normalize_mac(mac: str) -> str:
    return mac.replace(':', '').replace('-', '').lower()


def extract_radio_macs(stat: dict) -> list[str]:
    """Extract radio MACs from an AP stats radio_stat object.

    Pulls band_24.mac, band_5.mac, band_6.mac. Each radio MAC can host
    16 BSSIDs (last octet 0-F).
    """
    radio_stat = stat.get('radio_stat') or {}
    macs = []
    for band in ('band_24', 'band_5', 'band_6'):
        mac = (radio_stat.get(band) or {}).get('mac', '')
        if mac:
            macs.append(mac)
    return macs


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use in a filename."""
    name = name.replace(' ', '_')
    name = re.sub(r'[^a-zA-Z0-9_\-]', '', name)
    name = re.sub(r'_+', '_', name)
    return name.strip('_')


def resolve_scope(
    sites: list[dict],
    site_groups: list[dict],
    site_args: str | None,
    group_arg: str | None,
) -> set[str] | None:
    """Resolve --sites/--site-group arguments to a set of site IDs.

    Returns None for "entire org". Entries match site/group names
    (case-insensitive) or IDs. Raises ConfigError for unknown entries.
    """
    if site_args is not None:
        wanted = [t.strip() for t in site_args.split(',') if t.strip()]
        if not wanted:
            raise ConfigError("--sites was given but contains no site names or IDs.")
        by_id = {s.get('id'): s for s in sites if s.get('id')}
        target = set()
        unknown = []
        for token in wanted:
            if token in by_id:
                target.add(token)
                continue
            matches = [s['id'] for s in sites
                       if s.get('id') and s.get('name', '').lower() == token.lower()]
            if matches:
                target.update(matches)
            else:
                unknown.append(token)
        if unknown:
            names = ', '.join(sorted(s.get('name', '?') for s in sites)) or '(none)'
            raise ConfigError(
                f"Unknown site(s): {', '.join(unknown)}\nAvailable sites: {names}"
            )
        return target

    if group_arg is not None:
        token = group_arg.strip()
        if not token:
            raise ConfigError("--site-group was given but is empty.")
        group = next((g for g in site_groups if g.get('id') == token), None)
        if group is None:
            named = [g for g in site_groups if g.get('name', '').lower() == token.lower()]
            group = named[0] if named else None
        if group is None:
            names = ', '.join(sorted(g.get('name', '?') for g in site_groups)) or '(none)'
            raise ConfigError(
                f"Unknown site group: {token}\nAvailable groups: {names}"
            )
        site_ids = set(group.get('site_ids') or [])
        if not site_ids:
            raise ConfigError(f"Site group '{group.get('name', token)}' contains no sites.")
        return site_ids

    return None  # entire org


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

def export_bssids(
    api: MistSession,
    org_id: str,
    org_name: str,
    all_sites: list[dict],
    target_site_ids: set[str] | None,
    output: Path | None,
) -> tuple[Path, int]:
    """Run the export. Returns (csv_path, row_count)."""
    site_lookup = {}
    for s in all_sites:
        sid = s.get('id')
        if sid:
            site_lookup[sid] = {
                'name': s.get('name', 'Unknown'),
                'address': s.get('address', ''),
            }

    print("Fetching inventory...")
    assigned_aps = fetch_inventory_aps(api, org_id)

    if target_site_ids is not None:
        assigned_aps = {
            mac: info for mac, info in assigned_aps.items()
            if info['site_id'] in target_site_ids
        }

    if not assigned_aps:
        raise ConfigError("No assigned APs found for the selected scope.")

    # Group APs by site for bulk stats
    aps_by_site: dict[str, list[str]] = {}
    for norm_mac, info in assigned_aps.items():
        aps_by_site.setdefault(info['site_id'], []).append(norm_mac)

    print(f"Found {len(assigned_aps)} AP(s) across {len(aps_by_site)} site(s)")

    # Fetch bulk device stats + maps per site
    stats_lookup = {}
    site_ids = list(aps_by_site.keys())
    for idx, site_id in enumerate(site_ids, 1):
        site_name = site_lookup.get(site_id, {}).get('name', site_id[:8])
        print(f"  Site {idx}/{len(site_ids)}: {site_name} "
              f"({len(aps_by_site[site_id])} AP(s))...")

        maps = {}
        try:
            map_data = api.get_json_list(f"/api/v1/sites/{site_id}/maps")
            maps = {m['id']: m.get('name', '') for m in map_data if 'id' in m}
        except Exception as e:
            print(f"    Warning: could not fetch maps: {e}", file=sys.stderr)

        device_stats = []
        try:
            device_stats = api.get_json_list(
                f"/api/v1/sites/{site_id}/stats/devices?type=ap"
            )
        except Exception as e:
            print(f"    Warning: could not fetch device stats: {e}", file=sys.stderr)

        for stat in device_stats:
            norm = normalize_mac(stat.get('mac', ''))
            if norm not in assigned_aps:
                continue
            stats_lookup[norm] = {
                'name': stat.get('name', ''),
                'map_name': maps.get(stat.get('map_id', ''), ''),
                'radio_macs': extract_radio_macs(stat),
                'lldp_system_name': (stat.get('lldp_stat') or {}).get('system_name', ''),
                'lldp_port_id': (stat.get('lldp_stat') or {}).get('port_id', ''),
            }

    # Build CSV rows
    csv_rows = []
    for norm_mac, info in sorted(assigned_aps.items()):
        site_info = site_lookup.get(info['site_id'], {'name': 'Unknown', 'address': ''})
        stats = stats_lookup.get(norm_mac, {})
        csv_rows.append({
            'NAME': stats.get('name', ''),
            'MAP': stats.get('map_name', ''),
            'AP_MAC': info['raw_mac'],
            'SITE': site_info['name'],
            'SITE_ADDRESS': site_info['address'],
            'RADIO_MACS': ', '.join(stats.get('radio_macs', [])),
            'SWITCH_NAME': stats.get('lldp_system_name', ''),
            'SWITCH_PORT': stats.get('lldp_port_id', ''),
        })

    # Resolve output path: no file extension means "directory" (created if
    # needed) so `-o C:\exports` never silently writes a file named 'exports'.
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    default_name = f"{sanitize_filename(org_name) or 'org'}.bssid-export-{timestamp}.csv"
    if output is None:
        output_path = Path.cwd() / default_name
    elif output.is_dir() or output.suffix == '':
        output.mkdir(parents=True, exist_ok=True)
        output_path = output / default_name
    else:
        output_path = output
        output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(csv_rows)

    return output_path, len(csv_rows)


# --------------------------------------------------------------------------
# Listing helpers
# --------------------------------------------------------------------------

def print_sites(sites: list[dict]) -> None:
    if not sites:
        print("No sites found.")
        return
    width = max(len(s.get('name', '')) for s in sites)
    print(f"{'SITE':<{width}}  ID")
    for s in sorted(sites, key=lambda s: s.get('name', '').lower()):
        print(f"{s.get('name', ''):<{width}}  {s.get('id', '')}")


def print_groups(groups: list[dict]) -> None:
    if not groups:
        print("No site groups found.")
        return
    width = max(len(g.get('name', '')) for g in groups)
    print(f"{'GROUP':<{width}}  SITES  ID")
    for g in sorted(groups, key=lambda g: g.get('name', '').lower()):
        count = len(g.get('site_ids') or [])
        print(f"{g.get('name', ''):<{width}}  {count:>5}  {g.get('id', '')}")


# --------------------------------------------------------------------------
# Interactive mode
# --------------------------------------------------------------------------

_REGION_LABELS = {'global': 'Global', 'emea': 'EMEA', 'apac': 'APAC'}


def cloud_menu() -> list[tuple[str, str]]:
    """Ordered (label, url) pairs derived from CLOUD_ENDPOINTS."""
    items = []
    for key, url in CLOUD_ENDPOINTS.items():
        m = re.fullmatch(r'([a-z]+)(\d+)', key)
        label = f"{_REGION_LABELS.get(m.group(1), m.group(1).title())} {m.group(2)}"
        items.append((label, url))
    return items


def prompt_nonempty(label: str) -> str:
    while True:
        value = input(label).strip()
        if value:
            return value
        print("  A value is required (Ctrl+C to abort).")


def choose_cloud() -> str:
    items = cloud_menu()
    print("\nSelect your Mist cloud:")
    for i, (label, url) in enumerate(items, 1):
        print(f"  {i:>2}. {label:<10} {url}")
    while True:
        raw = input(f"Cloud number (1-{len(items)}): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(items):
            return items[int(raw) - 1][1]
        print("  Invalid selection.")


def write_env_file(env_path: Path, api_url: str, api_token: str, org_id: str) -> None:
    content = (
        "# Mist BSSID Export configuration (written by interactive setup)\n"
        f"MIST_API_TOKEN={api_token}\n"
        f"MIST_ORG_ID={org_id}\n"
        f"MIST_API_URL={api_url}\n"
    )
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(content, encoding='utf-8')


def shadowing_env_vars(api_url: str, api_token: str, org_id: str) -> list[str]:
    """OS-environment MIST_* variables that will override the saved .env.

    Real environment variables take precedence over .env, so a shell export
    that disagrees with what the wizard just saved silently wins next launch.
    """
    saved = {'MIST_API_TOKEN': api_token, 'MIST_ORG_ID': org_id, 'MIST_API_URL': api_url}
    shadowing = [key for key, val in saved.items()
                 if key in _SHELL_ENV and _SHELL_ENV[key] != val]
    if 'MIST_CLOUD' in _SHELL_ENV:
        key = re.sub(r'[\s_-]', '', _SHELL_ENV['MIST_CLOUD'].lower())
        resolved = CLOUD_ENDPOINTS.get(key, _SHELL_ENV['MIST_CLOUD'])
        if resolved.rstrip('/') != api_url.rstrip('/'):
            shadowing.append('MIST_CLOUD')
    return shadowing


def interactive_setup(env_path: Path) -> dict:
    """Guided credential setup. Validates, writes .env, returns config."""
    print("\n=== Mist API setup ===")
    print("You need your organization ID, an API token (My Account > API")
    print("Tokens in the Mist portal; read-only is sufficient), and your cloud.")
    while True:
        org_id = prompt_nonempty("\nOrganization ID: ")
        api_token = prompt_nonempty("API token: ")
        api_url = choose_cloud()
        print("\nValidating credentials...")
        try:
            api = MistSession(api_url, api_token)
            org_name = validate_credentials(api, org_id)
        except ConfigError as e:
            print(f"  {e}")
            print("Let's try again (Ctrl+C to abort).")
            continue
        write_env_file(env_path, api_url, api_token, org_id)
        print(f"  Connected to organization: {org_name}")
        print(f"  Saved configuration to {env_path}")
        shadowing = shadowing_env_vars(api_url, api_token, org_id)
        if shadowing:
            print(f"\n  WARNING: {', '.join(shadowing)} "
                  f"{'is' if len(shadowing) == 1 else 'are'} set in your OS "
                  "environment and will override the saved .env on the next "
                  "launch. Unset the variable(s) or the values you just "
                  "entered will not take effect.")
        return {
            'api_url': api_url,
            'api_token': api_token,
            'org_id': org_id,
            'org_name': org_name,
        }


def parse_site_selection(raw: str, ordered_sites: list[dict]) -> set[str]:
    """Map 'numbers, names, or IDs' user input to a set of site IDs.

    Numbers are 1-based indexes into ordered_sites as displayed.
    """
    tokens = [t.strip() for t in raw.split(',') if t.strip()]
    if not tokens:
        raise ConfigError("Nothing selected.")
    target = set()
    for token in tokens:
        matches = {s['id'] for s in ordered_sites
                   if s.get('id') == token or s.get('name', '').lower() == token.lower()}
        if token.isdigit() and 1 <= int(token) <= len(ordered_sites):
            indexed = ordered_sites[int(token) - 1]['id']
            if matches and matches != {indexed}:
                raise ConfigError(
                    f"'{token}' is both a list number and a site name - "
                    "use the site ID to disambiguate.")
            target.add(indexed)
            continue
        if not matches:
            raise ConfigError(f"No site matches '{token}'.")
        target.update(matches)
    return target


def match_group(token: str, ordered_groups: list[dict]) -> dict:
    """Map a 'number, name, or ID' user input to one site group."""
    token = token.strip()
    if not token:
        raise ConfigError("Nothing selected.")
    matches = [g for g in ordered_groups
               if g.get('id') == token or g.get('name', '').lower() == token.lower()]
    if token.isdigit() and 1 <= int(token) <= len(ordered_groups):
        indexed = ordered_groups[int(token) - 1]
        if matches and matches != [indexed]:
            raise ConfigError(
                f"'{token}' is both a list number and a group name - "
                "use the group ID to disambiguate.")
        return indexed
    if matches:
        return matches[0]
    raise ConfigError(f"No site group matches '{token}'.")


def _prompt_output() -> Path | None:
    raw = input("Output file or directory [Enter = current directory]: ")
    raw = raw.strip().strip('"').strip("'")
    return Path(raw) if raw else None


def _menu_export(api: MistSession, org_id: str, org_name: str,
                 sites: list[dict], target_site_ids: set[str] | None) -> None:
    output = _prompt_output()
    path, count = export_bssids(api, org_id, org_name, sites, target_site_ids, output)
    print(f"\nExport complete - {count} AP(s)")
    print(f"CSV written to: {path}")


def run_interactive(env_arg: Path | None) -> int:
    """Menu-driven mode: guided setup when unconfigured, then an action menu."""
    target_env = env_arg or Path(__file__).resolve().parent / '.env'

    config = None
    try:
        config = load_config(env_arg)
    except ConfigError as e:
        print(f"Configuration needed: {e}")
        config = interactive_setup(target_env)

    api = MistSession(config['api_url'], config['api_token'])
    org_id = config['org_id']
    org_name = config.get('org_name')
    if org_name is None:
        try:
            org_name = validate_credentials(api, org_id)
        except ConfigError as e:
            print(f"Stored credentials failed: {e}")
            if input("Reconfigure now? [y/N]: ").strip().lower() not in ('y', 'yes'):
                return 1
            config = interactive_setup(target_env)
            api = MistSession(config['api_url'], config['api_token'])
            org_id = config['org_id']
            org_name = config['org_name']

    cache: dict = {}

    def get_sites() -> list[dict]:
        if 'sites' not in cache:
            sites = [s for s in fetch_sites(api, org_id) if s.get('id')]
            sites.sort(key=lambda s: s.get('name', '').lower())
            cache['sites'] = sites
        return cache['sites']

    def get_groups() -> list[dict]:
        if 'groups' not in cache:
            cache['groups'] = sorted(fetch_site_groups(api, org_id),
                                     key=lambda g: g.get('name', '').lower())
        return cache['groups']

    while True:
        print(f"\n=== Mist BSSID Export - {org_name} ({api.base}) ===")
        print("  1. Export entire org")
        print("  2. Export selected sites")
        print("  3. Export a site group")
        print("  4. List sites")
        print("  5. List site groups")
        print("  6. Reconfigure credentials")
        print("  0. Exit")
        try:
            choice = input("Choice: ").strip().lower()
        except EOFError:
            print()
            return 0
        try:
            if choice in ('0', 'q', 'quit', 'exit'):
                return 0
            elif choice == '1':
                _menu_export(api, org_id, org_name, get_sites(), None)
            elif choice == '2':
                sites = get_sites()
                if not sites:
                    print("No sites in this org.")
                    continue
                for i, s in enumerate(sites, 1):
                    print(f"  {i:>3}. {s.get('name', '')}")
                raw = input("Sites to export (numbers, names, or IDs, comma-separated): ")
                target = parse_site_selection(raw, sites)
                _menu_export(api, org_id, org_name, sites, target)
            elif choice == '3':
                groups = get_groups()
                if not groups:
                    print("No site groups in this org.")
                    continue
                for i, g in enumerate(groups, 1):
                    count = len(g.get('site_ids') or [])
                    print(f"  {i:>3}. {g.get('name', '')} ({count} site(s))")
                raw = input("Site group (number, name, or ID): ")
                group = match_group(raw, groups)
                site_ids = set(group.get('site_ids') or [])
                if not site_ids:
                    raise ConfigError(
                        f"Site group '{group.get('name', '?')}' contains no sites.")
                _menu_export(api, org_id, org_name, get_sites(), site_ids)
            elif choice == '4':
                print_sites(get_sites())
            elif choice == '5':
                print_groups(get_groups())
            elif choice == '6':
                try:
                    config = interactive_setup(target_env)
                except KeyboardInterrupt:
                    print("\nSetup cancelled - keeping existing credentials.")
                    continue
                api = MistSession(config['api_url'], config['api_token'])
                org_id = config['org_id']
                org_name = config['org_name']
                cache.clear()
            else:
                print("Unknown choice - enter 0-6.")
        except ConfigError as e:
            print(f"Error: {e}")
        except requests.exceptions.RequestException as e:
            print(f"API error: {e}")
        except OSError as e:
            print(f"File error: {e}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='bssid_export',
        description='Export Juniper Mist AP radio MACs (BSSIDs) to CSV. '
                    'Run with no arguments for an interactive menu.',
        epilog='Credentials come from .env (MIST_API_TOKEN, MIST_ORG_ID, '
               'MIST_API_URL or MIST_CLOUD); the interactive menu offers '
               'guided setup when they are missing.',
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        '-a', '--all', action='store_true',
        help='export the entire org (non-interactive)')
    scope.add_argument(
        '--sites', metavar='NAME_OR_ID[,..]',
        help='limit export to these sites (comma-separated names or IDs)')
    scope.add_argument(
        '--site-group', metavar='NAME_OR_ID',
        help='limit export to sites in this site group')
    parser.add_argument(
        '-o', '--output', metavar='PATH', type=Path,
        help='output CSV file or directory (default: <org>.bssid-export-<timestamp>.csv '
             'in the current directory)')
    parser.add_argument(
        '--env', metavar='PATH', type=Path,
        help='path to .env file (default: .env next to the script, then ./.env)')
    parser.add_argument('--list-sites', action='store_true',
                        help='list org sites and exit')
    parser.add_argument('--list-groups', action='store_true',
                        help='list org site groups and exit')
    return parser


def wants_interactive(args: argparse.Namespace) -> bool:
    """Interactive unless any action/output flag was given (--env alone is fine)."""
    return not (args.all or args.sites is not None or args.site_group is not None
                or args.list_sites or args.list_groups or args.output is not None)


def main(argv: list[str] | None = None) -> int:
    # Never crash on non-ASCII org/site names when the console/redirect
    # target uses a legacy codepage (cp1252 etc.)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='replace')
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)

    try:
        if wants_interactive(args):
            return run_interactive(args.env)

        config = load_config(args.env)
        api = MistSession(config['api_url'], config['api_token'])
        org_id = config['org_id']

        org_name = validate_credentials(api, org_id)
        print(f"Organization: {org_name} ({api.base})")

        if args.list_sites:
            print_sites(fetch_sites(api, org_id))
            return 0
        if args.list_groups:
            print_groups(fetch_site_groups(api, org_id))
            return 0

        sites = fetch_sites(api, org_id)
        groups = fetch_site_groups(api, org_id) if args.site_group else []
        target_site_ids = resolve_scope(sites, groups, args.sites, args.site_group)

        output_path, count = export_bssids(
            api, org_id, org_name, sites, target_site_ids, args.output,
        )
        print(f"\nExport complete - {count} AP(s)")
        print(f"CSV written to: {output_path}")
        return 0

    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    # RequestException subclasses OSError, so it must be caught first
    except requests.exceptions.RequestException as e:
        print(f"API error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"File error: {e}", file=sys.stderr)
        return 3
    except EOFError:
        print("\nInput closed - exiting.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
