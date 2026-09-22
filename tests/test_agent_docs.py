"""The per-tool agent files are generated; CI fails if one drifts.

A stale copy is worse than no copy: it keeps teaching a model the rule that
changed. These tests are the reason the generator exists.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "util"))

import gen_agent_docs as gen  # noqa: E402


def test_every_target_is_in_sync():
    result = subprocess.run(
        [sys.executable, str(ROOT / "util" / "gen_agent_docs.py"), "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",  # not the locale's: the output carries em dashes
    )
    assert result.returncode == 0, result.stderr


def test_every_target_exists_and_points_at_the_source():
    for rel in gen.TARGETS:
        path = ROOT / rel
        assert path.exists(), f"{rel} missing — run util/gen_agent_docs.py"
        assert "AGENTS.md" in path.read_text(encoding="utf-8"), f"{rel} does not point at AGENTS.md"


def test_the_rule_that_matters_reaches_every_tool():
    # The anti-hallucination rule is the whole point; assert it is not just in
    # the canonical file but in what each assistant actually loads.
    for rel in gen.TARGETS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "Never guess a field name" in text, rel
        assert "read-only" in text, rel


def test_core_markers_still_delimit_a_block():
    core = gen.core_block()
    assert "Never guess a field name" in core
    assert gen.START not in core and gen.END not in core
