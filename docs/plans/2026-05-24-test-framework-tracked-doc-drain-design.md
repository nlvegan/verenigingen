# Test framework fix — drain `track_document` in tearDown

**Status:** VERIFIED — hypothesis confirmed via DB query (see Verification below); awaiting user approval to implement
**Date:** 2026-05-24
**Related memory:** `test-suite-crisis-2026-05-22`, codebase-health-audit-2026-05-17 (Tier 5)
**Related PRs:** #57 (chapter membership tearDown), #60 (ANBI clarity teardown), #62/#69/#70 (super() sweep)

## Problem

Three prior PRs (#57, #60, plus one earlier) fixed individual instances of "tests
leak orphan records that trip uniqueness violations on the next run." Each was
treated as a one-off. The orphan-accumulation sweep run on 2026-05-24 found
this is actually the visible tip of a **framework-level gap**, not a series of
isolated test bugs.

### The framework state today

`EnhancedTestCase` has three cleanup layers:

1. **Per-method rollback** in `tearDown()` (`enhanced_test_factory.py:1601`) —
   `frappe.db.rollback()`. Handles uncommitted data.
2. **Class-level stale-data cleanup** in `setUp()` once per class
   (`_cleanup_stale_test_data`, line 2027). Pattern-matches names like
   `first_name LIKE 'Test%'`, emails `@test.invalid`, etc. Handles committed
   data from previous runs.
3. **`track_document()`** (line 422) — appends to `self.created_documents`.
   But **nothing ever drains this list.** `get_cleanup_summary()` reads it
   for reporting; no code deletes the tracked records.

### The gap

When a test calls `frappe.db.commit()` (55 such files in the suite, AST-scanned),
the per-method rollback can't undo. The committed records survive into the next
test class — IF they don't match the narrow `_cleanup_stale_test_data` patterns,
they survive forever.

Tests commonly use **semantic** first_name prefixes that the patterns miss:
`Active`, `Eligibility`, `Source`, `Critical`, `Integration`, `Enhanced`, `Jan`,
`Maria`. Their auto-created Customer records have names like `Active Member5`,
`Source Member1` — none match the `Admin User %` / `Board Member %` /
`Regular Member %` / `Test %` / `TestMember%` patterns either.

`track_document()` is called when the factory creates records, so the framework
**already knows what was created** — it just throws the information away. The
auto-created Customer (`test_data_factory.py:181` — `member.create_customer()`)
is not tracked at all, though the Customer's Address is (line 215).

## Hypothesis

Adding a tearDown drain over `factory.created_documents` (+ tracking the auto-Customer)
will eliminate orphan accumulation for **all** factory-using tests in one change,
without per-test rewrites.

## Verification (DONE 2026-05-24)

Queried `veg11.veganisme.org` (the active dev site) directly. Sample:

```
SELECT first_name, COUNT(*) FROM tabMember
WHERE email LIKE "%@test%" OR email LIKE "%@example.com"
   OR email LIKE "%.test"  OR email LIKE "%.invalid"
GROUP BY first_name ORDER BY cnt DESC LIMIT 30;
```

Returned 200+ orphan Members with test-only emails but first_names that **do
not match** the existing `_cleanup_stale_test_data` patterns:

| first_name | count |
|---|---|
| Adam | 126 |
| Chapter | 24 |
| Board0 / Board1 / Board2 | 23 each |
| Load | 13 |
| Regular | 6 |
| (many more) | |

Companion Customer query:

```
SELECT COUNT(*) FROM tabCustomer c
WHERE c.creation > "2026-04-01"
  AND NOT EXISTS (SELECT 1 FROM tabMember m WHERE m.customer = c.name)
  AND (c.customer_name LIKE "%Member%" OR c.customer_name LIKE "Adam%"
       OR c.customer_name LIKE "Board%" OR ...);
```

→ **686 orphan Customer records since 2026-04-01.** These are the records
that produce Customer.PRIMARY duplicate violations on subsequent runs.

Hypothesis confirmed. The framework gap is real, large in scope (every
factory-using committing test is a contributor), and actively causing failures.

## Proposed fix

### Change 1 — Track auto-created Customer in Core factory

File: `verenigingen/tests/fixtures/test_data_factory.py`

In `_create_customer_for_member()` (line 175), after `member.create_customer()`,
add `self.track_doc("Customer", member.customer)` so the auto-created Customer
joins the tracked list alongside the Address.

### Change 2 — Drain tracked docs in tearDown

File: `verenigingen/tests/fixtures/enhanced_test_factory.py`

In `EnhancedTestCase.tearDown()` (line 1549), AFTER `frappe.db.rollback()` and
BEFORE `super().tearDown()`, call a new helper `_drain_tracked_documents()`:

```python
def _drain_tracked_documents(self):
    """Delete factory-tracked documents that survived per-method rollback.

    `frappe.db.rollback()` undoes uncommitted writes; this drain handles
    committed writes (`frappe.db.commit()` in test bodies or production code).
    Without this, committed test data accumulates across runs.

    Combines tracking from Enhanced (priority-sorted) and Core (creation-order).
    """
    if not hasattr(self, 'factory'):
        return

    tracked = []
    for d in getattr(self.factory, 'created_documents', []):
        tracked.append((d['doctype'], d['name'], d.get('priority', 0), 'enhanced'))
    if hasattr(self.factory, 'core'):
        for d in getattr(self.factory.core, 'created_records', []):
            tracked.append((d['doctype'], d['name'], 0, 'core'))

    # Dedupe (Member is tracked by both layers)
    seen = set()
    unique = [t for t in tracked if (t[0], t[1]) not in seen and not seen.add((t[0], t[1]))]

    # Highest priority deletes first (matches Enhanced's contract)
    unique.sort(key=lambda x: -x[2])

    for doctype, name, _prio, _src in unique:
        try:
            if frappe.db.exists(doctype, name):
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
        except Exception as e:
            frappe.logger().debug(f"Drain delete failed {doctype}/{name}: {e}")

    self.factory.created_documents = []
    if hasattr(self.factory, 'core'):
        self.factory.core.created_records = []

    frappe.db.commit()  # persist the cleanup
```

### What this does NOT fix

- Tests that bypass the factory (`frappe.new_doc("Customer")` directly in
  `test_eligibility_checker.py:39` etc.). Those records aren't tracked, so
  they'll still leak. A documented convention + a separate spot-check pass can
  pick them up.
- Records created by production code as a side effect of factory calls
  (e.g. Membership Dues Schedule auto-created by Membership.on_submit). These
  aren't tracked either. If they emerge as a problem, broaden tracking or
  pattern-match in `_cleanup_stale_test_data`.

## Risks

1. **Performance** — Per-method drain adds N delete operations + 1 commit per
   test. Mitigation: typical test creates 1-5 docs; delete-by-name is O(1);
   net overhead ~50-200ms per test. Worth the isolation guarantee.
2. **Breaking class-level shared state** — Tests using `setUpClass` to create
   docs shared across methods would have those docs deleted after each test.
   Mitigation: `self.factory` is recreated in `setUp()` (line 1532), so
   `factory.created_documents` is per-method anyway. Class-level docs aren't
   in the tracked list. Safe.
3. **Exposing latent bugs** — Some tests may currently pass because of leaked
   state from a previous test (the very anti-pattern we're closing). Those
   will start failing. Treat as a feature: surfaced bugs are real bugs.
4. **Cascading delete failures** — Frappe's `force=True` bypasses link checks,
   but cascading hooks (e.g., before_delete) could still raise. Mitigation:
   per-doc try/except → log + continue, never break the test run.

## Rollout

1. Verify hypothesis (above).
2. Implement Changes 1 + 2 in one PR.
3. Run the full test suite locally. Expect: some currently-passing tests will
   newly fail (state-leakage dependencies surfaced). Document each.
4. Triage newly-red tests:
   - Real bugs (state-leakage masking) → file separate fix tickets.
   - Tests that genuinely depended on shared state → either rewrite or move
     setup to `setUpClass` with explicit tracking.
5. CI baseline: capture failure count diff. Expect the count to MOVE — many
   currently-red may go green (no longer flaky from contamination); some
   currently-green may go red.
6. PR description must include the baseline-diff numbers.

## Out of scope

- Fixing tests that bypass the factory (`frappe.new_doc` in test code). Separate
  audit + PR.
- Decommissioning the `_cleanup_stale_test_data` pattern matcher. The drain is
  additive, not a replacement. The pattern matcher still catches docs from
  pre-fix runs and from tests that bypass the factory.
- `super()` sweep on `FrappeTestCase` + `VereningingenTestCase` subclasses.
  Separate work.
