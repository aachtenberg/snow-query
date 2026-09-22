# Working with this repository

snowq queries ServiceNow's REST APIs by reusing an SSO browser session. This
file is the canonical guidance for coding agents and IDE assistants; the
per-tool files in this repo are generated from it by
`util/gen_agent_docs.py`.

<!-- core:start -->
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
<!-- core:end -->

<!-- dev:start -->
## Working on this repository

- `uv run pytest` runs everything, including the check that the per-tool agent
  files still match this one.
- **CLAUDE.md, `.clinerules`, `.windsurfrules`, `.cursor/rules/`,
  `.continue/rules/` and `.claude/skills/snowq/SKILL.md` are generated.** Edit
  **AGENTS.md**, then run `python util/gen_agent_docs.py`. Hand-editing a
  generated file fails CI — the file you are reading may be one of them.
- The CLI is in `src/snowq/`. `./snowq` (POSIX/Git Bash) and `snowq.cmd`
  (Windows) run it from the checkout with no install; CI exercises both on
  Linux, macOS and Windows.
- **Name `encoding="utf-8"` on every text read and write.** These docs carry em
  dashes, and the Windows runner defaults to cp1252, which mangles them
  silently. `python -X warn_default_encoding -W error::EncodingWarning` finds
  the omissions.
- Keep instance names, group names, people and CI names out of committed files.
  Use shell variables the reader substitutes, as `docs/recipes.md` does.
<!-- dev:end -->

## Detail

snowq is read-only and runs as the signed-in user, reusing an SSO browser
session. It cannot create, update or delete records — never offer to.

## The rule that matters most: do not guess field names

A ServiceNow instance is customised. Form labels are not field names, choice
values differ per instance, and the fields that matter locally are usually
custom `u_` ones. Inventing `assigned_group`, `priority_label` or `state=Open`
produces a query that returns nothing and looks like an empty result rather
than a mistake.

Discover, then query:

```sh
# every field of one known record, raw value and display label together
snowq query incident -q "number=INC0012345" -d all -o json

# custom fields, with the labels shown in the form
snowq query sys_dictionary -q "name=incident^elementSTARTSWITHu_" -f element,column_label -n 0 -o table

# what the numbers in a choice field mean HERE
snowq query sys_choice -q "name=incident^element=state" -f value,label -n 0 -o table
```

- CORRECT: `-q "state=2"` after confirming 2 is In Progress on this instance
- WRONG: `-q "state=In Progress"` — state stores a number
- WRONG: assuming `state=2` means the same thing on another instance

## Encoded queries, not SQL and not URLs

`-q` takes ServiceNow's encoded-query string.

| Meaning | Syntax |
|---|---|
| AND | `^` — `active=true^priority=1` |
| OR | `^OR` — `support_groupISEMPTY^ORowned_byISEMPTY` |
| New query (separate clause) | `^NQ` |
| Contains / starts with | `LIKE`, `STARTSWITH` |
| One of | `IN` — `stateIN1,2,3` (no spaces) |
| Empty / not empty | `ISEMPTY`, `ISNOTEMPTY` |
| Relative date | `opened_atRELATIVEGE@day@ago@30`, `start_dateRELATIVELE@day@ahead@7` |
| Reference by name | dot-walk — `assignment_group.name=Database Platform` |

- CORRECT: `-q "active=true^priority=1"`
- WRONG: `-q "active=true AND priority=1"` — SQL, matches nothing
- WRONG: `-q "sysparm_query=active=true"` — that is the URL parameter, not the value

Relative-date units: `minute`, `hour`, `day`, `week`, `month`, `quarter`, `year`.

The fastest route to a hard filter is the UI: build it in the list view,
right-click the breadcrumb, **Copy query**, paste after `-q`.

## Flags that change whether output is usable

| Flag | Use |
|---|---|
| `-f a,b,c` | Fields. **No spaces after commas** — the shell splits the list and the query fails |
| `-d true` | Display values: `In Progress` instead of `2`, a name instead of a 32-char sys_id |
| `-d all` | Both raw and display — use when mapping fields |
| `-n 0` | Every match (pages 500 at a time). Default is 100 |
| `-o table` | For a human reading a terminal |
| `-o csv` / `-o json` | For a file or another program |

- CORRECT: `-f number,short_description,state`
- WRONG: `-f number, short_description, state`

Always pass `-f` for `-o table`. Without it the API returns every field —
incident has ~150 — and the table is unreadable.

## Commands

```sh
snowq whoami
snowq query <table> -q "<encoded query>" -f <fields> -d true -n 0 -o table
snowq get <table> <sys_id> -d all          # by sys_id, NOT by number
snowq count <table> -q "<encoded query>"   # volume without pulling records
snowq raw /api/now/... -p key=value        # any REST path
snowq logout
```

To fetch a record by its number, use `query` with `-q "number=INC0012345"` —
`get` takes a sys_id.

`-i <instance>` is a global option and must come **before** the subcommand, or
it is rejected as an unrecognized argument:

- CORRECT: `snowq -i acme query incident -q "active=true"`
- WRONG: `snowq query incident -q "active=true" -i acme`

`SNOWQ_INSTANCE` in the environment avoids the question entirely.

For a breakdown that `count` cannot do in one call, reach the Aggregate API:

```sh
snowq raw /api/now/stats/incident \
      -p "sysparm_query=active=true" \
      -p sysparm_count=true \
      -p sysparm_group_by=assignment_group \
      -p sysparm_display_value=true
```

## Tables worth knowing

| Table | Holds |
|---|---|
| `incident` | Incidents. Links to its problem through `problem_id` |
| `problem` | Problems. Lifecycle is on `state` or `problem_state` depending on the version — check before filtering |
| `problem_task` | RCA and fix tasks under a problem |
| `change_request` | Changes |
| `task_ci` | CIs affected by a task — `cmdb_ci` on the change is only the primary |
| `cmdb_ci_server` | Servers |
| `sys_user_group` | Groups |
| `sys_user_grmember` | Group membership |
| `sys_dictionary` | Field definitions — what fields exist |
| `sys_choice` | Choice values and their labels |

## Reading results honestly

Queries run with the user's roles and ACLs, so **an empty result can mean the
records exist but are not visible**. It is not proof of absence. `snowq count`
on the same filter distinguishes the two. Say which one you are reporting.

## Exit codes

| Code | Meaning | Response |
|---|---|---|
| 3 | Session expired or absent | Tell the user to re-authenticate; do not retry |
| 4 | Instance unreachable | Network or proxy; do not retry in a loop |
| 2 | Bad arguments | Re-read the message — a stray comma-list is the usual cause |

Never retry a 3 or 4 by re-running the same command.

## Invoking it

`./snowq` (POSIX/Git Bash) and `snowq.cmd` (Windows) run the CLI from the
checkout with no install. Prefer them over bare `snowq`, which only exists on
PATH after a successful install. If neither is used, `python -m snowq` needs
`PYTHONPATH=src`, or it fails with `No module named snowq`.

## Writing queries into files

Keep instance names, group names, people and CI names out of anything
committed. Put them in shell variables the reader substitutes:

```sh
GROUP="Database Platform"
snowq query incident -q "assignment_group.name=$GROUP^active=true" -f number,state -d true -o table
```

## More

`docs/recipes.md` has worked examples for incidents by assignment group,
backlog counts per team, server inventory, CMDB hygiene and change management.
`docs/sessions.md` covers authentication; `docs/install.md` covers blocked
package indexes.
