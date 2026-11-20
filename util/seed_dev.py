#!/usr/bin/env python3
"""Make a personal developer instance look like a customised, real one.

A fresh developer instance has plenty of records but only stock fields and
stock choice values, and those are not what goes wrong on a real instance.
This adds what does:

* four custom fields on incident whose labels do not match their names —
  u_business_impact ("Business impact", an integer choice: 10, 20, 30, 40),
  u_vendor_ticket ("Vendor reference"), u_regulated ("SOX in scope") and
  u_escalation_group ("Escalate to", a reference to sys_user_group)
* a non-standard incident state, 18 "Awaiting Vendor"
* two groups, three servers and a dozen incidents that use all of it

Everything it creates is marked "snowq-seed", so a second run skips what
exists and --clean removes exactly what it made, fields included.

    ./snowq -i "$PDI" login                         # once; seeding rides that session
    uv run --no-sync python util/seed_dev.py -i "$PDI"
    uv run --no-sync python util/seed_dev.py -i "$PDI" --clean

snowq stays read-only: this writes from outside the CLI, through the client's
generic request(). It refuses any host that is not a personal developer
instance (devNNNNN.service-now.com) unless you pass --any-instance.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snowq import auth  # noqa: E402
from snowq.client import SessionExpired, SnowClient  # noqa: E402

MARK = "snowq-seed"
NOTE = "Created by util/seed_dev.py in the snowq repository; remove with --clean."
PDI_HOST = re.compile(r"^dev\d+\.service-now\.com$")

FIELDS = [
    {"element": "u_business_impact", "column_label": "Business impact", "internal_type": "integer", "choice": "1"},
    {"element": "u_vendor_ticket", "column_label": "Vendor reference", "internal_type": "string", "max_length": "40"},
    {"element": "u_regulated", "column_label": "SOX in scope", "internal_type": "boolean", "default_value": "false"},
    {
        "element": "u_escalation_group",
        "column_label": "Escalate to",
        "internal_type": "reference",
        "reference": "sys_user_group",
    },
]

# (element, value, label, sequence)
CHOICES = [
    ("u_business_impact", "10", "Revenue loss", 10),
    ("u_business_impact", "20", "Regulatory exposure", 20),
    ("u_business_impact", "30", "Customer facing", 30),
    ("u_business_impact", "40", "Internal only", 40),
    ("state", "18", "Awaiting Vendor", 5),
]

# Stock values the incidents below use. Checked against sys_choice before
# anything is written, rather than assumed.
STOCK = {"state": {"1", "2", "6"}, "impact": {"1", "2", "3"}, "urgency": {"1", "2", "3"}}

# Close codes that need no linked record; values differ by release.
PLAIN_CLOSE_CODES = ("Resolved by caller", "Workaround provided", "Solution provided", "Solved (Permanently)")

GROUPS = [f"{MARK} Database Platform", f"{MARK} Storage Platform"]
SERVERS = [
    (f"{MARK}-db01", "192.0.2.11", "Primary reporting database"),
    (f"{MARK}-db02", "192.0.2.12", "Reporting database replica"),
    (f"{MARK}-nas01", "192.0.2.21", "Shared NAS head"),
]

# key, short_description, state, impact, urgency, group, server, impact code,
# vendor ticket, SOX, escalate-to group, days ago. None = leave the field empty.
INCIDENTS = [
    ("01", "Replica lag on the reporting database", "2", "2", "2", 0, 1, "30", None, True, None, 1),
    ("02", "Nightly export job missed its window", "1", "2", "3", 0, 0, "20", None, True, 1, 2),
    ("03", "Storage array firmware fault, vendor engaged", "18", "1", "2", 1, 2, "10", "VND-88412", False, None, 3),
    ("04", "Backup volume at 95% capacity", "2", "2", "1", 1, 2, "40", None, False, None, 4),
    ("05", "Database licence key rejected after renewal", "18", "2", "2", 0, 0, "20", "VND-88519", True, 1, 6),
    ("06", "Slow queries on the finance ledger schema", "6", "3", "3", 0, 0, None, None, True, None, 9),
    ("07", "NAS share read-only after failover", "6", "1", "1", 1, 2, "10", "VND-87001", False, 0, 14),
    ("08", "Replica out of sync after patching", "18", "2", "2", 0, 1, "30", "VND-88600", True, 1, 1),
    ("09", "Snapshot schedule not running", "1", "3", "3", 1, 2, None, None, False, None, 0),
    ("10", "Audit trail table growing unbounded", "2", "3", "2", 0, 0, "20", None, True, None, 5),
    ("11", "Disk latency alerts on the NAS head", "6", "2", "3", 1, 2, "40", None, False, None, 21),
    ("12", "Connection pool exhausted during month-end", "1", "1", "1", 0, 0, "10", None, True, 1, 0),
]


# --- REST helpers -------------------------------------------------------------


def find(client: SnowClient, table: str, query: str, fields: list[str] | None = None) -> list[dict]:
    return list(client.table(table, query=query, fields=fields or ["sys_id"], limit=None))


def insert(client: SnowClient, table: str, body: dict) -> dict:
    return client.request("POST", f"/api/now/table/{table}", json=body).json()["result"]


def delete(client: SnowClient, table: str, sys_id: str) -> None:
    # 204 with no body and no Content-Type: tell request() that an empty
    # response is not the login page it would otherwise take it for.
    client.request("DELETE", f"/api/now/table/{table}/{sys_id}", expect_json=False, allow_html=True)


def ensure(client: SnowClient, table: str, query: str, body: dict, what: str) -> str:
    found = find(client, table, query)
    if found:
        print(f"  exists   {table:15} {what}")
        return found[0]["sys_id"]
    sys_id = insert(client, table, body)["sys_id"]
    print(f"  created  {table:15} {what}")
    return sys_id


# --- seed ---------------------------------------------------------------------


def choice_values(client: SnowClient, element: str) -> set[str]:
    # A field inherited from task (impact, urgency) keeps its choices on task
    # unless incident overrides them, as it does for state. Same rule here.
    rows = find(client, "sys_choice", f"nameINincident,task^element={element}^inactive=false^language=en",
                ["name", "value"])
    own = {r["value"] for r in rows if r["name"] == "incident"}
    return own or {r["value"] for r in rows if r["name"] == "task"}


def seed(client: SnowClient) -> None:
    for element, wanted in STOCK.items():
        missing = wanted - choice_values(client, element)
        if missing:
            raise RuntimeError(f"incident.{element} has no choice {sorted(missing)} here; edit STOCK and INCIDENTS")
    # The one data policy on a stock instance makes close info mandatory when
    # resolved, and several codes ("Known error", "Duplicate", "Resolved by
    # problem") trip business rules that want a linked record. Take the first
    # plain code this instance actually offers.
    offered = choice_values(client, "close_code")
    close_code = next((c for c in PLAIN_CLOSE_CODES if c in offered), None)
    if close_code is None:
        raise RuntimeError(f"none of {PLAIN_CLOSE_CODES} is an incident.close_code here; add one this instance has")

    print("fields")
    for f in FIELDS:
        ensure(client, "sys_dictionary", f"name=incident^element={f['element']}", {"name": "incident", **f},
               f"incident.{f['element']} ({f['column_label']})")
    print("choices")
    for element, value, label, sequence in CHOICES:
        ensure(client, "sys_choice", f"name=incident^element={element}^value={value}^language=en",
               {"name": "incident", "element": element, "value": value, "label": label,
                "sequence": sequence, "language": "en", "inactive": "false"},
               f"incident.{element} {value} = {label}")
    print("groups")
    groups = [ensure(client, "sys_user_group", f"name={name}", {"name": name, "description": NOTE}, name)
              for name in GROUPS]
    print("servers")
    servers = [ensure(client, "cmdb_ci_server", f"name={name}",
                      {"name": name, "ip_address": ip, "short_description": desc, "comments": NOTE}, name)
               for name, ip, desc in SERVERS]

    print("incidents")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    for key, desc, state, impact, urgency, group, server, code, vendor, sox, escalate, days in INCIDENTS:
        body = {
            "correlation_id": f"{MARK}-{key}",
            "short_description": desc,
            "description": NOTE,
            "state": state,
            "impact": impact,
            "urgency": urgency,
            "assignment_group": groups[group],
            "cmdb_ci": servers[server],
            "u_regulated": "true" if sox else "false",
            "opened_at": (now - timedelta(days=days, hours=int(key))).strftime("%Y-%m-%d %H:%M:%S"),
        }
        if code:
            body["u_business_impact"] = code
        if vendor:
            body["u_vendor_ticket"] = vendor
        if escalate is not None:
            body["u_escalation_group"] = groups[escalate]
        if state == "6":
            body.update(close_code=close_code, close_notes=NOTE)
        ensure(client, "incident", f"correlation_id={MARK}-{key}", body, f"{MARK}-{key} {desc}")

    # Read back through the new columns: a field the Table API silently dropped
    # would come back empty here rather than failing anywhere above.
    rows = find(client, "incident", f"correlation_idSTARTSWITH{MARK}", ["number", "state", "u_regulated"])
    awaiting = sum(r["state"] == "18" for r in rows)
    sox = sum(r["u_regulated"] == "true" for r in rows)
    print(f"\n{len(rows)} seeded incidents: {awaiting} in state 18, {sox} with u_regulated=true")
    if awaiting != sum(i[2] == "18" for i in INCIDENTS) or sox != sum(i[9] for i in INCIDENTS):
        raise RuntimeError("the custom fields did not take; check sys_dictionary for incident.u_*")


def clean(client: SnowClient) -> None:
    targets = [
        ("incident", f"correlation_idSTARTSWITH{MARK}"),
        ("cmdb_ci_server", f"nameSTARTSWITH{MARK}-"),
        ("sys_user_group", f"nameSTARTSWITH{MARK} "),
        ("sys_choice", "name=incident^element=u_business_impact"),
        ("sys_choice", "name=incident^element=state^value=18"),
        ("sys_dictionary", "name=incident^elementIN" + ",".join(f["element"] for f in FIELDS)),
        # Labels can outlive their dictionary entry.
        ("sys_documentation", "name=incident^elementIN" + ",".join(f["element"] for f in FIELDS)),
    ]
    for table, query in targets:
        rows = find(client, table, query)
        for r in rows:
            delete(client, table, r["sys_id"])
        print(f"  deleted  {table:17} {len(rows)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed (or --clean) a developer instance with customised test data.")
    ap.add_argument("-i", "--instance", default=os.environ.get("SNOWQ_INSTANCE"),
                    help="instance name, host or URL (default: $SNOWQ_INSTANCE)")
    ap.add_argument("--clean", action="store_true", help="remove everything this script created")
    ap.add_argument("--any-instance", action="store_true",
                    help="allow a host that is not devNNNNN.service-now.com; never point this at production")
    args = ap.parse_args(argv)
    if not args.instance:
        print("seed_dev: pass -i or set SNOWQ_INSTANCE", file=sys.stderr)
        return 2
    host = auth.host_of(args.instance)
    if not PDI_HOST.match(host) and not args.any_instance:
        print(f"seed_dev: {host} is not a personal developer instance; refusing to write to it.\n"
              "  Pass --any-instance only for a disposable sub-production instance.", file=sys.stderr)
        return 2

    stored = auth.load_session(args.instance)
    if stored is None:
        print(f"seed_dev: no saved session for {host}\n  run: ./snowq -i {args.instance} login", file=sys.stderr)
        return 3
    client = SnowClient.from_session(stored)
    try:
        print(f"{'cleaning' if args.clean else 'seeding'} {host}")
        clean(client) if args.clean else seed(client)
    except SessionExpired as e:
        print(f"seed_dev: {e}\n  run: ./snowq -i {args.instance} login", file=sys.stderr)
        return 3
    except RuntimeError as e:
        print(f"seed_dev: {e}", file=sys.stderr)
        return 1
    finally:
        client.to_session(stored.source).save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
