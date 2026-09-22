---
name: snowq
description: Querying ServiceNow with the snowq CLI
---

<!-- Generated from AGENTS.md by util/gen_agent_docs.py — edit that, not this. -->

## Non-negotiables

**Never guess a field name or a choice value.** A ServiceNow instance is
customised: form labels are not field names, the fields that matter are often
custom `u_` ones, and choice values are numbers that differ per instance. A
wrong guess returns an empty result, not an error — so a broken query reads as
"no records" and nobody notices. Discover first:

```sh
snowq query incident -q "number=INC0012345" -d all -o json                      # every field of one record
snowq query sys_dictionary -q "name=incident^elementSTARTSWITHu_" -f element,column_label -n 0 -o table
snowq query sys_choice -q "name=incident^element=state" -f value,label -n 0 -o table
```

**`-q` takes an encoded query, not SQL.** `^` is AND, `^OR` is OR, `LIKE`,
`STARTSWITH`, `IN` (no spaces), `ISEMPTY`, `RELATIVEGE@day@ago@30`. Dot-walk to
reference fields: `assignment_group.name=Database Platform`.

- CORRECT: `-q "active=true^priority=1"`
- WRONG: `-q "active=true AND priority=1"`

**`-i` is global and goes before the subcommand.**

- CORRECT: `snowq -i acme query incident -q "active=true"`
- WRONG: `snowq query incident -q "active=true" -i acme`

**Always pass `-f` with `-o table`,** with no spaces after the commas. Without
`-f` the API returns every field — incident has ~150 — and the table is
unreadable. `-f number, short_description` is split by the shell and rejected.

**Pass `-d true` when a human reads the output,** or `state` is `2` and
`assigned_to` is a 32-character sys_id.

**An empty result can mean ACLs, not absence.** Queries run as the signed-in
user. `snowq count` on the same filter tells you which — say which one you are
reporting.

**snowq is read-only.** It cannot create, update or delete records.

**Exit codes:** 3 = session expired (re-authenticate, do not retry), 4 =
instance unreachable (do not retry in a loop), 2 = bad arguments.

**Run it as `./snowq` (POSIX/Git Bash) or `snowq.cmd` (Windows)** — these work
from the checkout with no install. Bare `snowq` only exists on PATH after a
successful install; `python -m snowq` needs `PYTHONPATH=src`.

The full guide is in [AGENTS.md](AGENTS.md): encoded-query syntax, the
commands, the tables worth knowing, and exit-code handling.
[docs/recipes.md](docs/recipes.md) has worked examples.
