# Recipes: incidents, servers and changes

Encoded-query syntax is the same one the list filter builds, so the fastest way to
write a hard filter is to build it in the UI, right-click the breadcrumb → **Copy
query**, and paste it after `-q`.

## First, learn your instance

Choice values are numbers that differ per instance, and the fields that matter in
a regulated shop are usually custom (`u_`) ones. Ask rather than guess:

```sh
# what do state / risk / type actually mean here?
snowq query sys_choice -q "name=change_request^element=risk" -f value,label -n 0 -o table

# custom fields on the server class — compliance flags tend to live here
snowq query sys_dictionary -q "name=cmdb_ci_server^elementSTARTSWITHu_" \
      -f element,column_label -n 0 -o table
```

## Incidents

Nothing below names a real group, person or CI. Put the values your instance
uses in shell variables once, and the commands stay copy-pasteable — and stay
shareable, which matters when a query ends up in a ticket or a wiki:

```sh
export SNOWQ_INSTANCE=acme       # snowq reads this one
GROUP="Database Platform"        # the rest are ordinary shell variables,
OTHER_GROUP="Storage Platform"   # expanded by your shell before snowq sees them
ASSIGNEE="Firstname Lastname"
GROUP_PREFIX="Platform_"         # a naming convention, for STARTSWITH
```

### Map the form to field names

Form labels are not field names, and the fields that matter locally are often
custom. Read them off one record you already have open rather than guessing:

```sh
# every field of one incident, raw value and display label side by side
snowq query incident -q "number=INC0012345" -d all -o json

# custom fields on incident, with the labels you see in the form
snowq query sys_dictionary -q "name=incident^elementSTARTSWITHu_" \
      -f element,column_label -n 0 -o table

# what the state / priority numbers mean here
snowq query sys_choice -q "name=incident^element=state" -f value,label -n 0 -o table
```

`-d true` matters more on incident than anywhere else: without it `state` is `2`,
`priority` is `4`, and `assigned_to` is a 32-character sys_id.

### One group's queue

`assignment_group` is a reference field, so dot-walk to the name instead of
looking up its sys_id:

```sh
# open work, newest first
snowq query incident -q "assignment_group.name=$GROUP^active=true" \
      -f number,short_description,state,priority,assigned_to,opened_at \
      -d true --order-by -opened_at -n 0 -o table

# accepted by the group, owned by nobody
snowq query incident -q "assignment_group.name=$GROUP^active=true^assigned_toISEMPTY" \
      -f number,short_description,priority,opened_at -d true -o table

# aging: still open after 30 days
snowq query incident -q "assignment_group.name=$GROUP^active=true^opened_atRELATIVELE@day@ago@30" \
      -f number,short_description,priority,assigned_to,opened_at \
      -d true --order-by opened_at -o table

# who is carrying what
snowq query incident -q "assignment_group.name=$GROUP^active=true" \
      -f assigned_to,number,priority,state -d true --order-by assigned_to -n 0 -o table

# one person's queue
snowq query incident -q "assigned_to.name=$ASSIGNEE^active=true" \
      -f number,short_description,state,priority,opened_at -d true -o table
```

Find the exact group name — they are easy to mistype — with:

```sh
snowq query sys_user_group -q "nameLIKE$GROUP" -f name,sys_id,manager -d true -o table
```

Group membership lives in its own table:

```sh
snowq query sys_user_grmember -q "group.name=$GROUP" -f user -d true -n 0 -o table
```

### Several groups at once

`IN` takes a comma-separated list with no spaces; `STARTSWITH` covers a naming
convention:

```sh
snowq query incident -q "assignment_group.nameIN$GROUP,$OTHER_GROUP^active=true" \
      -f number,assignment_group,state,priority,assigned_to -d true -o table

snowq query incident -q "assignment_group.nameSTARTSWITH$GROUP_PREFIX^active=true" \
      -f number,assignment_group,state,priority -d true -n 0 -o csv > backlog.csv
```

### Backlog per group, without pulling records

`snowq count` answers one filter at a time. For a breakdown in a single call,
reach the same Aggregate API through `raw` — this is the cheapest team-level
report there is:

```sh
snowq raw /api/now/stats/incident \
      -p "sysparm_query=active=true^assignment_group.nameSTARTSWITH$GROUP_PREFIX" \
      -p sysparm_count=true \
      -p sysparm_group_by=assignment_group \
      -p sysparm_display_value=true
```

Each entry carries `groupby_fields` and `stats.count`. Drop
`sysparm_display_value=true` and the groups come back as sys_ids.

### Reporting pulls

```sh
# a month of one category, for a review deck
snowq query incident -q "category=Cloud^opened_atRELATIVEGE@day@ago@30" \
      -f number,short_description,state,priority,assignment_group,assigned_to,opened_at \
      -d true -n 0 -o csv > incidents.csv

# what got resolved, and how — close-code quality
snowq query incident -q "assignment_group.name=$GROUP^stateIN6,7^sys_updated_onRELATIVEGE@day@ago@90" \
      -f number,short_description,close_code,close_notes,assigned_to \
      -d true -n 0 -o table

# volume only
snowq count incident -q "assignment_group.name=$GROUP^active=true"
```

State numbers differ per instance — check yours with the `sys_choice` query above
before trusting `stateIN6,7`.

## Server inventory

```sh
# full inventory for a patch or audit cycle
snowq query cmdb_ci_server -q "operational_status=1" \
      -f name,os,os_version,ip_address,support_group,owned_by,environment \
      -d true -n 0 -o csv > servers.csv

# CMDB hygiene: live servers with no owner or support group — a recurring audit finding
snowq query cmdb_ci_server -q "operational_status=1^support_groupISEMPTY^ORowned_byISEMPTY" \
      -f name,os,ip_address,sys_updated_on -d true -n 0 -o table

# stale records: not touched by discovery in 90 days, so the CMDB may be lying
snowq query cmdb_ci_server -q "operational_status=1^sys_updated_onRELATIVELT@day@ago@90" \
      -f name,sys_updated_on,discovery_source -d true --order-by sys_updated_on -o table

# one OS family, for an end-of-support campaign
snowq query cmdb_ci_server -q "osLIKEWindows^os_versionLIKE2012" \
      -f name,os_version,environment,support_group -d true -n 0 -o csv
```

## Change management

```sh
# what is scheduled for the next 7 days — CAB prep
snowq query change_request -q "start_dateRELATIVELE@day@ahead@7^active=true" \
      -f number,short_description,type,risk,start_date,assignment_group,cmdb_ci \
      -d true --order-by start_date -n 0 -o table

# emergency changes raised in the last 30 days — the first thing an auditor asks for
snowq query change_request -q "type=emergency^sys_created_onRELATIVEGE@day@ago@30" \
      -f number,short_description,requested_by,approval,start_date,close_code \
      -d true -n 0 -o csv > emergency-changes.csv

# changes that did not land cleanly — change-failure-rate evidence
snowq query change_request -q "close_codeNOT LIKEsuccessful^stateIN3,4^sys_created_onRELATIVEGE@day@ago@90" \
      -f number,short_description,close_code,close_notes,assignment_group \
      -d true -n 0 -o table

# volume by month, without pulling the records
snowq count change_request -q "type=emergency^sys_created_onRELATIVEGE@day@ago@30"
```

## Tying changes to infrastructure

```sh
# every change against one server, newest first
snowq query change_request -q "cmdb_ci.name=PRDAPP001" \
      -f number,type,state,start_date,short_description \
      -d true --order-by -start_date -o table

# affected CIs on a change (task_ci is the many-to-many table; cmdb_ci holds only the primary)
snowq query task_ci -q "task.number=CHG0031234" -f ci_item -d true -n 0 -o table

# changes touching anything in one support group's estate
snowq query change_request -q "cmdb_ci.support_group.name=Unix Platform Engineering" \
      -f number,cmdb_ci,type,start_date,state -d true -n 0 -o csv
```

Dot-walking works inside `-q` (`cmdb_ci.support_group.name`), which saves joining
exports by hand. `RELATIVEGE@day@ago@30` and `RELATIVELE@day@ahead@7` are relative
date filters — the unit can be `minute`, `hour`, `day`, `week`, `month`, `quarter`
or `year`.

Everything here is read-only and runs as you, so results are already filtered by
your ACLs. A query returning nothing can mean the records do not exist *or* that
you cannot see them; `snowq count` on the same filter tells you which.

## Scheduled exports

`examples/export.py` replaces the recurring "open the list view, filter,
right-click, Export > CSV" chore. Each pull is defined once in `EXPORTS`, and every
run writes `<name>-YYYY-MM-DD.csv`, so you get a dated trail instead of overwriting
last month's file.

```sh
python examples/export.py -i acme -o ./exports
python examples/export.py -i acme --only servers      # just one
```

It exits 3 when the session has expired and 4 when the instance is unreachable, so
a scheduled run fails loudly rather than quietly writing empty files. A single
failing table does not abort the others.

The catch worth planning for: this rides your browser session, so an unattended
schedule still needs someone to refresh it — daily-ish for a cookie header, longer
if you use `snowq login` with a persistent profile. That makes it a good fit for a
desk-side chore on a weekly or monthly cadence, and a poor one for an unattended
server. For that, ask your ServiceNow team for a service account and integration
credentials.
