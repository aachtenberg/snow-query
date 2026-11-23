# Testing against a developer instance

A free personal developer instance (developer.servicenow.com) gives you a real
ServiceNow to point snowq at. Out of the box it has plenty of records but only
stock fields and stock choice values, and those are not what goes wrong on a
customised instance. Two scripts close that gap:

| Script | What it does |
|---|---|
| `util/seed_dev.py` | Writes a customised layer onto the instance (below). Re-running skips what exists; `--clean` removes all of it. |
| `util/record_fixtures.py` | Records read-only calls against the seeded instance into `tests/fixtures/seeded_instance.json`, which `tests/test_fixtures.py` replays offline. |

```sh
PDI=dev12345                                                  # your instance
./snowq -i "$PDI" login                                       # sign in; both scripts use this session
uv run --no-sync python util/seed_dev.py -i "$PDI"
uv run --no-sync python util/record_fixtures.py -i "$PDI"     # only when the fixtures should change
uv run --no-sync python util/seed_dev.py -i "$PDI" --clean    # undo the seed
```

`--no-sync` matters: a plain `uv run` re-syncs without the `login` extra and
removes Playwright.

## What the seed adds

- Custom fields on `incident` whose labels are not their names:
  `u_business_impact` "Business impact" (integer choice: 10, 20, 30, 40),
  `u_vendor_ticket` "Vendor reference", `u_regulated` "SOX in scope", and
  `u_escalation_group` "Escalate to" (a reference to `sys_user_group`).
- A non-standard incident state: `18` "Awaiting Vendor".
- Two groups, three servers and twelve incidents that use all of it. Every
  record is marked `snowq-seed` (in `correlation_id`, or the name), which is
  how re-runs and `--clean` find them.

Before writing, it checks that the stock choice values it relies on exist on
the instance, and picks a close code the instance actually offers.

## Safety

snowq stays read-only. The seed writes through the same saved session from
outside the CLI, and refuses any host that is not `devNNNNN.service-now.com`
unless you pass `--any-instance`. Never pass that for an instance other people
use.

The recorder swaps the instance host for `acme.service-now.com` and refuses to
write a recording that still names the instance.

## Things this instance taught us

- Its login form is served from `navpage.do` itself, and that page already
  carries a guest-session `g_ck`. `snowq login` now waits for the instance to
  confirm a real user instead of stopping at the first token.
- `impact` and `urgency` on incident keep their choices on `task`; `state` is
  overridden on incident. Query `sys_choice` with `nameINincident,task`.
- Some close codes ("Known error", "Duplicate", "Resolved by problem") trip
  business rules that want a linked record, so an insert with one fails with a
  403 naming the rule.
- An empty choice field under `-d all` has `display_value: null`, not `""`.
- A developer instance hibernates when idle. A sleeping instance looks like an
  expired session (exit 3) or an unreachable one (exit 4); wake it from the
  developer portal.
