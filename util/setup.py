#!/usr/bin/env python3
"""Install everything snowq needs, in one command.

    python3 util/setup.py               # venv, the login extra, Playwright's Chromium
    python3 util/setup.py --all         # also browser-cookie3, for import-browser
    python3 util/setup.py --no-browser  # skip the Chromium download
    python3 util/setup.py --with-deps   # Linux: also Chromium's system libraries (sudo)

On Windows, run it as ``python util\\setup.py``.

It is stdlib-only, so it runs on any Python 3.9+ before anything is installed,
and it shells out to uv for the rest. uv takes its package index from
UV_DEFAULT_INDEX or uv.toml, not pip.conf; behind a private index, set that
up first (docs/install.md).

Pass --no-browser when cdn.playwright.dev is blocked, or when you will log in
with ``snowq login --channel chrome`` (or ``msedge``), which drives a browser
that is already installed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = os.name == "nt"
WRAPPER = "snowq.cmd" if WINDOWS else "./snowq"

# On Linux, `playwright install` succeeds even when the system libraries that
# Chromium needs are missing; only the launch fails. Launch it here, not at the
# end of someone's first SSO login.
LAUNCH_CHECK = (
    "from playwright.sync_api import sync_playwright\n"
    "with sync_playwright() as p:\n"
    "    p.chromium.launch().close()\n"
)


def run(cmd: list[str], shown: str | None = None) -> int:
    # Echo the program by name ("uv", not /home/.../uv.exe), run it by full path.
    print("\n+ " + (shown or " ".join([Path(cmd[0]).stem, *cmd[1:]])), flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def fail(*lines: str) -> int:
    print(file=sys.stderr)
    for line in lines:
        print(line, file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Install snowq's dependencies into .venv.")
    ap.add_argument("--all", action="store_true", help="also install browser-cookie3, for import-browser")
    ap.add_argument(
        "--no-browser",
        action="store_true",
        help="skip downloading Playwright's Chromium (log in with --channel chrome or msedge)",
    )
    ap.add_argument(
        "--with-deps",
        action="store_true",
        help="also install Chromium's system libraries (Linux; runs apt through sudo)",
    )
    args = ap.parse_args(argv)

    uv = shutil.which("uv")
    if not uv:
        return fail(
            "setup: uv is not on PATH. Install it from https://docs.astral.sh/uv/, then rerun.",
            f"  No package index at all? Skip setup: {WRAPPER} doctor, then import-cookie.",
        )

    extra = "all" if args.all else "login"
    if run([uv, "sync", "--extra", extra]):
        return fail(
            "setup: uv sync failed.",
            "  'requests was not found in the package registry' means uv reached no",
            "  package index, not that a version is wrong. See docs/install.md.",
        )

    if not args.no_browser:
        install = [uv, "run", "--no-sync", "playwright", "install"]
        if args.with_deps:
            install.append("--with-deps")
        install.append("chromium")
        if run(install):
            return fail(
                "setup: downloading Chromium failed.",
                "  It comes from cdn.playwright.dev, not the package index. Set",
                "  PLAYWRIGHT_DOWNLOAD_HOST to an internal mirror, or rerun with",
                "  --no-browser and log in with --channel chrome (or msedge).",
            )
        launch = [uv, "run", "--no-sync", "python", "-c", LAUNCH_CHECK]
        if run(launch, shown="launch Chromium headless and close it"):
            return fail(
                "setup: Chromium installed but will not start.",
                "  On Linux this is usually missing system libraries: rerun with",
                "  --with-deps (uses sudo), or use --no-browser and --channel chrome.",
            )

    doctor = ["cmd", "/c", "snowq.cmd", "doctor"] if WINDOWS else ["sh", "./snowq", "doctor"]
    if run(doctor):
        return fail("setup: the wrapper's doctor check failed; see above.")

    login = f"{WRAPPER} -i <instance> login"
    if args.no_browser:
        login += " --channel chrome"
    print(f"\nsetup: done. Get a session with:\n  {login}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
