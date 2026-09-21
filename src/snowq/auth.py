"""Getting and keeping a ServiceNow browser session.

ServiceNow behind SSO (SAML/OIDC) has no password we can hand to the REST API,
but once you've logged in through the browser the instance issues ordinary
session cookies (JSESSIONID, glide_user_route, glide_session_store, ...). Any
HTTP client that presents those cookies — plus the per-session CSRF token
``g_ck`` as the ``X-UserToken`` header — is treated as that logged-in user.

This module gets those cookies from one of three places and saves them to a
per-instance session file (mode 0600) that the client reuses until it expires:

* ``login_with_browser``  — opens a real browser via Playwright, you finish
  SSO/MFA, it captures the cookies and ``g_ck``. The most reliable option.
* ``import_from_browser`` — reads cookies out of an installed browser's cookie
  store with browser_cookie3. Handy, but Chrome/Edge on Windows encrypt
  cookies with app-bound keys that third-party tools can't read.
* ``import_cookie_header`` — paste the ``Cookie:`` request header from devtools.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from http.cookiejar import Cookie
from pathlib import Path
from urllib.parse import urlparse

import requests

CONFIG_DIR = Path(os.environ.get("SNOWQ_HOME", Path.home() / ".config" / "snowq"))


def normalize_instance(instance: str) -> str:
    """Accept ``acme``, ``acme.service-now.com`` or a full URL; return ``https://host``."""
    instance = instance.strip().rstrip("/")
    if "://" not in instance:
        if "." not in instance:
            instance = f"{instance}.service-now.com"
        instance = f"https://{instance}"
    parsed = urlparse(instance)
    return f"{parsed.scheme}://{parsed.netloc}"


def host_of(instance: str) -> str:
    return urlparse(normalize_instance(instance)).hostname or ""


def session_path(instance: str) -> Path:
    return CONFIG_DIR / "sessions" / f"{host_of(instance)}.session.json"


@dataclass
class StoredSession:
    instance: str
    cookies: list[dict]
    g_ck: str | None = None
    source: str = "unknown"
    saved_at: float = field(default_factory=time.time)

    def to_jar(self) -> requests.cookies.RequestsCookieJar:
        jar = requests.cookies.RequestsCookieJar()
        for c in self.cookies:
            jar.set(
                c["name"],
                c["value"],
                domain=c.get("domain") or host_of(self.instance),
                path=c.get("path") or "/",
                secure=c.get("secure", True),
                expires=_expiry(c.get("expires")),
            )
        return jar

    def save(self) -> Path:
        path = session_path(self.instance)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        # Create with 0600 up front so the cookies are never world-readable.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self.__dict__, f, indent=2)
        return path


def _expiry(value) -> int | None:
    # Playwright uses -1 for session cookies; http.cookiejar wants None.
    if value is None or value == -1:
        return None
    return int(value)


def cookies_from_jar(jar) -> list[dict]:
    out = []
    for c in jar:
        c: Cookie
        out.append(
            {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "secure": bool(c.secure),
                "expires": c.expires,
            }
        )
    return out


def load_session(instance: str) -> StoredSession | None:
    path = session_path(instance)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return StoredSession(**data)


def delete_session(instance: str) -> bool:
    path = session_path(instance)
    if path.exists():
        path.unlink()
        return True
    return False


def _cookie_matches(domain: str, host: str) -> bool:
    domain = domain.lstrip(".")
    return host == domain or host.endswith("." + domain)


def import_cookie_header(instance: str, header: str) -> StoredSession:
    """Build a session from a raw ``Cookie:`` header copied out of devtools."""
    header = header.strip()
    if header.lower().startswith("cookie:"):
        header = header.split(":", 1)[1]
    host = host_of(instance)
    cookies = []
    for part in header.split(";"):
        if "=" not in part:
            continue
        name, value = part.strip().split("=", 1)
        cookies.append({"name": name, "value": value, "domain": host, "path": "/", "secure": True})
    if not cookies:
        raise ValueError("no name=value pairs found in cookie header")
    return StoredSession(normalize_instance(instance), cookies, source="cookie-header")


def import_from_browser(instance: str, browser: str = "chrome") -> StoredSession:
    """Read the instance's cookies out of an installed browser profile."""
    try:
        import browser_cookie3
    except ImportError as e:  # pragma: no cover - depends on optional extra
        raise RuntimeError("browser import needs the 'browser' extra: uv sync --extra browser") from e

    loader = getattr(browser_cookie3, browser, None)
    if loader is None:
        raise ValueError(f"unsupported browser {browser!r}")
    host = host_of(instance)
    jar = loader(domain_name=host)
    cookies = [c for c in cookies_from_jar(jar) if _cookie_matches(c["domain"], host)]
    if not cookies:
        raise RuntimeError(
            f"no {host} cookies found in {browser}. Log in to the instance in that browser first, "
            "or use `snowq login` instead."
        )
    return StoredSession(normalize_instance(instance), cookies, source=f"browser:{browser}")


# Polled in the page after SSO: once g_ck exists, the session is fully established.
_G_CK_JS = "() => (window.g_ck || (window.NOW && window.NOW.g_ck) || null)"


def login_with_browser(
    instance: str,
    channel: str | None = None,
    timeout_s: int = 300,
    profile_dir: Path | None = None,
) -> StoredSession:
    """Open a browser at the instance, wait for you to finish SSO, capture the session.

    ``channel`` picks an installed browser ("chrome", "msedge") instead of
    Playwright's bundled Chromium — use it when your IdP requires a managed
    browser for device trust or Kerberos/IWA. ``profile_dir`` keeps a
    persistent profile so the IdP remembers you between logins.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "browser login needs the 'login' extra: uv sync --extra login && "
            "uv run --extra login playwright install chromium"
        ) from e

    base = normalize_instance(instance)
    host = host_of(base)
    profile_dir = profile_dir or CONFIG_DIR / "browser-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(profile_dir), headless=False, channel=channel, no_viewport=True
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(f"{base}/navpage.do")
            deadline = time.monotonic() + timeout_s
            g_ck = None
            while time.monotonic() < deadline:
                if urlparse(page.url).hostname == host:
                    try:
                        g_ck = page.evaluate(_G_CK_JS)
                    except Exception:
                        g_ck = None  # page mid-navigation
                    if g_ck:
                        break
                page.wait_for_timeout(1000)
            if not g_ck:
                raise TimeoutError(f"login not completed within {timeout_s}s")
            cookies = [
                {k: c[k] for k in ("name", "value", "domain", "path", "secure", "expires")}
                for c in ctx.cookies()
                if _cookie_matches(c["domain"], host)
            ]
        finally:
            ctx.close()

    return StoredSession(base, cookies, g_ck=g_ck, source=f"login:{channel or 'chromium'}")
