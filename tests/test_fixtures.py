"""Replay answers recorded from a seeded developer instance.

The fake handlers in test_client.py are written by hand, so they carry only the
shapes someone thought of. These come off a real instance that
util/seed_dev.py customised: custom u_ fields whose labels are not their
names, a non-standard state value, reference fields that stay sys_ids until
-d true, choices inherited from task. Re-record with util/record_fixtures.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from snowq import cli
from test_client import INSTANCE, make_client

FIXTURE = Path(__file__).parent / "fixtures" / "seeded_instance.json"
TEXT = FIXTURE.read_text(encoding="utf-8")
SCENARIOS = json.loads(TEXT)["scenarios"]
SYS_ID = re.compile(r"^[0-9a-f]{32}$")


def replay(name: str):
    """Make the recorded call against the recording; return (result, adapter)."""
    scenario = SCENARIOS[name]
    served = {
        (e["method"], e["path"], tuple(sorted(e["params"].items()))): e for e in scenario["exchanges"]
    }

    def handler(method, path, params, headers):
        key = (method, path, tuple(sorted(params.items())))
        if key not in served:
            raise AssertionError(f"{name}: nothing recorded for {key}; re-run util/record_fixtures.py")
        e = served[key]
        return e["status"], {"Content-Type": e["content_type"]}, e["body"]

    client, adapter = make_client(handler, g_ck="t" * 32)
    call = scenario["call"]
    result = getattr(client, call["method"])(**call["args"])
    return (list(result) if call["method"] == "table" else result), adapter


def by_number(rows: list[dict]) -> dict[str, dict]:
    return {r["number"]: r for r in rows}


def test_custom_fields_are_not_named_after_their_labels():
    rows, _ = replay("custom_fields")
    labels = {r["element"]: r["column_label"] for r in rows}
    assert labels == {
        "u_business_impact": "Business impact",
        "u_escalation_group": "Escalate to",
        "u_regulated": "SOX in scope",
        "u_vendor_ticket": "Vendor reference",
    }


def test_state_choices_carry_the_custom_value_as_a_string():
    rows, _ = replay("state_choices")
    choices = {r["value"]: r["label"] for r in rows}
    assert choices["18"] == "Awaiting Vendor"
    assert {"1", "2", "6"} <= set(choices)


def test_inherited_choices_live_on_the_parent_table():
    # name=incident finds nothing for impact; the choices are defined on task.
    on_incident, _ = replay("impact_choices_on_incident")
    on_task, _ = replay("impact_choices_on_task")
    assert on_incident == []
    assert {r["value"] for r in on_task} >= {"1", "2", "3"}


def test_raw_values_are_codes_and_sys_ids_until_display_true():
    raw = by_number(replay("seeded_raw")[0])
    shown = by_number(replay("seeded_display")[0])
    impact_labels = {r["value"]: r["label"] for r in replay("business_impact_choices")[0]}
    assert raw.keys() == shown.keys()

    for number, r in raw.items():
        d = shown[number]
        assert r["state"].lstrip("-").isdigit() and not d["state"].isdigit()
        if r["u_business_impact"]:
            assert d["u_business_impact"] == impact_labels[r["u_business_impact"]]
        if r["u_escalation_group"]:
            assert SYS_ID.match(r["u_escalation_group"])
            assert d["u_escalation_group"].startswith("snowq-seed ")
        assert r["u_regulated"] in ("true", "false")
    assert "Awaiting Vendor" in {d["state"] for d in shown.values()}


def test_count_agrees_with_the_rows():
    rows, _ = replay("seeded_raw")
    count, _ = replay("seeded_count")
    assert count == len(rows) > 0
    awaiting, _ = replay("awaiting_vendor_count")
    assert awaiting == sum(r["state"] == "18" for r in rows) > 0


def test_paging_over_real_pages():
    rows, adapter = replay("seeded_paged")
    count, _ = replay("seeded_count")
    numbers = [r["number"] for r in rows]
    assert len(numbers) == len(set(numbers)) == count
    # Pages of 5 until one comes back short.
    assert [c[2]["sysparm_offset"] for c in adapter.calls] == [str(o) for o in range(0, count + 1, 5)]


def test_dot_walk_through_a_custom_reference():
    rows, _ = replay("escalated_to_storage")
    assert rows and {r["u_escalation_group"] for r in rows} == {"snowq-seed Storage Platform"}


def test_display_all_pairs_every_field_and_may_say_null():
    record, _ = replay("one_record_all")
    assert all(set(v) >= {"display_value", "value"} for v in record.values() if isinstance(v, dict))
    assert record["u_business_impact"]["value"].isdigit()
    # An empty choice field shows display_value null, not "".
    assert record["close_code"] == {"display_value": None, "value": ""}


def test_display_all_record_renders_as_json(capsys):
    record, _ = replay("one_record_all")
    cli._emit_json(record)
    assert json.loads(capsys.readouterr().out)["u_business_impact"]["display_value"]


@pytest.mark.parametrize("fmt", ["table", "csv"])
def test_seeded_rows_render(fmt, capsys):
    rows, _ = replay("seeded_display")
    fields = ["number", "state", "u_business_impact", "close_code"]
    cli._emit_rows(rows, fmt, fields)
    out = capsys.readouterr().out
    assert "Awaiting Vendor" in out
    if fmt == "csv":  # the table clips long values; CSV keeps the instance's en dashes intact
        assert "Resolved – " in out


def test_recording_names_no_instance():
    hosts = set(re.findall(r"[\w.-]+\.service-now\.com", TEXT))
    assert hosts <= {INSTANCE.split("//")[1]}
    assert not re.search(r"\bdev\d{4,}\b", TEXT)
