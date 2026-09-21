# snowq

Query ServiceNow's REST APIs from Python by reusing the session you get from logging in through SSO in a browser. You don't need an API user, OAuth client, or password.

## How it works

Once you finish an SSO (SAML/OIDC) login, the instance sets ordinary session cookies (`JSESSIONID`, `glide_user_route`, `glide_session_store`, …). ServiceNow accepts those cookies on its REST endpoints as long as the request also sends the session's CSRF token, `g_ck`, in the `X-UserToken` header. snowq:

1. gets the cookies (see below),
2. gets `g_ck` — from the login capture if it has one, otherwise from the
   `X-UserToken-Response` header the REST API returns, falling back to scraping
   a UI page (`/navpage.do`),
3. calls `/api/now/...` with both,
4. saves any rotated cookies to `~/.config/snowq/sessions/<host>.session.json` (mode 0600) so the next run reuses them.

When the session expires (you get redirected to the IdP, a 401, or an HTML login page instead of JSON), snowq exits with code 3 and tells you to log in again.

Everything runs as **you**, with your roles and ACLs. Treat the session file like a password.

## Install

```sh
uv sync --extra login                 # or --extra all to include browser-cookie import
uv run --extra login playwright install chromium   # skip if you'll use --channel chrome / msedge
```

`uv run` re-syncs the environment first and drops extras unless you name them, so
`uv run playwright ...` without `--extra login` uninstalls Playwright and then fails
with `Failed to spawn: playwright`.

### Behind Artifactory or another private index

**uv does not read `pip.conf` / `pip.ini`.** If your machine is set up for a
private index through pip's config, pip works and uv quietly falls back to
pypi.org — which a corporate network usually blocks. uv only takes an index from
`uv.toml`, `[tool.uv]` in `pyproject.toml`, `UV_*` environment variables, or the
command line.

Either way — no index configured, or one configured but unauthenticated — uv gets
nothing back and reports the package as *missing* rather than unreachable:

```
error: No solution found when resolving dependencies
  cause: Because requests was not found in the package registry and your project
         depends on requests>=2.25, we can conclude that your project's
         requirements are unsatisfiable.
```

That is an index problem, not a version problem. `requests` is on every mirror;
if uv cannot find it, it is not reaching an index it can read. Start by copying
pip's index URL over:

```sh
echo "$PIP_INDEX_URL"  # `pip config list` shows config FILES only, not env vars
pip config debug       # this one does include the environment-variable section
uv sync --extra login --index "$PIP_INDEX_URL"
```

`--index` puts that URL at the front of the search order — above `--default-index`
and above anything in `uv.toml` — so it is the reliable way to test a URL before
making it permanent. If pip works and uv
does not, this is nearly always why: the index lives in `PIP_INDEX_URL`, which
configures pip and nothing else.

If that URL carries no credentials, authenticate it.

**Check which Artifactory repo the URL names.** A `*-local` repo holds only what
your own organisation publishes — it does not proxy pypi.org, so third-party
packages are legitimately absent and uv reports them as not found:

```
DEBUG Sending fresh GET request for:
      https://artifactory.example.com/artifactory/api/pypi/pypi-local/simple/requests/
```

Third-party packages come from a `*-remote` proxy repo, or from the *virtual*
repo that aggregates local and remote. Swap the repo segment and probe it:

```sh
for repo in pypi pypi-virtual pypi-remote pypi-local; do
  printf '%-16s -> ' "$repo"
  curl -sS -o /dev/null -w '%{http_code}\n' \
    "https://artifactory.example.com/artifactory/api/pypi/$repo/simple/requests/"
done
```

`uv sync -v` prints every URL it requests, which is the fastest way to see what
index you are actually hitting. Expect it to also log `Resolving despite existing
lockfile due to missing remote index` — that is the lockfile churn described above.

Pick one (uv reads all three; keep the URL and token out of the repo):

```sh
# 1. credentials in the index URL
export UV_DEFAULT_INDEX="https://$USER:$ARTIFACTORY_TOKEN@artifactory.example.com/artifactory/api/pypi/pypi/simple"

# 2. netrc  (chmod 600; on Windows use %USERPROFILE%\.netrc and set NETRC
#    explicitly, since the filename is sometimes _netrc there)
#    machine artifactory.example.com login <user> password <identity-token>
export NETRC="$HOME/.netrc"
export UV_DEFAULT_INDEX="https://artifactory.example.com/artifactory/api/pypi/pypi/simple"

# 3. keyring, for SSO-issued tokens
uv sync --extra login --keyring-provider subprocess
```

Then `uv sync --extra login`. Note that `uv.lock` pins every package to a
`pypi.org` URL, so syncing from a different index rewrites it — leave that churn
out of your commits.

Other things that bite on a corporate network:

```sh
uv --native-tls sync --extra login   # TLS interception: use the OS trust store
uv run --no-sync --extra login playwright install chromium  # skip re-resolution once synced
```

If the mirror does not carry a Playwright new enough for `playwright>=1.44`,
loosen the pin in `pyproject.toml` to whatever it does carry, or skip Playwright's
browser download entirely and drive an installed browser with
`snowq -i acme login --channel chrome` (or `msedge`). `playwright install` pulls
browser binaries from `cdn.playwright.dev`, not from the package index — that host
is a separate firewall rule, so set `PLAYWRIGHT_DOWNLOAD_HOST` to your internal
mirror or use `--channel`. `snowq -i acme import-browser firefox` needs no
Playwright at all.

### If you cannot reach any index at all

You do not need uv, a virtualenv, or an install. `requests` is the only hard
dependency, and corporate Python builds usually already have it — check with
`python -c "import requests"`. If that works, run straight from the checkout:

```sh
cd snow-query
export PYTHONPATH=src        # this is a src-layout, so the package is not importable without it
python -m snowq -i acme import-cookie   # paste the Cookie header, then Ctrl-D (Ctrl-Z on Windows)
python -m snowq -i acme whoami
python -m snowq -i acme query incident -q 'active=true' -n 5
```

In PowerShell that export is `$env:PYTHONPATH = "src"`.

To get the header:

1. Open the instance in the browser where SSO already has you logged in.
2. `F12` → **Network** tab.
3. `Ctrl+R` to reload — a cached page may show only "provisional headers".
4. Click a request to the instance host itself (`navpage.do`, or anything under
   `/api/now/`) — not one to your IdP or a CDN.
5. **Headers** → **Request Headers** → right-click the `Cookie:` value → Copy value.
6. Save it to `cookie.txt` and redirect it in, which avoids paste and EOF quirks:
   `python -m snowq -i acme import-cookie < cookie.txt`. Delete the file after.

Paste the whole value even if it is long; only well-formed `name=value` pairs are
kept. Do **not** use `document.cookie` from the console — `JSESSIONID` is
`HttpOnly`, so it is missing there and the session will not authenticate.

This skips `login` and `import-browser`, which are the two commands
that need the optional extras; the client scrapes the `g_ck` CSRF token itself, so
a pasted cookie header is enough to read. The session lasts as long as your browser
session does — paste a fresh one when it expires.

### "the SSO session has expired"

snowq raises this whenever a request is redirected off the instance or to a login
page, which covers more than an actually-expired session. If a freshly pasted
cookie header fails straight away, test the cookies without snowq in the way:

```sh
curl -sS -i -H "Cookie: $(tr -d '\r\n' < cookie.txt)" \
  "https://acme.service-now.com/api/now/table/sys_user?sysparm_limit=1" | head -15
```

* **200 and JSON** — the cookies are good, so snowq's headers are the problem.
  The usual cause is a UA-gated instance: copy the `User-Agent` from the same
  devtools request and `export SNOWQ_USER_AGENT="<that string>"`.
* **302 to `login.do` or your IdP** — the cookies are not a working session.
  Either the copied request was to the IdP rather than the instance, or the
  instance host does not match `-i` (check the host in the browser's address bar;
  a vanity domain like `snow.corp.example` is not `corp.service-now.com`).
* **401 with `X-Is-Logged-In: true`** — the cookies are fine. ServiceNow requires
  the CSRF token on REST calls and returns the right one in
  `X-UserToken-Response`; snowq picks that up automatically.
* **401 with `X-Is-Logged-In: false`** — the session is genuinely gone; grab a
  fresh header.

Cookie headers last only as long as the browser session behind them, so expect to
re-paste periodically. `snowq login` avoids that, but needs the `login` extra.

## Getting a session

| Command | When to use it |
|---|---|
| `snowq -i acme login` | **Most reliable.** Opens a browser. You finish SSO/MFA, and snowq captures the cookies and `g_ck`. It uses a persistent profile (`~/.config/snowq/browser-profile`), so the IdP remembers you next time. Add `--channel chrome` or `--channel msedge` if your IdP requires a managed or compliant browser. |
| `snowq -i acme import-browser chrome` | Copies cookies out of a browser where you're already logged in (needs the `browser` extra). Works with Firefox everywhere and with Chrome on Linux/macOS. Chrome and Edge on Windows use app-bound cookie encryption, which blocks this. |
| `snowq -i acme import-cookie` | Fallback. In devtools, go to Network, pick any request to the instance, copy the `Cookie` request header, and paste it on stdin. |

`-i` accepts `acme`, `acme.service-now.com`, or a full URL for custom domains. You can also set `SNOWQ_INSTANCE`.

## Querying

```sh
export SNOWQ_INSTANCE=acme

snowq whoami
snowq query incident -q "active=true^priority=1" -f number,short_description,state,assigned_to \
      -d true --order-by -sys_created_on -n 20 -o table
snowq query change_request -q "start_date>=javascript:gs.beginningOfToday()" -n 0 -o csv > changes.csv
snowq get incident 9d385017c611228701d22104cc95c371 -d all
snowq count incident -q "active=true"
snowq raw /api/now/table/sys_user_group -p sysparm_limit=5 -p sysparm_fields=name
snowq logout
```

`-n 0` fetches every matching record, paging 500 at a time. `-d true` returns display values instead of sys_ids for reference and choice fields. `-d all` returns both.

## Recipes: servers and changes

Encoded-query syntax is the same one the list filter builds, so the fastest way to
write a hard filter is to build it in the UI, right-click the breadcrumb → **Copy
query**, and paste it after `-q`.

### First, learn your instance

Choice values are numbers that differ per instance, and the fields that matter in
a regulated shop are usually custom (`u_`) ones. Ask rather than guess:

```sh
# what do state / risk / type actually mean here?
snowq query sys_choice -q "name=change_request^element=risk" -f value,label -n 0 -o table

# custom fields on the server class — compliance flags tend to live here
snowq query sys_dictionary -q "name=cmdb_ci_server^elementSTARTSWITHu_" \
      -f element,column_label -n 0 -o table
```

### Server inventory

```sh
# full inventory for a patch or audit cycle
snowq query cmdb_ci_server -q "operational_status=1" \
      -f name,os,os_version,ip_address,support_group,owned_by,environment \
      -d true -n 0 -o csv > servers.csv

# CMDB hygiene: live servers with no owner or support group — a recurring audit finding
snowq query cmdb_ci_server -q "operational_status=1^support_groupISEMPTY^ORowned_byISEMPTY" \
      -f name,os,ip_address,sys_updated_on -d true -n 0 -o table

# stale records: not touched by discovery in 90 days, so the CMDB may be lying
snowq query cmdb_ci_server -q "operational_status=1^sys_updated_onRELATIVELT@day@ago@90" \
      -f name,sys_updated_on,discovery_source -d true --order-by sys_updated_on -o table

# one OS family, for an end-of-support campaign
snowq query cmdb_ci_server -q "osLIKEWindows^os_versionLIKE2012" \
      -f name,os_version,environment,support_group -d true -n 0 -o csv
```

### Change management

```sh
# what is scheduled for the next 7 days — CAB prep
snowq query change_request -q "start_dateRELATIVELE@day@ahead@7^active=true" \
      -f number,short_description,type,risk,start_date,assignment_group,cmdb_ci \
      -d true --order-by start_date -n 0 -o table

# emergency changes raised in the last 30 days — the first thing an auditor asks for
snowq query change_request -q "type=emergency^sys_created_onRELATIVEGE@day@ago@30" \
      -f number,short_description,requested_by,approval,start_date,close_code \
      -d true -n 0 -o csv > emergency-changes.csv

# changes that did not land cleanly — change-failure-rate evidence
snowq query change_request -q "close_codeNOT LIKEsuccessful^stateIN3,4^sys_created_onRELATIVEGE@day@ago@90" \
      -f number,short_description,close_code,close_notes,assignment_group \
      -d true -n 0 -o table

# volume by month, without pulling the records
snowq count change_request -q "type=emergency^sys_created_onRELATIVEGE@day@ago@30"
```

### Tying changes to infrastructure

```sh
# every change against one server, newest first
snowq query change_request -q "cmdb_ci.name=PRDAPP001" \
      -f number,type,state,start_date,short_description \
      -d true --order-by -start_date -o table

# affected CIs on a change (task_ci is the many-to-many table; cmdb_ci holds only the primary)
snowq query task_ci -q "task.number=CHG0031234" -f ci_item -d true -n 0 -o table

# changes touching anything in one support group's estate
snowq query change_request -q "cmdb_ci.support_group.name=Core Banking Infrastructure" \
      -f number,cmdb_ci,type,start_date,state -d true -n 0 -o csv
```

Dot-walking works inside `-q` (`cmdb_ci.support_group.name`), which saves joining
exports by hand. `RELATIVEGE@day@ago@30` and `RELATIVELE@day@ahead@7` are relative
date filters — the unit can be `minute`, `hour`, `day`, `week`, `month`, `quarter`
or `year`.

Everything here is read-only and runs as you, so results are already filtered by
your ACLs. A query returning nothing can mean the records do not exist *or* that
you cannot see them; `snowq count` on the same filter tells you which.

## As a library

```python
from snowq import SnowClient
from snowq.auth import load_session

stored = load_session("acme")
snow = SnowClient.from_session(stored)
for inc in snow.table("incident", query="active=true^priority=1", fields=["number", "short_description"], limit=None):
    print(inc["number"], inc["short_description"])
snow.to_session(stored.source).save()   # keep rotated cookies
```

## Tests

```sh
uv run pytest
```

The tests use a fake HTTP adapter, so they don't need an instance.
