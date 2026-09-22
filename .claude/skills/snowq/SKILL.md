---
name: snowq
description: Query ServiceNow from the command line with snowq — encoded-query syntax, discovering real field names, and recipes for incident, change_request, cmdb_ci_* and sys_user_group. Use when asked to pull ServiceNow data, write or fix an encoded query, find which field or choice value an instance uses, or export records to CSV.
---

# Querying ServiceNow with snowq

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
| `incident` | Incidents |
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
