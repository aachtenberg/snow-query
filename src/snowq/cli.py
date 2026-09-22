"""snowq — query ServiceNow with your SSO browser session.

    snowq -i acme login                 # finish SSO in the browser that opens
    snowq -i acme whoami
    snowq -i acme query incident -q "active=true^priority=1" -f number,short_description,state -o table
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys

import requests

from . import auth
from .client import SessionExpired, SnowClient


def _csv_list(value: str | None) -> list[str] | None:
    return [f.strip() for f in value.split(",") if f.strip()] if value else None


def _display_value(value: str) -> str | bool:
    return {"true": True, "false": False, "all": "all"}[value]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="snowq", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "-i",
        "--instance",
        default=os.environ.get("SNOWQ_INSTANCE"),
        help="instance name, host or URL (default: $SNOWQ_INSTANCE)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("login", help="log in through a real browser (SSO/MFA) and save the session")
    s.add_argument("--channel", help="installed browser to drive instead of bundled Chromium: chrome, msedge")
    s.add_argument("--timeout", type=int, default=300, help="seconds to wait for you to finish logging in")

    s = sub.add_parser("import-browser", help="copy the session cookies out of an installed browser")
    s.add_argument("browser", nargs="?", default="chrome", help="chrome, firefox, edge, brave, chromium, ...")

    s = sub.add_parser("import-cookie", help="save a Cookie header copied from devtools (reads stdin if omitted)")
    s.add_argument("header", nargs="?")

    sub.add_parser("logout", help="delete the saved session")
    sub.add_parser("whoami", help="show the user the session belongs to")

    s = sub.add_parser("query", help="query a table via the Table API")
    s.add_argument("table")
    s.add_argument("-q", "--query", help="encoded query, e.g. 'active=true^priority=1'")
    s.add_argument("-f", "--fields", help="comma-separated fields to return")
    s.add_argument("-n", "--limit", type=int, default=100, help="max records (0 = no limit; default 100)")
    s.add_argument("--order-by", help="field to sort by; prefix with - for descending")
    s.add_argument("-d", "--display-value", choices=["true", "false", "all"], default="false")
    s.add_argument("-o", "--output", choices=["json", "jsonl", "table", "csv"], default="json")

    s = sub.add_parser("get", help="fetch one record by sys_id")
    s.add_argument("table")
    s.add_argument("sys_id")
    s.add_argument("-f", "--fields")
    s.add_argument("-d", "--display-value", choices=["true", "false", "all"], default="false")

    s = sub.add_parser("count", help="count records matching a query (Aggregate API)")
    s.add_argument("table")
    s.add_argument("-q", "--query")

    s = sub.add_parser("raw", help="GET any REST path, e.g. /api/now/table/sys_user?sysparm_limit=1")
    s.add_argument("path")
    s.add_argument("-p", "--param", action="append", default=[], metavar="KEY=VALUE")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.instance:
        print("snowq: pass --instance or set SNOWQ_INSTANCE", file=sys.stderr)
        return 2
    try:
        return _run(args)
    except SessionExpired as e:
        print(f"snowq: {e}\n  run: snowq -i {args.instance} login", file=sys.stderr)
        return 3
    except requests.RequestException as e:
        # Corporate networks are the usual cause: a proxy that needs HTTPS_PROXY
        # set, or TLS interception that needs REQUESTS_CA_BUNDLE.
        print(f"snowq: could not reach {args.instance}: {e.__class__.__name__}", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        return 4
    except (RuntimeError, ValueError, TimeoutError) as e:
        print(f"snowq: {e}", file=sys.stderr)
        return 1


def _run(args) -> int:
    inst = args.instance

    if args.cmd in ("login", "import-browser", "import-cookie"):
        if args.cmd == "login":
            stored = auth.login_with_browser(inst, channel=args.channel, timeout_s=args.timeout)
        elif args.cmd == "import-browser":
            stored = auth.import_from_browser(inst, args.browser)
        else:
            stored = auth.import_cookie_header(inst, args.header or sys.stdin.read())
        client = SnowClient.from_session(stored)
        user = client.whoami()  # prove the session works before saving it
        path = client.to_session(stored.source).save()
        print(f"logged in as {user.get('user_name')} ({user.get('name')}); session saved to {path}", file=sys.stderr)
        return 0

    if args.cmd == "logout":
        print("session deleted" if auth.delete_session(inst) else "no saved session", file=sys.stderr)
        return 0

    stored = auth.load_session(inst)
    if stored is None:
        raise SessionExpired(f"no saved session for {auth.host_of(inst)}")
    client = SnowClient.from_session(stored)
    try:
        _dispatch(client, args)
    finally:
        # Persist rotated cookies / refreshed g_ck so the session lives as long as the browser's would.
        client.to_session(stored.source).save()
    return 0


def _dispatch(client: SnowClient, args) -> None:
    if args.cmd == "whoami":
        _emit_json(client.whoami())
    elif args.cmd == "query":
        rows = client.table(
            args.table,
            query=args.query,
            fields=_csv_list(args.fields),
            limit=args.limit or None,
            display_value=_display_value(args.display_value),
            order_by=args.order_by,
        )
        _emit_rows(rows, args.output, _csv_list(args.fields))
    elif args.cmd == "get":
        _emit_json(
            client.get_record(
                args.table, args.sys_id, _csv_list(args.fields), display_value=_display_value(args.display_value)
            )
        )
    elif args.cmd == "count":
        print(client.count(args.table, args.query))
    elif args.cmd == "raw":
        params = dict(p.split("=", 1) for p in args.param)
        _emit_json(client.get_json(args.path, params or None))


def _emit_json(obj) -> None:
    json.dump(obj, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _cell(value) -> str:
    # display_value=all returns {"value": ..., "display_value": ...}; show the human side.
    if isinstance(value, dict):
        value = value.get("display_value", value.get("value", ""))
    return "" if value is None else str(value)


MAX_COL = 60
COL_GAP = 2
MIN_COL = 8


def _ellipsis() -> str:
    """'…' where the terminal can encode it, '...' on a legacy code page."""
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "\u2026".encode(enc)
    except (UnicodeEncodeError, LookupError):
        return "..."
    return "\u2026"


def _clip(value: str, width: int, ell: str) -> str:
    if len(value) <= width:
        return value
    if width <= len(ell):
        return value[:width]
    return value[: width - len(ell)] + ell


PREFERRED_COLS = (
    "number",
    "name",
    "short_description",
    "state",
    "priority",
    "severity",
    "urgency",
    "assigned_to",
    "assignment_group",
    "caller_id",
    "cmdb_ci",
    "category",
    "opened_at",
    "start_date",
    "close_code",
    "sys_created_on",
    "sys_updated_on",
)


def _auto_columns(cols: list[str], by_col: dict, term: int) -> list[str]:
    """Pick the columns worth showing when the caller gave no -f.

    A ServiceNow table answers with every field it has — incident is ~150,
    most of them empty custom ones — so printing all of them is a wall of
    wrapped text. Drop the columns that are empty in every row, lead with the
    fields that identify a record, and keep only what fits on one line.
    """
    kept = [c for c in cols if any(by_col[c])] or list(cols)
    rank = {name: i for i, name in enumerate(PREFERRED_COLS)}
    kept.sort(key=lambda c: (rank.get(c, len(PREFERRED_COLS)), c))

    chosen: list[str] = []
    used = 0
    for c in kept:
        width = min(MAX_COL, max([len(c)] + [len(v) for v in by_col[c]]))
        cost = width + (COL_GAP if chosen else 0)
        if chosen and used + cost > term:
            break
        chosen.append(c)
        used += cost
    return chosen


def _column_widths(cols: list[str], cells: list[list[str]], term: int | None = None) -> list[int]:
    """Size columns to their content, then shrink the widest until the row fits.

    Without this a wide result wraps in the terminal and the alignment that
    makes a table readable is exactly what is lost.
    """
    widths = [
        min(MAX_COL, max([len(c)] + [len(row[i]) for row in cells]))
        for i, c in enumerate(cols)
    ]
    if not widths:
        return widths
    if term is None:
        term = shutil.get_terminal_size((100, 24)).columns
    budget = term - COL_GAP * (len(widths) - 1)
    while sum(widths) > budget and max(widths) > MIN_COL:
        widths[widths.index(max(widths))] -= 1
    return widths


def _emit_rows(rows, fmt: str, fields: list[str] | None) -> None:
    if fmt == "jsonl":
        for r in rows:
            sys.stdout.write(json.dumps(r, ensure_ascii=False) + "\n")
        return
    rows = list(rows)
    if fmt == "json":
        _emit_json(rows)
        return
    cols = fields or (sorted(rows[0]) if rows else [])
    if fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(cols)
        for r in rows:
            w.writerow([_cell(r.get(c)) for c in cols])
        return
    # table
    by_col = {c: [_cell(r.get(c)).replace("\n", " ") for r in rows] for c in cols}
    term = shutil.get_terminal_size((100, 24)).columns
    shown = cols if fields else _auto_columns(cols, by_col, term)
    cells = [[by_col[c][i] for c in shown] for i in range(len(rows))]
    widths = _column_widths(shown, cells, term=term)
    ell = _ellipsis()

    def line(values) -> str:
        # rstrip so the last column carries no trailing padding
        return "  ".join(_clip(v, w, ell).ljust(w) for v, w in zip(values, widths)).rstrip()

    print(line(shown))
    print("  ".join("-" * w for w in widths).rstrip())
    for row in cells:
        print(line(row))
    if len(shown) < len(cols):
        note = f"({len(rows)} rows; {len(shown)} of {len(cols)} fields — use -f to choose)"
    else:
        note = f"({len(rows)} rows)"
    print(note, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
