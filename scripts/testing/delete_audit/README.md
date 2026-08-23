# Delete-resurrection auditor

Answers one question the harness cannot answer about itself: **for every delete that
reported success, is the row actually gone?**

## Why this exists

Three separate issues in this repo were the same defect — a delete inside the test
transaction, undone by a later rollback — and each was found by hand, one module at a
time, with a probe that was then thrown away:

| instance | how it was found |
|---|---|
| #407 `_purge_orphan_claims` | a skeptical review of an unrelated PR |
| #486 the drain's per-document rollback | one instrumented print, after two sessions |
| #489 `TestCleanupManager` vs the base teardown | a throwaway probe |

Every cleanup in the harness reports its own success, and every one of those reports has
lied at least once: `cleanup_status == "skipped"` means "did not exist when I looked",
an empty error list means "nothing raised", and a global orphan join reads 0 either way
once `revert_series_if_last` reuses the name. This asks the database instead.

## Running it

`PYTHONPATH` must be **absolute**. `bench` runs from the bench root, where
`scripts/testing/delete_audit` does not exist, so the relative form an earlier version of
this file showed loaded nothing, created no log, and reported `OK` — measured.

```bash
AUDIT=$PWD/apps/verenigingen/scripts/testing/delete_audit   # from the bench root

# 1. record, during the run. The log path must not already exist.
DELETE_AUDIT_LOG=/tmp/audit-$$.jsonl PYTHONPATH="$AUDIT" \
  bench --site test_site_1 run-tests --app verenigingen --module <module>

# 2. check, afterwards, in its own process
cd sites && ../env/bin/python "$AUDIT/check_survivors.py" test_site_1 /tmp/audit-$$.jsonl
```

The first line of the log is an `armed` marker. If it is missing the checker exits **2**
and says so, instead of printing `recorded=0` — which was indistinguishable from a clean
run, and is the instrument failure this tool exists to replace. The recorder also refuses
a log path that already has content, because appending merges two runs and attributes the
first one's rows to the second.

Two processes on purpose. The checker has no connection-lifetime problem at interpreter
exit, and it sees only **committed** state — which is the contamination question. A row
transiently resurrected and rolled back at class end never mattered; one that outlives
the run is what poisons the next shard.

`selftest.sh` runs both halves against **five** planted cases and asserts the verdicts,
plus two positive requirements on the recorder itself: that it armed, and that it saw all
five planted deletes. Those two matter more than the verdicts. Measured: with
`_install_frappe_hooks` stubbed out — a completely dead recorder — "a delete that stuck is
NOT reported" and "an already-gone row is not a delete" both stayed **green**, because they
are `grep -c == 0` assertions with no positive requirement. They still do; the two new
checks are what turns the suite red.

The control module skips itself unless **`DELETE_AUDIT_SELFTEST`** is set — deliberately not
`DELETE_AUDIT_LOG`. Two of its five cases strand a row on purpose (the checker runs
afterwards, in another process, and can only read committed state, so cleaning up in the
test would leave it nothing to read). Gating on the recorder variable would re-arm those two
rows during any suite-wide census, which is the tool's own stated next step. Only
`selftest.sh` sets `DELETE_AUDIT_SELFTEST`, and it sweeps the rows on the way out.

## Verdicts

| verdict | meaning |
|---|---|
| `SURVIVED` | the delete reported success and the **same row** (same `creation`) is still there |
| `RECREATED` | same docname, **different row** — a get-or-create fixture rebuilt it. Not this defect |
| `UNVERIFIABLE` | the pre-delete `creation` read failed, so "cannot tell" — never reported as a resurrection |
| `UNKNOWN-DOCTYPE` | the doctype does not exist, so the delete could never have run (#491) |

`RECREATED` is not a nicety. The first census run reported
`Chapter::Test Amsterdam Chapter` as a survivor, and a name-only auditor would have
called every recreated shared fixture a resurrection. It turned out to be a real
resurrection — same `creation` — which is #498, but only the timestamp could tell them
apart.

`SURVIVED-CREATION-REWRITTEN` exists because `creation` is not immutable here. Four live
sites in this app rewrite it — a Company backdated to `2000-01-01`, a Sales Invoice, and two
raw `UPDATE tabMember SET creation = DATE_SUB(NOW(), ...)`. Without that branch a genuine
resurrection whose `creation` was rewritten mid-transaction reads `RECREATED`: the tool going
silent on precisely the defect it exists to find. The two raw-SQL backdaters use `NOW()`,
which is second-precision, so several rows backdated in one second share a `creation` exactly
— the column itself is `datetime(6)`, so ordinary inserts are safe, but those sites are not.

## What it does NOT do

- **It does not judge intent.** A test that deliberately deletes a row inside its own
  transaction and expects the rollback to restore it is reported too. This is a census
  instrument; a survivor is a question, not a verdict.
- **It does not catch a delete that never reported success.** Those are the leak
  ratchet's business (`scripts/testing/check_test_leaks.py`).
- **It does not record filtered bulk deletes.** `frappe.db.delete(dt, {"status": "X"})`
  has no docname; only the unambiguous shapes are recorded, and saying so beats guessing.
  `{"name": ["in", [...]]}` is a filter too, and is likewise not recorded.
- **It does not see raw SQL.** `frappe.db.sql("delete from `tabX` ...")` bypasses
  `Database.delete` entirely. There are **60** raw `DELETE FROM` sites under
  `verenigingen/`, five of them in `enhanced_test_factory` — the harness's own cleanup,
  i.e. part of the population under audit. This is the largest blind spot.
- **It does not see child rows cascaded by a parent delete.** `delete_doc` removes them with
  `frappe.db.delete(child, {"parenttype": ..., "parent": ...})` — two filter keys, so not
  recorded. Harmless when the whole parent delete is undone (the parent is reported), but a
  cleanup that deletes child rows directly is unwatched.
- **It does not see deletes in another process.** A subprocess, or an RQ worker, has its own
  interpreter and never loads the recorder.
- **It is not a gate.** No baseline, nothing fails on a survivor. Making it one needs a
  census across the whole suite first — the mistake the `HARNESS_FILES` ratchet made was
  gating a population nobody had counted (0 of 93).

## Measured

First census, 7 modules on `test_site_5`: **1 survivor in 336 recorded deletes**
(`Chapter::Test Amsterdam Chapter`, → #498).

**There is no negative control on real code, and an earlier version of this file claimed
one.** It said `test_event_driven_payment_history` reads "0 of 9" because #486 fixed that
module on develop. Re-measured on `test_site_2`: **7 runs of that module, one of which read
`recorded=10 survived=4`** — a submitted Sales Invoice, a Customer, a Contact and a second
Customer, all same-`creation`, all still on the site. The other six read `9/0`. So the
observed rate is 1 in 7, not 0, and a single zero reading from an intermittent process is not
a control (#517). Do not quote a zero from this tool as evidence a module is clean without
saying how many runs produced it.
