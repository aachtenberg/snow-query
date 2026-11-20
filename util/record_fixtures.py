#!/usr/bin/env python3
"""Record a seeded developer instance's answers for the offline tests.

    uv run --no-sync python util/seed_dev.py -i "$PDI"          # first
    uv run --no-sync python util/record_fixtures.py -i "$PDI"

Every scenario below is one read-only SnowClient call. The HTTP exchanges it
makes are captured as they come off the wire, the instance host is replaced
with acme.service-now.com, and the lot is written to
tests/fixtures/seeded_instance.json together with the call that produced it.
tests/test_fixtures.py makes the same call against the recording, so the
requests it sends have to match the recorded ones exactly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from requests.adapters import HTTPAdapter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snowq import auth  # noqa: E402
from snowq.client import SessionExpired, SnowClient  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "seeded_instance.json"
PLACEHOLDER_HOST = "acme.service-now.com"
SEEDED = "correlation_idSTARTSWITHsnowq-seed"
SEEDED_FIELDS = [
    "number", "correlation_id", "short_description", "state", "close_code", "assignment_group",
    "u_business_impact", "u_vendor_ticket", "u_regulated", "u_escalation_group",
]

# name -> (client method, keyword arguments). get_record's sys_id is filled in
# from the seeded_raw result once that has been recorded.
SCENARIOS: dict[str, tuple[str, dict]] = {
    "state_choices": ("table", {
        "table": "sys_choice", "query": "name=incident^element=state^inactive=false^language=en",
        "fields": ["value", "label"], "limit": None, "order_by": "sequence"}),
    "business_impact_choices": ("table", {
        "table": "sys_choice", "query": "name=incident^element=u_business_impact^language=en",
        "fields": ["value", "label"], "limit": None, "order_by": "sequence"}),
    "impact_choices_on_incident": ("table", {
        "table": "sys_choice", "query": "name=incident^element=impact^inactive=false^language=en",
        "fields": ["value", "label"], "limit": None}),
    "impact_choices_on_task": ("table", {
        "table": "sys_choice", "query": "name=task^element=impact^inactive=false^language=en",
        "fields": ["value", "label"], "limit": None}),
    "custom_fields": ("table", {
        "table": "sys_dictionary", "query": "name=incident^elementSTARTSWITHu_",
        "fields": ["element", "column_label", "internal_type"], "limit": None, "order_by": "element"}),
    "seeded_raw": ("table", {
        "table": "incident", "query": SEEDED, "fields": SEEDED_FIELDS, "limit": None,
        "order_by": "correlation_id"}),
    "seeded_display": ("table", {
        "table": "incident", "query": SEEDED, "fields": SEEDED_FIELDS, "limit": None,
        "order_by": "correlation_id", "display_value": True}),
    "seeded_count": ("count", {"table": "incident", "query": SEEDED}),
    "seeded_paged": ("table", {
        "table": "incident", "query": SEEDED, "fields": ["number"], "limit": None, "page_size": 5,
        "order_by": "correlation_id"}),
    "escalated_to_storage": ("table", {
        "table": "incident", "query": f"{SEEDED}^u_escalation_group.name=snowq-seed Storage Platform",
        "fields": ["number", "u_escalation_group"], "limit": None, "display_value": True}),
    "awaiting_vendor_count": ("count", {"table": "incident", "query": f"{SEEDED}^state=18"}),
    "one_record_all": ("get_record", {"table": "incident", "sys_id": None, "display_value": "all"}),
}


class Recorder(HTTPAdapter):
    """Keeps a copy of every JSON exchange with the REST API."""

    def __init__(self):
        super().__init__()
        self.exchanges: list[dict] = []

    def send(self, request, **kw):
        r = super().send(request, **kw)
        u = urlparse(request.url)
        ctype = r.headers.get("Content-Type", "")
        # Skip the token probe's 401 and anything else that is not an answer.
        if u.path.startswith("/api/") and r.status_code == 200 and "json" in ctype:
            self.exchanges.append({
                "method": request.method,
                "path": u.path,
                "params": {k: v[0] for k, v in parse_qs(u.query).items()},
                "status": r.status_code,
                "content_type": ctype,
                "body": r.json(),
            })
        return r


def record(client: SnowClient, recorder: Recorder) -> dict:
    scenarios: dict[str, dict] = {}
    for name, (method, kwargs) in SCENARIOS.items():
        kwargs = dict(kwargs)
        # The previous scenario keeps the list it was recorded into; start a
        # new one before any request, the sys_id lookup included.
        recorder.exchanges = []
        if name == "one_record_all":
            kwargs["sys_id"] = _first_seeded_sys_id(client)
            recorder.exchanges = []  # the lookup is not part of this scenario
        result = getattr(client, method)(**kwargs)
        if method == "table":
            result = list(result)
        scenarios[name] = {"call": {"method": method, "args": kwargs}, "exchanges": recorder.exchanges}
        size = len(result) if isinstance(result, list) else result if isinstance(result, int) else "1 record"
        print(f"  {name:28} {size}")
    return scenarios


def _first_seeded_sys_id(client: SnowClient) -> str:
    rows = list(client.table("incident", query=SEEDED, fields=["sys_id"], limit=1, order_by="correlation_id"))
    if not rows:
        raise RuntimeError("no seeded incidents; run util/seed_dev.py first")
    return rows[0]["sys_id"]


def scrub(text: str, host: str) -> str:
    text = text.replace(host, PLACEHOLDER_HOST)
    leftover = re.findall(r"[\w.-]+\.service-now\.com", text)
    leftover = sorted(set(leftover) - {PLACEHOLDER_HOST})
    instance = host.split(".")[0]
    if leftover or re.search(rf"\b{re.escape(instance)}\b", text):
        raise RuntimeError(f"the recording still names the instance ({leftover or instance}); not writing it")
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Record tests/fixtures/seeded_instance.json from a seeded instance.")
    ap.add_argument("-i", "--instance", default=os.environ.get("SNOWQ_INSTANCE"),
                    help="instance name, host or URL (default: $SNOWQ_INSTANCE)")
    args = ap.parse_args(argv)
    if not args.instance:
        print("record_fixtures: pass -i or set SNOWQ_INSTANCE", file=sys.stderr)
        return 2
    stored = auth.load_session(args.instance)
    if stored is None:
        print(f"record_fixtures: no saved session\n  run: ./snowq -i {args.instance} login", file=sys.stderr)
        return 3

    client = SnowClient.from_session(stored)
    recorder = Recorder()
    client.http.mount("https://", recorder)
    try:
        print(f"recording {client.host}")
        scenarios = record(client, recorder)
    except SessionExpired as e:
        print(f"record_fixtures: {e}\n  run: ./snowq -i {args.instance} login", file=sys.stderr)
        return 3
    except RuntimeError as e:
        print(f"record_fixtures: {e}", file=sys.stderr)
        return 1
    finally:
        client.to_session(stored.source).save()

    doc = {
        "about": "Recorded by util/record_fixtures.py from a developer instance seeded by "
                 "util/seed_dev.py. Re-record rather than hand-edit.",
        "instance": f"https://{PLACEHOLDER_HOST}",
        "scenarios": scenarios,
    }
    text = json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    try:
        text = scrub(text, client.host)
    except RuntimeError as e:
        print(f"record_fixtures: {e}", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
