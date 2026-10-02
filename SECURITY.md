# Security

This document describes how this CLI handles the Mist API token and
`.env`. It matches `bssid_export.py` on the default branch. It does not
list vulnerabilities in the Mist cloud.

The tool issues read-only HTTP GET calls. It does not create, update, or
delete Mist configuration. For a hard limit on what the token can do,
create it with read privileges only (an Observer-role token). With that
token, configuration changes are rejected by the API.

## Where the token goes

The token is sent as `Authorization: Token <MIST_API_TOKEN>` on requests
from the Mist session.

Before any request, the configured URL must be `https://` and its
hostname must be one of the allowlisted Mist hosts in the README. The
session base is then `https://` plus that hostname only. A username,
password, port, path, query, or backslash in the original URL is not
part of the base the token is sent to. An `http://` URL is rejected so
the token is not sent in cleartext. An unknown host is rejected before
a request is made.

The session sets `trust_env` off. These variables do nothing for Mist
calls, whether they come from `.env` or from the process environment:

- `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`
- `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`

TLS verification stays on the requests default (the certifi CA bundle).
There is no setting in this tool for a proxy or a custom CA. Run the
export on a host that can reach the Mist cloud directly.

## What `.env` loads

The loader copies only these keys into the process:

- `MIST_API_TOKEN`
- `MIST_ORG_ID`
- `MIST_API_URL`
- `MIST_CLOUD`

Every other line is left unread, including proxy and CA variables. If
one of the four keys is already set in the process environment, `.env`
does not replace it.

Interactive setup writes `MIST_API_TOKEN`, `MIST_ORG_ID`, and
`MIST_API_URL` to a plaintext `.env` next to the script (or to the path
given with `--env`). The new contents are written to a temporary file in
the same directory and moved onto `.env`. The existing file is not
emptied first. If the save fails, the previous `.env` is left as it was
and the temporary file is removed. On Unix a successful save is mode
`0600`: the owner can read and write it, and other users on the host
cannot, including when the previous file was readable by the group or by
everyone else. On Windows, `os.fchmod` is missing before Python 3.13 and
`chmod` only toggles the read-only flag, so that mode change is
best-effort. First-time setup, menu option 6 (Reconfigure credentials),
and reconfigure after stored credentials fail all use this write.

A `.env` created by copying `.env.example` keeps the permissions of that
copy. On a shared Unix host, restrict that copy to your user before it
contains the token. Loading `.env` for an export keeps the mode the file
already has.

`.env` is listed in `.gitignore`. Treat the file as a secret: it
contains the API token. Do not commit it, and do not pass it to people
who should not call the API as you.

Unquoted values are truncated at the first ` #` (an inline comment).
A token that contains `#` must be quoted, single or double, or the
loader will keep only the text before that comment and the cloud will
reject the shortened token:

```
MIST_API_TOKEN="tok#with#hash"  # comment after the closing quote is ignored
```

The file must be UTF-8. A leading UTF-8 BOM is accepted. UTF-16 (what
PowerShell 5.1 `>` redirection writes) is rejected and nothing from that
file is loaded.

The CLI does not print the token. Errors name the missing key or the
rejected URL; they do not echo `MIST_API_TOKEN`.

## What the CSV contains

The CSV holds AP names, Ethernet MACs, radio base MACs, site names,
site street addresses, map names, and LLDP neighbor system name and
port. It does not contain the API token.

A failed fetch of org AP stats, site device stats, or site maps aborts
before the destination CSV is replaced. The file is written to a
temporary name in that directory and moved into place only after the
write finishes, so a failed run does not publish a partial export in
place of the previous one.

## Reporting

Report a problem in this repository through
[GitHub issues](https://github.com/joshua-builds-stuff/mist-bssid-export/issues).
There is no separate private disclosure address for this project.
