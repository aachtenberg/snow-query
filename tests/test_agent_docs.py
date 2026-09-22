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


# Listed literally, NOT read from gen.TARGETS: a test that reads the same
# config it is checking passes when someone flips the flag off, which is the
# regression it exists to catch.
REPO_ASSISTANT_FILES = (
    "CLAUDE.md",
    ".github/copilot-instructions.md",
    ".cursor/rules/snowq.mdc",
    ".windsurfrules",
    ".clinerules",
    ".continue/rules/snowq.md",
)
USAGE_ONLY_FILES = (".claude/skills/snowq/SKILL.md",)


def test_repo_assistants_learn_the_files_are_generated():
    # The trap this closes: an agent asked to change the agent instructions
    # opens the file it was loaded with, edits it, and CI fails with no hint.
    # Every file an assistant loads for the repo must say to edit AGENTS.md.
    for rel in REPO_ASSISTANT_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "are generated" in text, rel
        assert "util/gen_agent_docs.py" in text, rel
        assert "uv run pytest" in text, rel


def test_the_usage_skill_carries_no_repo_chores():
    for rel in USAGE_ONLY_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "Working on this repository" not in text, rel


def test_the_two_file_lists_cover_every_target():
    assert set(REPO_ASSISTANT_FILES) | set(USAGE_ONLY_FILES) == set(gen.TARGETS)


def test_markers_still_delimit_their_blocks():
    core, dev = gen.core_block(), gen.dev_block()
    assert "Never guess a field name" in core
    assert "Working on this repository" in dev
    # neither block may swallow the other, or the split stops meaning anything
    assert "Working on this repository" not in core
    for marker in (*gen.CORE, *gen.DEV):
        assert marker not in core and marker not in dev
