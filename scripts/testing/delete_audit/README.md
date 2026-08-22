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

```bash
# 1. record, during the run
DELETE_AUDIT_LOG=/tmp/audit.jsonl \
  PYTHONPATH=scripts/testing/delete_audit \
  bench --site test_site_1 run-tests --app verenigingen --module <module>

# 2. check, afterwards, in its own process
cd sites && ../env/bin/python ../apps/verenigingen/scripts/testing/delete_audit/check_survivors.py \
  test_site_1 /tmp/audit.jsonl
```

Two processes on purpose. The checker has no connection-lifetime problem at interpreter
exit, and it sees only **committed** state — which is the contamination question. A row
transiently resurrected and rolled back at class end never mattered; one that outlives
the run is what poisons the next shard.

`selftest.sh` runs both halves against four planted cases and asserts the verdicts.

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

## What it does NOT do

- **It does not judge intent.** A test that deliberately deletes a row inside its own
  transaction and expects the rollback to restore it is reported too. This is a census
  instrument; a survivor is a question, not a verdict.
- **It does not catch a delete that never reported success.** Those are the leak
  ratchet's business (`scripts/testing/check_test_leaks.py`).
- **It does not record filtered bulk deletes.** `frappe.db.delete(dt, {"status": "X"})`
  has no docname; only the unambiguous shapes are recorded, and saying so beats guessing.
- **It is not a gate.** No baseline, nothing fails on a survivor. Making it one needs a
  census across the whole suite first — the mistake the `HARNESS_FILES` ratchet made was
  gating a population nobody had counted (0 of 93).

## Measured

First census, 7 modules on `test_site_5`: **1 survivor in 336 recorded deletes**
(`Chapter::Test Amsterdam Chapter`, → #498). `test_event_driven_payment_history` read
**0 of 9**, which is the negative control on real code: that is #486's module, fixed on
develop.
