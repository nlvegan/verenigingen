# Test framework fix — drain `track_document` in tearDown

**Status:** IMPLEMENTED — PR #79; revised post double-review (skeptical + senior reviewers, see Revision Log)
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

- **`VereningingenTestCase` hierarchy** (127 files at
  `verenigingen/tests/utils/base.py:44` and its descendants). Only
  `EnhancedTestCase` (339 files) gets the drain. The two hierarchies are
  parallel; closing the gap on the other one is a separate follow-up.
- **Tests that bypass the factory** (`frappe.new_doc("Customer")` directly,
  e.g. `test_eligibility_checker.py:39`). Those records aren't tracked, so
  they still leak. `test_eligibility_checker.py` alone has 27 commit calls
  and is already broken at HEAD (the test creates the auto-Customer twice
  via the factory and then manually). A grep audit for
  `frappe.new_doc("Customer"|"Member"|"Sales Invoice")` in test files is
  warranted as a follow-up.
- **Submitted documents** (`docstatus=1`). `delete_doc(force=True)` does
  NOT bypass the submitted-doc check at
  `frappe/model/delete_doc.py:287-297`. Tracked Sales Invoices, Payment
  Entries, and submitted Memberships will fail to delete and surface as a
  `WARNING`-level log line (see drain logging behaviour). Membership
  happens to survive because Member's `on_trash` cascade cancels +
  deletes it (`services/member/lifecycle/member_cleanup_service.py:172-174`).
  Standalone submitted docs need either a cascade path or explicit
  `cancel()` in the test code.
- **Side-effect records from production code** not visible to the factory
  (e.g. Membership Dues Schedule auto-created in `Membership.on_submit`).
  If they emerge as a problem, extend factory tracking or pattern-match
  in `_cleanup_stale_test_data`.

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

## Revision Log

### 2026-05-24 — Post-review revisions (PR #79 follow-up commit)

Two reviewers (skeptical-code-reviewer + code-quality-reviewer) ran in
parallel. None found critical bugs. The following material findings were
addressed before merge:

1. **Master-data deletion risk (critical-near-miss, skeptical S3).**
   `_ensure_master_data()` fallback paths tracked `Company`, `Fiscal Year`,
   `"All Departments"` (the ERPNext root), and `"Netherlands"` Territory
   at priority=1. If any fallback fired, the drain would delete these
   shared roots, corrupting subsequent tests and any production data
   linked to them. **Fix:** stopped tracking those four in the fallback
   paths (root-cause fix). Also added defensive contract in the drain:
   records with `priority < 0` are skipped. Anyone adding new
   session-scoped infrastructure should use negative priority.

2. **Dedupe priority bug (correctness, senior M6).** Previous dedupe kept
   the FIRST-SEEN priority for a (doctype, name) pair. For docs tracked
   by both Enhanced (priority=5) and Core (priority=0), this could
   discard the higher priority and reverse the documented delete order.
   **Fix:** dedupe now keeps the HIGHEST priority across sources. New
   regression test `test_dedupe_keeps_highest_priority_across_sources`.

3. **Rollback-failure + drain commit interaction (correctness, skeptical
   S1).** If the tearDown rollback raised and was swallowed by the outer
   try/except, the drain's final commit would persist whatever
   uncommitted test state remained. **Fix:** drain now issues a
   defensive `frappe.db.rollback()` before any DELETE. If THAT rollback
   raises, drain skips both deletes and commit, logs WARNING, clears
   tracking lists.

4. **Silent failure logging (visibility, both reviewers).** Per-doc
   delete failures logged at `debug` were invisible in CI logs. **Fix:**
   `frappe.DoesNotExistError` (cascaded-from-parent) stays silent;
   anything else logs WARNING with doctype/name; aggregate
   end-of-drain WARNING fires if any delete failed.

5. **Empty-drain optimization (perf, senior M4).** Drain paid the cost
   of building tracked, iterating, and committing even when nothing was
   tracked. **Fix:** early return after dedupe if `unique` is empty.
   Saves a MariaDB round-trip per read-only test method.

6. **Idempotency test gap (test quality, skeptical S10 / senior L8).**
   Previous test only checked that lists were empty after two drains;
   didn't verify the first call actually deleted anything. A no-op
   implementation would have passed. **Fix:** test now asserts records
   gone after first drain, plus state remains clean after second.

7. **Documentation accuracy (senior M5, skeptical S4).** Design doc's
   "defence-in-depth" framing was incorrect: `_cleanup_stale_test_data`
   doesn't run on `veg11.veganisme.org` (site not in approved list).
   Doc also incorrectly claimed coverage of `VereningingenTestCase`
   hierarchy. **Fix:** scope narrowed in "What this does NOT fix";
   `VereningingenTestCase` sweep added to "Out of scope" follow-ups.

### Pushback / non-issues

- **Senior I1 (scalability test AttributeError).** Reviewer flagged
  `test_payment_history_scalability.py:81` calling `self.factory.cleanup()`.
  Verified: that test overrides `self.factory` to `PaymentHistoryTestFactory`
  (line 61) which has its own `cleanup()` method. The drain uses
  `getattr(self.factory, 'created_documents', [])` so it cleanly no-ops
  on factories that don't expose that attribute. Not a bug.

- **Submitted-doc *automatic* cancel (skeptical S2).** Reviewer
  suggested the drain could `cancel()` docstatus=1 docs before delete.
  Deferred: this would silently mask test bugs (tests submitting docs
  without explicit cleanup are wrong). Instead, the drain now logs at
  WARNING so leakage is visible. Tests creating submittable docs must
  cascade cleanly or explicitly cancel.

- **Test file location at top-level `tests/` (senior L7).** Intentional:
  the file is about the test framework itself, alongside the existing
  `test_framework_enhanced.py` shim. Not a domain test.
