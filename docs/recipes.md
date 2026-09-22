# Recipes: servers and changes

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
