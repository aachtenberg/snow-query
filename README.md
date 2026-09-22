# snowq

Query ServiceNow's REST APIs from Python by reusing the session you get from
logging in through SSO in a browser. No API user, OAuth client, or password.

```sh
uv sync --extra login
uv run playwright install chromium   # skip with --channel chrome / msedge

snowq -i acme login                  # finish SSO in the browser that opens
snowq -i acme query incident -q "active=true^priority=1" -n 10 -o table
```

Everything runs as **you**, with your roles and ACLs. Treat the saved session like
a password.

## How it works

After an SSO (SAML/OIDC) login the instance sets ordinary session cookies
(`JSESSIONID`, `glide_user_route`, …). ServiceNow accepts those on its REST
endpoints as long as the request also sends the session's CSRF token, `g_ck`, in
the `X-UserToken` header. snowq collects the cookies, picks up `g_ck` (from the
login capture, the `X-UserToken-Response` header, or `/navpage.do`), calls
`/api/now/...` with both, and saves rotated cookies to
`~/.config/snowq/sessions/<host>.session.json` for the next run.

When the session expires, snowq exits with code 3 and tells you to log in again.

## Install

```sh
uv sync --extra login                 # or --extra all to include browser-cookie import
uv run --extra login playwright install chromium
```

`uv run` re-syncs first and drops extras unless you name them, so `uv run
playwright ...` without `--extra login` uninstalls Playwright and then fails.

Behind Artifactory or another private index, see
**[docs/install.md](docs/install.md)** — uv ignores `pip.conf`, which is the usual
reason a working pip and a failing `uv sync` sit side by side.

### If `uv sync` fails, skip the install

```
error: No solution found when resolving dependencies
  cause: Because requests was not found in the package registry ...
```

That means uv reached no index at all, not that the version pin is wrong —
`requests` is on every mirror. You do not need uv, a virtualenv, or an install to
use snowq: `requests` is the only hard dependency, and corporate Python builds
usually already have it.

```sh
cd snow-query
export PYTHONPATH=src        # src-layout; without this you get "No module named snowq"
python -m snowq -i acme import-cookie < cookie.txt
python -m snowq -i acme whoami
```

In PowerShell that export is `$env:PYTHONPATH = "src"`.

Use `import-cookie` here, not `login` — `login` drives Playwright, which is the
thing you could not install. See
[docs/sessions.md](docs/sessions.md#capturing-the-cookie-header) for how to copy
`cookie.txt` out of devtools, and [docs/install.md](docs/install.md) for pointing
uv at your real index once you want the full install.

## Getting a session

| Command | When to use it |
|---|---|
| `snowq -i acme login` | **Most reliable.** Opens a browser, you finish SSO/MFA, snowq captures the session. |
| `snowq -i acme import-browser chrome` | Copies cookies from a browser you're already logged into (needs the `browser` extra). |
| `snowq -i acme import-cookie` | Fallback: paste the `Cookie` request header from devtools. Needs no extras. |

`-i` accepts `acme`, `acme.service-now.com`, or a full URL. You can also set
`SNOWQ_INSTANCE`. Details, and what to do when a session is rejected, are in
**[docs/sessions.md](docs/sessions.md)**.

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

`-n 0` fetches every matching record, paging 500 at a time. `-d true` returns
display values instead of sys_ids for reference and choice fields; `-d all` returns
both.

The `-q` encoded-query syntax is what the UI list filter builds — build the filter
there, right-click the breadcrumb → **Copy query**, and paste it. Dot-walking works
too (`cmdb_ci.support_group.name=Unix Platform Engineering`).

**[docs/recipes.md](docs/recipes.md)** has worked examples for server inventory,
CMDB hygiene, CAB prep, emergency-change audits, and scheduled CSV exports via
`examples/export.py`.

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
