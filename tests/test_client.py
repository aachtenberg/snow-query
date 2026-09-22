import json
import os
import stat
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from requests.adapters import BaseAdapter

from snowq import auth, cli
from snowq.client import SessionExpired, SnowClient, extract_g_ck

INSTANCE = "https://acme.service-now.com"


class FakeAdapter(BaseAdapter):
    """Routes requests to a handler(method, path, params, headers) -> (status, headers, body)."""

    def __init__(self, handler):
        super().__init__()
        self.handler = handler
        self.calls = []

    def send(self, request, **kw):
        u = urlparse(request.url)
        params = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.calls.append((request.method, u.path, params, dict(request.headers)))
        status, headers, body = self.handler(request.method, u.path, params, request.headers)
        r = requests.Response()
        r.status_code = status
        r.headers.update(headers)
        r._content = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        r.url = request.url
        r.request = request
        return r

    def close(self):
        pass


def make_client(handler, g_ck=None):
    client = SnowClient(INSTANCE, requests.cookies.RequestsCookieJar(), g_ck=g_ck)
    adapter = FakeAdapter(handler)
    client.http.mount("https://", adapter)
    return client, adapter


JSON = {"Content-Type": "application/json;charset=UTF-8"}
HTML = {"Content-Type": "text/html"}


def test_normalize_instance():
    assert auth.normalize_instance("acme") == INSTANCE
    assert auth.normalize_instance("acme.service-now.com") == INSTANCE
    assert auth.normalize_instance("https://snow.corp.example/nav_to.do?x=1") == "https://snow.corp.example"


def test_extract_g_ck_classic_and_polaris():
    assert extract_g_ck("var g_ck = 'abc123def456abc123def456abc123def456';") == "abc123def456abc123def456abc123def456"
    assert extract_g_ck('window.g_ck = "0123456789abcdef0123456789abcdef";') == "0123456789abcdef0123456789abcdef"
    assert extract_g_ck("<html>no token</html>") is None


def test_token_scraped_and_sent_as_x_usertoken():
    token = "f" * 32

    def handler(method, path, params, headers):
        if path == "/api/now/table/sys_user":  # token probe; this instance withholds it
            return 200, JSON, {"result": []}
        if path == "/navpage.do":
            return 200, HTML, f"<script>var g_ck = '{token}';</script>"
        assert headers["X-UserToken"] == token
        return 200, JSON, {"result": [{"number": "INC1"}]}

    client, _ = make_client(handler)
    assert list(client.table("incident", limit=5)) == [{"number": "INC1"}]


def test_paging_respects_limit_and_order():
    data = [{"n": i} for i in range(7)]

    def handler(method, path, params, headers):
        off, lim = int(params["sysparm_offset"]), int(params["sysparm_limit"])
        return 200, JSON, {"result": data[off : off + lim]}

    client, adapter = make_client(handler, g_ck="t" * 32)
    rows = list(client.table("incident", query="active=true", limit=5, page_size=2, order_by="-sys_created_on"))
    assert [r["n"] for r in rows] == [0, 1, 2, 3, 4]
    assert [c[2]["sysparm_limit"] for c in adapter.calls] == ["2", "2", "1"]
    assert adapter.calls[0][2]["sysparm_query"] == "active=true^ORDERBYDESCsys_created_on"

    client, _ = make_client(handler, g_ck="t" * 32)
    assert len(list(client.table("incident", limit=None, page_size=3))) == 7


def test_redirect_to_idp_is_session_expired():
    def handler(method, path, params, headers):
        return 302, {"Location": "https://login.microsoftonline.com/saml2"}, ""

    client, _ = make_client(handler, g_ck="t" * 32)
    with pytest.raises(SessionExpired):
        list(client.table("incident"))


def test_stale_token_is_rescraped_once():
    state = {"api_calls": 0}

    def handler(method, path, params, headers):
        if path == "/api/now/table/sys_user":  # token probe; this instance withholds it
            return 200, JSON, {"result": []}
        if path == "/navpage.do":
            return 200, HTML, "var g_ck = 'new0000000000000000000000000000';"
        state["api_calls"] += 1
        if headers["X-UserToken"] != "new0000000000000000000000000000":
            return 401, JSON, {"error": {"message": "User Not Authenticated"}}
        return 200, JSON, {"result": {"stats": {"count": "42"}}}

    client, _ = make_client(handler, g_ck="old0000000000000000000000000000")
    assert client.count("incident") == 42
    assert state["api_calls"] == 2


def test_html_response_is_session_expired():
    client, _ = make_client(lambda *a: (200, HTML, "<html>login</html>"), g_ck="t" * 32)
    with pytest.raises(SessionExpired):
        client.count("incident")


def test_cookie_header_import_and_private_save(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "CONFIG_DIR", tmp_path)
    stored = auth.import_cookie_header("acme", "Cookie: JSESSIONID=abc; glide_user_route=glide.xyz")
    assert {c["name"] for c in stored.cookies} == {"JSESSIONID", "glide_user_route"}
    path = stored.save()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    loaded = auth.load_session("acme.service-now.com")
    assert loaded.to_jar().get("JSESSIONID") == "abc"


def test_network_failure_reports_cleanly(monkeypatch, capsys):
    """A dead network should not dump a traceback at the user."""
    import requests

    from snowq import cli

    def boom(*a, **kw):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(cli.auth, "load_session", boom)
    code = cli.main(["-i", "acme", "whoami"])
    assert code == 4
    err = capsys.readouterr().err
    assert "could not reach acme" in err
    assert "Traceback" not in err


def test_user_agent_is_overridable(monkeypatch):
    """Instances that pin the session to a browser UA need the real one."""
    monkeypatch.setenv("SNOWQ_USER_AGENT", "Mozilla/5.0 Edg/141.0.0.0")
    c = SnowClient("acme", requests.cookies.RequestsCookieJar())
    assert c.http.headers["User-Agent"] == "Mozilla/5.0 Edg/141.0.0.0"


def test_token_taken_from_x_usertoken_response_header():
    """A logged-in session gets its token back on an unauthenticated REST call."""
    token = "a" * 32

    def handler(method, path, params, headers):
        if path == "/api/now/table/sys_user":
            hdrs = {**JSON, "X-UserToken-Response": token, "X-Is-Logged-In": "true"}
            return 401, hdrs, {"error": {"message": "User is not authenticated"}}
        assert headers["X-UserToken"] == token
        return 200, JSON, {"result": [{"number": "INC1"}]}

    client, adapter = make_client(handler)
    assert list(client.table("incident", limit=1)) == [{"number": "INC1"}]
    assert "/navpage.do" not in [c[1] for c in adapter.calls]


# --- table rendering -------------------------------------------------------


def test_column_widths_shrink_to_fit_the_terminal():
    cols = ["number", "short_description", "state"]
    cells = [["CHG0031234", "x" * 200, "Scheduled"]]

    wide = cli._column_widths(cols, cells, term=200)
    assert wide[1] == cli.MAX_COL  # never wider than the cap, however big the terminal

    narrow = cli._column_widths(cols, cells, term=60)
    assert sum(narrow) + cli.COL_GAP * (len(narrow) - 1) <= 60
    assert narrow[0] == len("CHG0031234")  # the widest column gives way first


def test_column_widths_stop_at_a_readable_floor():
    cols = ["a", "b"]
    cells = [["x" * 50, "y" * 50]]
    assert min(cli._column_widths(cols, cells, term=4)) == cli.MIN_COL


def test_clip_marks_truncation():
    assert cli._clip("abcdefghij", 5, "…") == "abcd…"
    assert cli._clip("abc", 10, "…") == "abc"
    assert cli._clip("abcdef", 2, "...") == "ab"  # no room for the marker


def test_ellipsis_falls_back_on_a_legacy_code_page(monkeypatch):
    class Out:
        encoding = "cp437"

    monkeypatch.setattr(cli.sys, "stdout", Out())
    assert cli._ellipsis() == "..."


def test_table_rows_carry_no_trailing_padding(capsys):
    rows = [{"number": "CHG1", "state": "Closed"}, {"number": "CHG2", "state": "Open"}]
    cli._emit_rows(rows, "table", ["number", "state"])
    out = capsys.readouterr().out.splitlines()
    assert all(line == line.rstrip() for line in out)
    assert out[0].split() == ["number", "state"]


def test_auto_columns_drops_empty_and_leads_with_identifiers():
    rows = [{"number": "INC1", "short_description": "disk full", "u_blank": "", "sys_id": "abc"}]
    cols = sorted(rows[0])
    by_col = {c: [str(r.get(c, "")) for r in rows] for c in cols}

    chosen = cli._auto_columns(cols, by_col, term=200)
    assert "u_blank" not in chosen  # empty in every row
    assert chosen[0] == "number"  # identifiers lead, not alphabetical order


def test_auto_columns_keeps_one_line_worth():
    rows = [{f"u_field_{i:03d}": "x" * 20 for i in range(150)}]
    cols = sorted(rows[0])
    by_col = {c: [str(r.get(c, "")) for r in rows] for c in cols}

    chosen = cli._auto_columns(cols, by_col, term=100)
    assert 0 < len(chosen) < 10  # not all 150
    width = sum(min(cli.MAX_COL, len(by_col[c][0])) for c in chosen)
    assert width + cli.COL_GAP * (len(chosen) - 1) <= 100


def test_explicit_fields_are_never_dropped(capsys):
    rows = [{"number": "INC1", "u_blank": "", "state": "2"}]
    cli._emit_rows(rows, "table", ["number", "u_blank", "state"])
    out = capsys.readouterr()
    assert out.out.splitlines()[0].split() == ["number", "u_blank", "state"]
    assert "use -f" not in out.err


def test_unfiltered_table_says_how_many_fields_it_hid(capsys):
    rows = [dict({"number": "INC1"}, **{f"u_{i:03d}": "y" * 30 for i in range(60)})]
    cli._emit_rows(rows, "table", None)
    err = capsys.readouterr().err
    assert "use -f to choose" in err
    assert "of 61 fields" in err


def test_csv_still_emits_every_field(capsys):
    rows = [{"number": "INC1", "u_blank": "", "state": "2"}]
    cli._emit_rows(rows, "csv", None)
    assert capsys.readouterr().out.splitlines()[0] == "number,state,u_blank"
