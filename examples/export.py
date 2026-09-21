#!/usr/bin/env python3
"""Export a fixed set of ServiceNow queries to timestamped CSV files.

This replaces the periodic "open the list view, apply the filter, right-click
the header, Export > CSV" routine: define each pull once in EXPORTS below, then
run this on whatever schedule the recipients need.

    PYTHONPATH=src python examples/export.py -i acme -o ./exports

Every run writes <name>-YYYY-MM-DD.csv, so successive runs are diffable and you
keep a dated audit trail rather than overwriting last month's file. Exit codes:
0 all exports succeeded, 3 the session expired, 4 the instance was unreachable,
1 one or more exports failed (the rest still ran).
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

import requests

from snowq import SnowClient
from snowq.auth import host_of, load_session
from snowq.client import SessionExpired

# Each entry becomes one CSV. `fields` is also the column order.
EXPORTS = [
    {
        "name": "servers",
        "table": "cmdb_ci_server",
        "query": "operational_status=1",
        "fields": [
            "name", "sys_class_name", "os", "os_version", "ip_address",
            "environment", "support_group", "owned_by", "sys_updated_on",
        ],
    },
    {
        "name": "servers-missing-owner",
        "table": "cmdb_ci_server",
        "query": "operational_status=1^support_groupISEMPTY^ORowned_byISEMPTY",
        "fields": ["name", "os", "ip_address", "support_group", "owned_by", "sys_updated_on"],
    },
    {
        "name": "changes-last-30-days",
        "table": "change_request",
        "query": "sys_created_onRELATIVEGE@day@ago@30",
        "fields": [
            "number", "type", "state", "risk", "short_description",
            "assignment_group", "cmdb_ci", "start_date", "end_date", "close_code",
        ],
    },
]


def export_one(snow: SnowClient, spec: dict, out_dir: Path, stamp: str) -> int:
    """Write one CSV. Returns the row count."""
    path = out_dir / f"{spec['name']}-{stamp}.csv"
    fields = spec["fields"]
    rows = 0
    # Stream to disk rather than building a list: a full CMDB pull is large.
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in snow.table(
            spec["table"],
            query=spec.get("query"),
            fields=fields,
            limit=None,
            display_value=spec.get("display_value", True),
        ):
            writer.writerow(row)
            rows += 1
    print(f"  {path.name}: {rows} rows", file=sys.stderr)
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-i", "--instance", required=True, help="instance name, host or URL")
    p.add_argument("-o", "--out", default="exports", help="output directory (default: ./exports)")
    p.add_argument("--only", action="append", metavar="NAME", help="run just these exports; repeatable")
    args = p.parse_args(argv)

    specs = EXPORTS
    if args.only:
        specs = [s for s in EXPORTS if s["name"] in args.only]
        missing = set(args.only) - {s["name"] for s in specs}
        if missing:
            print(f"export: no such export: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    stored = load_session(args.instance)
    if stored is None:
        print(f"export: no saved session for {host_of(args.instance)}", file=sys.stderr)
        print(f"  run: snowq -i {args.instance} login", file=sys.stderr)
        return 3

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    snow = SnowClient.from_session(stored)

    failed = []
    try:
        for spec in specs:
            print(f"{spec['name']} ({spec['table']})", file=sys.stderr)
            try:
                export_one(snow, spec, out_dir, stamp)
            except SessionExpired:
                raise
            except (requests.RequestException, RuntimeError, ValueError) as e:
                # One bad table should not cost you the other exports.
                print(f"  failed: {e}", file=sys.stderr)
                failed.append(spec["name"])
    except SessionExpired as e:
        print(f"export: {e}\n  run: snowq -i {args.instance} login", file=sys.stderr)
        return 3
    except requests.RequestException as e:
        print(f"export: could not reach {args.instance}: {e}", file=sys.stderr)
        return 4
    finally:
        stored_path = snow.to_session(stored.source).save()  # keep rotated cookies
        print(f"session refreshed: {stored_path}", file=sys.stderr)

    if failed:
        print(f"export: {len(failed)} failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"export: wrote {len(specs)} file(s) to {out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
