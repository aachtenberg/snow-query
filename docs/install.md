# Installing behind a private index

The normal install is two commands ([README](../README.md#install)). This page is
for corporate networks where pypi.org is blocked and packages come from
Artifactory or a similar mirror.

## uv does not read `pip.conf` / `pip.ini`

If your machine is set up for a private index through pip's config, pip works and
uv quietly falls back to pypi.org — which a corporate network usually blocks. uv
only takes an index from `uv.toml`, `[tool.uv]` in `pyproject.toml`, `UV_*`
environment variables, or the command line.

Either way — no index configured, or one configured but unauthenticated — uv gets
nothing back and reports the package as *missing* rather than unreachable:

```
error: No solution found when resolving dependencies
  cause: Because requests was not found in the package registry and your project
         depends on requests>=2.25, we can conclude that your project's
         requirements are unsatisfiable.
```

That is an index problem, not a version problem. `requests` is on every mirror; if
uv cannot find it, it is not reaching an index it can read. Start by copying pip's
index URL over:

```sh
echo "$PIP_INDEX_URL"  # `pip config list` shows config FILES only, not env vars
pip config debug       # this one does include the environment-variable section
uv sync --extra login --index "$PIP_INDEX_URL"
```

`--index` puts that URL at the front of the search order — above `--default-index`
and above anything in `uv.toml` — so it is the reliable way to test a URL before
making it permanent. If pip works and uv does not, this is nearly always why: the
index lives in `PIP_INDEX_URL`, which configures pip and nothing else.

If that URL carries no credentials, authenticate it.

## Check which Artifactory repo the URL names

A `*-local` repo holds only what your own organisation publishes — it does not
proxy pypi.org, so third-party packages are legitimately absent and uv reports
them as not found:

```
DEBUG Sending fresh GET request for:
      https://artifactory.example.com/artifactory/api/pypi/pypi-local/simple/requests/
```

Third-party packages come from a `*-remote` proxy repo, or from the *virtual* repo
that aggregates local and remote. Swap the repo segment and probe it:

```sh
for repo in pypi pypi-virtual pypi-remote pypi-local; do
  printf '%-16s -> ' "$repo"
  curl -sS -o /dev/null -w '%{http_code}\n' \
    "https://artifactory.example.com/artifactory/api/pypi/$repo/simple/requests/"
done
```

`uv sync -v` prints every URL it requests, which is the fastest way to see what
index you are actually hitting. Expect it to also log `Resolving despite existing
lockfile due to missing remote index` — that is the lockfile churn described below.

## Authenticating

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

## Other things that bite

```sh
uv --native-tls sync --extra login   # TLS interception: use the OS trust store
uv run --no-sync --extra login playwright install chromium  # skip re-resolution once synced
```

If the mirror does not carry a Playwright new enough for `playwright>=1.44`, loosen
the pin in `pyproject.toml` to whatever it does carry, or skip Playwright's browser
download entirely and drive an installed browser with
`snowq -i acme login --channel chrome` (or `msedge`). `playwright install` pulls
browser binaries from `cdn.playwright.dev`, not from the package index — that host
is a separate firewall rule, so set `PLAYWRIGHT_DOWNLOAD_HOST` to your internal
mirror or use `--channel`. `snowq -i acme import-browser firefox` needs no
Playwright at all.

## If you cannot reach any index at all

You do not need uv, a virtualenv, or an install. `requests` is the only hard
dependency, and corporate Python builds usually already have it — check with
`python -c "import requests"`. If that works, run straight from the checkout:

The `./snowq` wrapper at the repo root does this for you — it picks an
interpreter that has `requests`, sets the path, and reports what is missing:

```sh
cd snow-query
./snowq doctor
./snowq -i acme import-cookie < cookie.txt
./snowq -i acme query incident -q 'active=true' -n 5
```

It is POSIX `sh`, so on Windows run it from Git Bash. By hand it is:

```sh
export PYTHONPATH=src        # src-layout; without this you get "No module named snowq"
python -m snowq -i acme import-cookie   # paste the Cookie header, then Ctrl-D (Ctrl-Z on Windows)
python -m snowq -i acme whoami
```

In PowerShell that export is `$env:PYTHONPATH = "src"`.

This skips `login` and `import-browser`, which are the two commands that need the
optional extras. See [Sessions](sessions.md#capturing-the-cookie-header) for how to
copy the `Cookie` header out of devtools.
