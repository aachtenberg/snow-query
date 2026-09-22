#!/usr/bin/env python3
"""Generate the per-tool agent instruction files from AGENTS.md.

Every IDE assistant looks for its own filename, and keeping six hand-written
copies of the same rules in sync is a losing game — they drift, and a stale
copy teaching a model to guess field names is worse than no copy at all. So
AGENTS.md is the source, the block between the `core` markers is what every
tool gets, and each tool file is generated with the header that tool expects.

    python util/gen_agent_docs.py            # write the files
    python util/gen_agent_docs.py --check    # fail if any file is stale (CI)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "AGENTS.md"
START, END = "<!-- core:start -->", "<!-- core:end -->"

GENERATED = "<!-- Generated from AGENTS.md by util/gen_agent_docs.py — edit that, not this. -->"

POINTER = (
    "The full guide is in [AGENTS.md](AGENTS.md): encoded-query syntax, the\n"
    "commands, the tables worth knowing, and exit-code handling.\n"
    "[docs/recipes.md](docs/recipes.md) has worked examples.\n"
)

# path -> header placed above the shared core block
TARGETS: dict[str, str] = {
    # Cross-tool default, and what Claude Code reads for the repo.
    "CLAUDE.md": "# snowq\n\n{generated}\n\n",
    # GitHub Copilot, in VS Code and JetBrains.
    ".github/copilot-instructions.md": "# snowq — Copilot instructions\n\n{generated}\n\n",
    # Cursor. Project rules live in .cursor/rules/*.mdc with frontmatter.
    ".cursor/rules/snowq.mdc": (
        "---\n"
        "description: Querying ServiceNow with the snowq CLI\n"
        "alwaysApply: true\n"
        "---\n\n"
        "{generated}\n\n"
    ),
    # Windsurf.
    ".windsurfrules": "# snowq\n\n{generated}\n\n",
    # Cline.
    ".clinerules": "# snowq\n\n{generated}\n\n",
    # Continue.
    ".continue/rules/snowq.md": (
        "---\n"
        "name: snowq\n"
        "description: Querying ServiceNow with the snowq CLI\n"
        "---\n\n"
        "{generated}\n\n"
    ),
    # Claude Code skill: discovered by its frontmatter description.
    ".claude/skills/snowq/SKILL.md": (
        "---\n"
        "name: snowq\n"
        "description: Query ServiceNow from the command line with snowq — encoded-query syntax, "
        "discovering real field names, and recipes for incident, change_request, cmdb_ci_* and "
        "sys_user_group. Use when asked to pull ServiceNow data, write or fix an encoded query, "
        "find which field or choice value an instance uses, or export records to CSV.\n"
        "---\n\n"
        "# Querying ServiceNow with snowq\n\n"
        "{generated}\n\n"
    ),
}


def core_block() -> str:
    text = SOURCE.read_text()
    try:
        body = text.split(START, 1)[1].split(END, 1)[0]
    except IndexError:
        raise SystemExit(f"{SOURCE.name}: missing {START} / {END} markers")
    return body.strip() + "\n"


def render(header: str, core: str) -> str:
    # A pointer relative to the repo root works from a nested file too, because
    # every assistant resolves these against the workspace root.
    return header.format(generated=GENERATED) + core + "\n" + POINTER


def main(argv: list[str]) -> int:
    check = "--check" in argv
    core = core_block()
    stale: list[str] = []

    for rel, header in TARGETS.items():
        path = ROOT / rel
        want = render(header, core)
        have = path.read_text() if path.exists() else None
        if have == want:
            continue
        if check:
            stale.append(rel)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(want)
        print(f"wrote {rel}")

    if stale:
        print("stale, re-run util/gen_agent_docs.py:", file=sys.stderr)
        for rel in stale:
            print(f"  {rel}", file=sys.stderr)
        return 1
    if check:
        print(f"{len(TARGETS)} agent files up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
