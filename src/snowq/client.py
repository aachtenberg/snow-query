"""A thin REST client that rides a browser session instead of API credentials."""

from __future__ import annotations

import os
import re
from typing import Any, Iterator
from urllib.parse import urlparse

import requests

from .auth import StoredSession, cookies_from_jar, normalize_instance

# UI pages that embed the session's CSRF token, tried in order. navpage.do is
# the classic UI frame; the Next Experience shell sets window.g_ck too.
_TOKEN_PAGES = ("/navpage.do", "/now/nav/ui/home", "/home.do")
_G_CK_RE = re.compile(r"""g_ck\s*[=:]\s*['"]([A-Za-z0-9]{20,})['"]""")
_DEFAULT_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) snowq"
_LOGIN_MARKERS = ("login.do", "saml", "sso", "oauth", "logout", "auth_redirect", "external_login")


class SessionExpired(RuntimeError):
    """The browser session is gone; log in again."""


def extract_g_ck(html: str) -> str | None:
    m = _G_CK_RE.search(html)
    return m.group(1) if m else None


class SnowClient:
    def __init__(
        self,
        instance: str,
        cookies: requests.cookies.RequestsCookieJar,
        g_ck: str | None = None,
        timeout: float = 60,
    ):
        self.base = normalize_instance(instance)
        self.host = urlparse(self.base).hostname
        self.timeout = timeout
        self.g_ck = g_ck
        self.http = requests.Session()
        self.http.cookies = cookies
        self.http.headers.update(
            {
                "Accept": "application/json",
                # Some instances gate API access on looking like the browser that owns
                # the session. If yours bounces a valid cookie straight to the login
                # page, copy the User-Agent from the same devtools request that gave
                # you the cookies and set $SNOWQ_USER_AGENT to it.
                "User-Agent": os.environ.get("SNOWQ_USER_AGENT") or _DEFAULT_UA,
            }
        )

    @classmethod
    def from_session(cls, stored: StoredSession, **kw) -> "SnowClient":
        return cls(stored.instance, stored.to_jar(), g_ck=stored.g_ck, **kw)

    def to_session(self, source: str) -> StoredSession:
        """Snapshot the (possibly rotated) cookies so the next run reuses them."""
        return StoredSession(self.base, cookies_from_jar(self.http.cookies), g_ck=self.g_ck, source=source)

    # --- token -----------------------------------------------------------------

    def refresh_token(self) -> str:
        """Scrape g_ck from a UI page. Raises SessionExpired if we get bounced to login."""
        for path in _TOKEN_PAGES:
            r = self.http.get(self.base + path, timeout=self.timeout, headers={"Accept": "text/html"})
            self._raise_if_bounced(r)
            token = extract_g_ck(r.text)
            if token:
                self.g_ck = token
                return token
        raise SessionExpired(
            "could not find g_ck on any UI page — the session is probably no longer logged in"
        )

    def _raise_if_bounced(self, r: requests.Response) -> None:
        # A dead session gets redirected to the login page or the IdP rather than a 401.
        hops = [h.url for h in r.history] + [r.url]
        for url in hops:
            parsed = urlparse(url)
            if parsed.hostname != self.host or any(m in parsed.path.lower() for m in _LOGIN_MARKERS):
                raise SessionExpired(f"redirected to {url}; the SSO session has expired")
        if r.status_code == 401:
            raise SessionExpired("401 Unauthorized; the SSO session has expired")

    # --- requests ---------------------------------------------------------------

    def request(self, method: str, path: str, **kw) -> requests.Response:
        if not self.g_ck:
            self.refresh_token()
        url = path if path.startswith("http") else self.base + path
        for attempt in (1, 2):
            r = self.http.request(
                method,
                url,
                headers={"X-UserToken": self.g_ck, **kw.pop("headers", {})},
                timeout=self.timeout,
                allow_redirects=False,
                **kw,
            )
            if r.is_redirect:
                raise SessionExpired(f"redirected to {r.headers.get('Location')}; the SSO session has expired")
            # A stale g_ck (e.g. after the instance rotated it) shows up as a 401 with
            # live cookies; re-scrape once before giving up.
            if r.status_code == 401 and attempt == 1:
                self.refresh_token()
                continue
            if r.status_code == 401:
                raise SessionExpired("401 Unauthorized; the SSO session has expired")
            if "json" not in r.headers.get("Content-Type", ""):
                raise SessionExpired(
                    f"expected JSON from {path}, got {r.headers.get('Content-Type')!r} — "
                    "probably a login page"
                )
            if not r.ok:
                raise RuntimeError(f"{method} {path} -> {r.status_code}: {_error_message(r)}")
            return r
        raise AssertionError("unreachable")

    def get_json(self, path: str, params: dict | None = None) -> Any:
        return self.request("GET", path, params=params).json()

    # --- APIs -------------------------------------------------------------------

    def table(
        self,
        table: str,
        query: str | None = None,
        fields: list[str] | None = None,
        limit: int | None = 100,
        display_value: str | bool = False,
        page_size: int = 500,
        order_by: str | None = None,
    ) -> Iterator[dict]:
        """Yield records from the Table API, paging until ``limit`` (None = all)."""
        sysparm_query = query or ""
        if order_by:
            desc = order_by.startswith("-")
            clause = f"ORDERBY{'DESC' if desc else ''}{order_by.lstrip('-')}"
            sysparm_query = f"{sysparm_query}^{clause}" if sysparm_query else clause
        offset = 0
        yielded = 0
        while limit is None or yielded < limit:
            n = page_size if limit is None else min(page_size, limit - yielded)
            params = {
                "sysparm_limit": n,
                "sysparm_offset": offset,
                "sysparm_display_value": str(display_value).lower(),
                "sysparm_exclude_reference_link": "true",
            }
            if sysparm_query:
                params["sysparm_query"] = sysparm_query
            if fields:
                params["sysparm_fields"] = ",".join(fields)
            rows = self.get_json(f"/api/now/table/{table}", params)["result"]
            yield from rows
            yielded += len(rows)
            offset += len(rows)
            if len(rows) < n:
                return

    def get_record(self, table: str, sys_id: str, fields: list[str] | None = None, display_value=False) -> dict:
        params = {"sysparm_display_value": str(display_value).lower(), "sysparm_exclude_reference_link": "true"}
        if fields:
            params["sysparm_fields"] = ",".join(fields)
        return self.get_json(f"/api/now/table/{table}/{sys_id}", params)["result"]

    def count(self, table: str, query: str | None = None) -> int:
        params = {"sysparm_count": "true"}
        if query:
            params["sysparm_query"] = query
        result = self.get_json(f"/api/now/stats/{table}", params)["result"]
        return int(result["stats"]["count"])

    def whoami(self) -> dict:
        rows = list(
            self.table(
                "sys_user",
                query="sys_id=javascript:gs.getUserID()",
                fields=["sys_id", "user_name", "name", "email", "title", "department"],
                limit=1,
                display_value=True,
            )
        )
        if not rows:
            raise SessionExpired("session resolved to no user (guest?) — log in again")
        return rows[0]


def _error_message(r: requests.Response) -> str:
    try:
        err = r.json().get("error", {})
        return f"{err.get('message')}: {err.get('detail')}"
    except ValueError:
        return r.text[:300]
