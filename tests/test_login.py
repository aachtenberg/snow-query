"""`snowq login` must wait for a real user, not stop at the guest session.

An instance with a local login form serves it from navpage.do on the instance
host, and that page already carries a g_ck for the guest session. Stopping at
the first g_ck captured that guest session before anyone could type.

Playwright is faked here, so these run without the `login` extra installed.
"""

from __future__ import annotations

import sys
import types

import pytest

from snowq import auth

BASE = "https://acme.service-now.com"


class FakeResponse:
    def __init__(self, status: int, body=None):
        self.status = status
        self.ok = 200 <= status < 300
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


class FakeBrowser:
    """Page, context and context.request in one: a local login form at navpage.do.

    It shows a guest g_ck from the first poll; the user is signed in after
    ``signed_in_after`` polls (never, if None).
    """

    def __init__(self, signed_in_after: int | None):
        self.signed_in_after = signed_in_after
        self.polls = 0
        self.url = BASE + "/navpage.do"
        self.pages = [self]
        self.request = self
        self.probes: list[str] = []

    @property
    def signed_in(self) -> bool:
        return self.signed_in_after is not None and self.polls >= self.signed_in_after

    # page
    def goto(self, url):
        self.url = url

    def evaluate(self, js):
        return "user-token" if self.signed_in else "guest-token"

    def wait_for_timeout(self, ms):
        self.polls += 1

    # context
    def cookies(self):
        value = "user" if self.signed_in else "guest"
        return [{"name": "JSESSIONID", "value": value, "domain": "acme.service-now.com",
                 "path": "/", "secure": True, "expires": -1}]

    def close(self):
        pass

    # context.request
    def get(self, url, params=None, headers=None, max_redirects=None):
        self.probes.append(headers["X-UserToken"])
        if headers["X-UserToken"] != "user-token":
            return FakeResponse(401, {"error": {"message": "User Not Authenticated"}})
        return FakeResponse(200, {"result": [{"user_name": "someone"}]})


@pytest.fixture
def browser(monkeypatch):
    def install(signed_in_after):
        fake = FakeBrowser(signed_in_after)

        class Playwright:
            def __init__(self):
                self.chromium = self

            def launch_persistent_context(self, *args, **kwargs):
                return fake

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        sync_api = types.ModuleType("playwright.sync_api")
        sync_api.sync_playwright = Playwright
        package = types.ModuleType("playwright")
        package.sync_api = sync_api
        monkeypatch.setitem(sys.modules, "playwright", package)
        monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
        # One "second" per poll, so the timeout is counted in polls.
        monkeypatch.setattr(auth.time, "monotonic", lambda: fake.polls)
        return fake

    return install


def test_login_waits_past_the_guest_token(browser, tmp_path):
    fake = browser(signed_in_after=3)
    stored = auth.login_with_browser(BASE, timeout_s=60, profile_dir=tmp_path)
    assert stored.g_ck == "user-token"
    assert [c["value"] for c in stored.cookies] == ["user"]
    assert fake.probes == ["guest-token"] * 3 + ["user-token"]


def test_login_times_out_if_nobody_signs_in(browser, tmp_path):
    browser(signed_in_after=None)
    with pytest.raises(TimeoutError):
        auth.login_with_browser(BASE, timeout_s=5, profile_dir=tmp_path)


class OneResponse:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error

    def get(self, *args, **kwargs):
        if self.error:
            raise self.error
        return self.response


@pytest.mark.parametrize(
    "request_, expected",
    [
        (OneResponse(FakeResponse(200, {"result": [{"user_name": "someone"}]})), True),
        (OneResponse(FakeResponse(200, {"result": [{"user_name": "guest"}]})), False),
        (OneResponse(FakeResponse(200, {"result": []})), False),
        (OneResponse(FakeResponse(200, None)), False),  # an HTML login page
        (OneResponse(FakeResponse(302, None)), False),  # sent off to the IdP
        (OneResponse(FakeResponse(401, {"error": {}})), False),
        (OneResponse(error=RuntimeError("request torn down by navigation")), False),
    ],
)
def test_signed_in_needs_a_named_user(request_, expected):
    assert auth._signed_in(request_, BASE, "token") is expected
