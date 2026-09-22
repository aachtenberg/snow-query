# snowq

[![CI](https://github.com/aachtenberg/snow-query/actions/workflows/ci.yml/badge.svg)](https://github.com/aachtenberg/snow-query/actions/workflows/ci.yml)

Query ServiceNow's REST APIs from Python by reusing the session you get from
logging in through SSO in a browser. No API user, OAuth client, or password.

For the situation where you can read the records perfectly well in the
ServiceNow UI but cannot get at them any other way: no integration user, no
OAuth client approved, and a service-account request measured in weeks. snowq
reads the same records the web UI already shows you, over the same session.

```sh
uv sync --extra login
uv run playwright install chromium   # skip with --channel chrome / msedge

snowq -i acme login                  # finish SSO in the browser that opens
snowq -i acme query incident -q "active=true^priority=1" -n 10 -o table
```

**It is read-only and runs as you**, with your own roles and ACLs: it sees
exactly what you see in the UI, and it cannot create, update or delete anything.
That is the point — it automates the access you already have rather than
granting new access. For unattended or shared automation, ask your ServiceNow
team for a service account instead; [docs/recipes.md](docs/recipes.md) says
where that line falls. Treat the saved session like a password.

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

### If `uv sync` fails, use `./snowq`

```
error: No solution found when resolving dependencies
  cause: Because requests was not found in the package registry ...
```

That means uv reached no index at all, not that the version pin is wrong —
`requests` is on every mirror. You do not need uv, a virtualenv, or an install:
`requests` is the only hard dependency, and corporate Python builds usually
already have it. The `./snowq` wrapper in this repo finds a Python that has it,
puts `src/` on the path, and runs the CLI straight from the checkout:

```sh
./snowq doctor                                    # what is available here
./snowq -i acme import-cookie < cookie.txt
./snowq -i acme whoami
./snowq -i acme query incident -q 'active=true' -n 5 -o table
```

```bat
snowq.cmd doctor
snowq.cmd -i acme import-cookie < cookie.txt
```

`doctor` prints which interpreter it picked, which optional extras are present,
and whether you have a saved session. The wrapper prefers a synced `.venv` when
there is one, so the same command keeps working after a successful install.

On a blocked index reach for `import-cookie`, not `login` — `login` drives
Playwright, which is the thing that would not install. The wrapper says so up
front instead of failing deep inside the login flow.
[docs/sessions.md](docs/sessions.md#capturing-the-cookie-header) has the devtools
steps for `cookie.txt`; [docs/install.md](docs/install.md) covers pointing uv at
your real index.

`./snowq` is POSIX `sh` (Git Bash on Windows); `snowq.cmd` is the same thing for
`cmd` and PowerShell. Without either, the equivalent is `export PYTHONPATH=src`
(`$env:PYTHONPATH = "src"` in PowerShell) followed by `python -m snowq ...` —
skipping that export is what produces `No module named snowq`.

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

`-o` picks the shape: `json` (default), `jsonl` for streaming into `jq`, `csv` for
a spreadsheet, and `table` for reading in the terminal.

A ServiceNow table answers with every field it has — `incident` is around 150,
most of them empty custom ones — so **`-f` is what makes a table readable**:

```sh
snowq query incident -q 'active=true' -n 5 -o table \
      -f number,short_description,state,assigned_to -d true
```

Without `-f`, `table` will not print all 150: it drops the fields that are empty
in every row, leads with the ones that identify a record (`number`, `state`,
`assigned_to`, …), keeps what fits one line, and tells you on stderr how many it
held back. `csv` and `json` are unfiltered either way, so exports keep every
field. The row count also goes to stderr, so `... -o table 2>/dev/null` leaves
just the table.

The `-q` encoded-query syntax is what the UI list filter builds — build the filter
there, right-click the breadcrumb → **Copy query**, and paste it. Dot-walking works
too (`cmdb_ci.support_group.name=Unix Platform Engineering`).

**[docs/recipes.md](docs/recipes.md)** has worked examples: incident queues by
assignment group, backlog counts per team, server inventory, CMDB hygiene, CAB
prep, emergency-change audits, and scheduled CSV exports via
`examples/export.py`.

## For coding agents

**[AGENTS.md](AGENTS.md)** is the guidance for LLM-driven use: encoded-query
syntax, the flags that decide whether output is usable, exit-code handling, and
the rule that matters most — discover field and choice values from the instance
rather than guessing them, because a customised instance answers a wrong guess
with an empty result rather than an error.

Every assistant looks for its own filename, so the shared core of that file is
generated into each one — Claude Code (`CLAUDE.md`, plus a skill under
`.claude/skills/`), Copilot (`.github/copilot-instructions.md`), Cursor
(`.cursor/rules/`), Windsurf, Cline and Continue. Edit `AGENTS.md`, then:

```sh
python util/gen_agent_docs.py           # regenerate
python util/gen_agent_docs.py --check   # CI: fail if one drifted
```

`uv run pytest` runs that check, because a stale copy still teaches the rule
that changed.

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
