# Usage

How to select a scope, which Mist lists are paged, and how the CSV is
written. Install steps, the four `.env` keys, and the cloud allowlist are
in the [README](../README.md). Credential handling is in
[SECURITY.md](../SECURITY.md).

```
python bssid_export.py                        # interactive menu
python bssid_export.py --all                  # export the entire org
python bssid_export.py --sites "HQ,Branch 7"  # these sites (names or IDs)
python bssid_export.py --sites "Dallas, TX"   # one site whose name contains a comma
python bssid_export.py --sites 'HQ,"Dallas, TX"'
python bssid_export.py --site-group Campus    # sites in this site group
python bssid_export.py --list-sites           # show org sites and exit
python bssid_export.py --list-groups          # show org site groups and exit
python bssid_export.py -o ~/exports           # directory; ~ is your home directory
python bssid_export.py -o out.csv             # exact output file
python bssid_export.py --env C:\path\to\.env  # use a specific .env file
```

`--all`, `--sites`, and `--site-group` are mutually exclusive. With no
arguments the tool opens a menu. `--env` alone still opens the menu. Any
other argument switches to the CLI. In the menu, a configuration or API
error is printed and the menu stays open. The exit codes in the README
apply to CLI mode.

## Select sites

`--sites` may be repeated. Each value is a site name, a site ID, or a
comma-separated list of those.

Names match regardless of case. IDs match regardless of case. Every site
whose name matches is included, so two sites with the same name are both
exported.

A value equal to one site's name (any case) or equal to one site's ID
is kept whole. `--sites "Dallas, TX"` selects the site named
`Dallas, TX` and is not split into `Dallas` and `TX`. To combine that
site with others:

- quote the name inside the list: `--sites 'HQ,"Dallas, TX"'`
- repeat the flag: `--sites "Dallas, TX" --sites HQ`
- pass the site ID

The interactive prompt ("numbers, names, or IDs") uses the same comma
rules. Numbers are 1-based positions in the printed list. If a number is
also another site's name or ID, the prompt errors and asks for the site
ID.

An unknown name or ID is a configuration error (CLI exit `1`). The
message quotes the tokens it tried and lists the org's site names.

## Select a site group

`--site-group` takes one name or one ID. Names and IDs match regardless
of case. The group's `site_ids` are the export scope. An empty group is
a configuration error.

Mist allows more than one group to share a name, and the API order is
not stable. If the name matches more than one group (the comparison
ignores case, so `Campus` and `campus` collide), the tool does not pick
the first. It errors, prints each matching group's name and ID, and
tells you to pass the group ID. CLI exit code is `1`.

A group ID selects that group even when names collide. In the menu, the
printed list number does the same. `--list-groups` prints each group's
name, site count, and ID.

## What the export reads

Every call is an HTTP GET. `429` and `5xx` responses, and connection
errors, are retried up to three times (a numeric `Retry-After` header,
otherwise a short backoff). After the last attempt the error propagates.

Only APs assigned to a site are exported. Unassigned inventory has no
radio stats.

**Inventory.** `GET /api/v1/orgs/{org_id}/inventory?type=ap` is read with
the pager below, 1000 devices per page. It follows `X-Page-Total` and
`X-Page-Limit`. A non-empty page shorter than 1000 does not end the
inventory while fewer than `X-Page-Total` devices have been collected.
After every page is collected, a row that is not an AP, has no
`site_id`, or has no MAC is dropped. The inventory `name`, or else
`hostname`, is kept for the `NAME` fallback below.

**Sites and site groups.** `GET /api/v1/orgs/{org_id}/sites` and
`GET /api/v1/orgs/{org_id}/sitegroups` are read with the pager below, so
a site past the first page still supplies `SITE` and `SITE_ADDRESS`.

**Maps.** For each site in scope,
`GET /api/v1/sites/{site_id}/maps` is read with the same pager. `MAP` is
the name of the map whose id is the AP's `map_id`. A floorplan past the
first page is included.

**AP stats, org-wide.** `--all` and menu option 1 (no site filter) issue
one paged query:

`GET /api/v1/orgs/{org_id}/stats/devices?type=ap&fields=mac,site_id,name,map_id,status,radio_stat,lldp_stat`

Stats are grouped by `site_id`. If any connected AP in a site's slice is
missing the `radio_stat` field, that site is fetched again from the
per-site endpoint so radio MACs are not left blank.

**AP stats, scoped.** `--sites` and `--site-group` do not use the org
stats query. Each selected site is read from
`GET /api/v1/sites/{site_id}/stats/devices?type=ap`, paged the same way.

**Pager.** Those list calls (org AP inventory, sites, site groups, maps,
org stats, and per-site device stats) request up to 1000 items per page.
The tool stops once it has collected `X-Page-Total` items. A non-empty
page shorter than 1000 does not stop the read while that total has not
been reached. Without `X-Page-Total` it stops on an empty page, or on a
page shorter than `X-Page-Limit` (or shorter than 1000 when the server
does not send that header). An empty page stops the read either way.

## Names, maps, and missing MACs

`NAME` is the first of these that is a non-empty string:

1. the device-stats `name`
2. the inventory `name`
3. the inventory `hostname`

A stats `name` that is null or missing does not clear the inventory
name. Offline APs, which have no stats row, still export under the
inventory name or hostname with an empty `RADIO_MACS`. The run prints
how many assigned APs were absent from device stats.

A device-stats row whose `mac` is null, missing, or not a string is
skipped. The export does not stop. That row is not a CSV line of its
own. An assigned AP is matched by MAC, so a stats row with no MAC cannot
attach a name or radio MACs to it.

`RADIO_MACS` is `band_24.mac`, `band_5.mac`, and `band_6.mac` from
`radio_stat`, joined with a comma and a space. `SWITCH_NAME` and
`SWITCH_PORT` come from `lldp_stat` `system_name` and `port_id`.

## When a fetch fails

A failure fetching org AP stats, a site's device stats, or a site's maps
aborts the export. Blank BSSID or map columns would look the same as an
offline AP in an E911 upload, so the run does not write a partial CSV.

On the CLI that is exit `2` (the API-error code), after retries are
exhausted. The CSV is written to a temporary file in the destination
directory and moved into place only after the full write succeeds. A
failed run leaves an existing CSV unchanged and removes the temporary
file. If the destination file did not exist, it is not created.

Unknown sites, an ambiguous site-group name, a missing `.env`, and "no
assigned APs in this scope" are configuration errors (CLI exit `1`) and
also write no CSV.

## Output path

The default file is `<OrgName>.bssid-export-<timestamp>.csv` in the
current directory. Characters outside letters, digits, `_`, and `-` are
stripped from the org name in that filename.

`-o` and the menu prompt accept either a directory or a file. A path
with no extension is a directory (created if needed), including a path
that does not exist yet. A path whose last component has an extension
(`.csv` or anything else) is the file itself; parent directories are
created.

`~` at the start of the path is expanded to the home directory before
that directory-versus-file check (`USERPROFILE` on Windows, `HOME`
otherwise). Expand happens in the tool, so it applies to the menu and
to a quoted `-o` value. An unquoted `~/exports` on the command line is
expanded by the shell first.

## CSV file

Encoding is UTF-8 with a byte-order mark, so Excel reads non-ASCII site
names and addresses (for example `São Paulo`) as UTF-8. Open the file in
Python with `encoding='utf-8-sig'`. Column meanings are in the README.

## `.env` values

Only `MIST_API_TOKEN`, `MIST_ORG_ID`, `MIST_API_URL`, and `MIST_CLOUD`
are loaded. Anything else in the file is ignored. A value already set
in the process environment is left as-is.

Unquoted values are cut at an inline comment: `MIST_ORG_ID=abc123  # production`
loads `abc123`. A single- or double-quoted value keeps the text inside
the quotes, including `#`, and a comment after the closing quote is
ignored: `MIST_API_TOKEN="tok#with#hash"  # production` loads
`tok#with#hash`. Quote a token that contains `#`.

Save the file as UTF-8. UTF-8 with a BOM is accepted. UTF-16 is rejected.

## Shell values after interactive setup

Interactive setup writes `MIST_API_TOKEN`, `MIST_ORG_ID`, and
`MIST_API_URL` (the cloud you picked). It does not write `MIST_CLOUD`.
Process environment values still override that file on the next launch.
When one of them will, setup prints a warning naming each variable and
tells you to unset it or the values just entered will not take effect.

`MIST_API_TOKEN` and `MIST_ORG_ID` are compared exactly, character for
character. A different token or org ID warns.

`MIST_API_URL` is compared after stripping whitespace and a trailing
`/`. The shell value is not turned into another URL. These name the same
cloud and do not warn when setup saved `https://api.mist.com`:

- `https://api.mist.com/`
- `https://api.mist.com`

A different host still warns. `https://api.eu.mist.com` against that
saved URL warns `MIST_API_URL`.

`MIST_CLOUD` is resolved the same way startup resolves it, then a
trailing `/` is ignored, and the result is compared to the saved URL:

- a known shorthand (`global01`, `emea01`, `apac02`, and the other names
  in the README table) maps to that cloud's `https://` URL. Lookup
  ignores case and drops spaces, underscores, and hyphens, so
  `Global 01`, `global-01`, and `global_01` are `global01`
- a bare hostname is prefixed with `https://` (`api.mist.com` becomes
  `https://api.mist.com`)
- a value that already starts with `http` is kept as that URL

`MIST_CLOUD=api.mist.com` or `MIST_CLOUD=global01` does not warn when
setup saved `https://api.mist.com`. `MIST_CLOUD=emea01` against that
saved URL does warn. A shell value that names the saved cloud does not
warn; the next launch still prefers the process environment, and
startup treats the two forms as the same cloud.

## Who can read the saved `.env`

Interactive setup saves `.env` with Unix mode `0600`. The owner can read
and write the file. Other users on the host cannot. A new file is
created with that mode. When a file is already at that path, setup sets
it to `0600` before writing `MIST_API_TOKEN`, `MIST_ORG_ID`, and
`MIST_API_URL`.

The write runs in three places:

- the menu has no valid configuration yet (first run, or credentials
  the tool cannot load)
- stored credentials fail and you choose to reconfigure
- menu option 6, Reconfigure credentials

A `.env` you create by copying `.env.example` keeps the permissions of
that copy. On a shared Unix host, restrict it to your user before it
holds the token. An export that only reads `.env` keeps the mode the
file already has. The same rules are in [SECURITY.md](../SECURITY.md).
