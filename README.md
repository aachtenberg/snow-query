# snowq

Query ServiceNow's REST APIs from Python by reusing the session you get from logging in through SSO in a browser. You don't need an API user, OAuth client, or password.

## How it works

Once you finish an SSO (SAML/OIDC) login, the instance sets ordinary session cookies (`JSESSIONID`, `glide_user_route`, `glide_session_store`, …). ServiceNow accepts those cookies on its REST endpoints as long as the request also sends the session's CSRF token, `g_ck`, in the `X-UserToken` header. snowq:

1. gets the cookies (see below),
2. scrapes `g_ck` from a UI page (`/navpage.do`), unless it already captured it at login,
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
pip config list        # look for index-url / global.index-url
export UV_DEFAULT_INDEX="<that URL>"
uv sync --extra login
```

If that URL carries no credentials, authenticate it.

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

In PowerShell that export is `$env:PYTHONPATH = "src"`. To get the header: open
the instance in the browser where you are already logged in, DevTools → Network →
click any request to the instance → Request Headers → copy the whole `Cookie:`
line. This skips `login` and `import-browser`, which are the two commands
that need the optional extras; the client scrapes the `g_ck` CSRF token itself, so
a pasted cookie header is enough to read. The session lasts as long as your browser
session does — paste a fresh one when it expires.

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
