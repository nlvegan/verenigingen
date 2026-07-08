# Domain A5 — Termination + Chapter + Volunteer services

Read-only test-method inventory. Every `def test_*` method classified by dominant
intent: HAPPY (nominal success), UNHAPPY (expects error/throw/validation-failure/
permission-denial/rejection), EDGE (boundary/empty/null/zero/duplicate/idempotency/
concurrency/ordering/unusual-data/alternate-flag), OTHER (smoke/shape/tautological).

12 files, 258 test methods.

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| tests/services/test_termination_approval_service.py | 26 | 15 | 9 | 2 | 0 |
| tests/services/test_termination_execution_service.py | 15 | 2 | 6 | 6 | 1 |
| tests/services/test_termination_operations.py | 22 | 15 | 1 | 5 | 1 |
| tests/services/test_chapter_management_service.py | 18 | 9 | 2 | 6 | 1 |
| tests/services/test_chapter_permission_service_integration.py | 20 | 15 | 3 | 2 | 0 |
| tests/services/test_volunteer_activity_service.py | 19 | 10 | 6 | 3 | 0 |
| tests/services/test_volunteer_assignment_service.py | 19 | 12 | 0 | 6 | 1 |
| tests/services/test_volunteer_assignment_service_simple.py | 13 | 6 | 0 | 6 | 1 |
| services/termination/test_termination_utils.py | 26 | 15 | 3 | 6 | 2 |
| services/termination/test_termination_integration.py | 61 | 30 | 13 | 18 | 0 |
| services/termination/test_termination_integration_coverage.py | 9 | 6 | 0 | 3 | 0 |
| services/termination/test_termination_integration_extra_coverage.py | 10 | 6 | 0 | 4 | 0 |
| **DOMAIN TOTALS** | **258** | **141** | **43** | **67** | **7** |

## Observations

- **Balanced negative coverage overall.** 43 UNHAPPY (17%) + 67 EDGE (26%) = 43% non-happy.
  The termination domain is defensively engineered — helpers return `False`/`0`/error-dicts
  on bad input rather than raising — so a large share of the negative surface lands in EDGE
  and in "missing X returns false" UNHAPPY cases rather than exception-raising.

- **Classification convention applied consistently:** "missing/nonexistent input" (invalid
  identity → error/false) counted UNHAPPY; "valid record with no related data" (no volunteer,
  no employee, no invoices → zero/empty) counted EDGE. This split explains the high EDGE count
  in test_termination_integration.py (18) where nearly every helper has both variants.

- **Execution service is nearly all negative/edge (2 HAPPY of 15).** It targets QCE critical
  fixes: race-condition/idempotency (EDGE), transaction rollback on failure (UNHAPPY),
  savepoint-release regressions, retry recovery — a hardening suite, not a feature suite.
  It also relies heavily on `patch('frappe.db.begin/commit/rollback')` mocking of the
  transaction layer, which weakens the realism of its atomicity claims.

- **The 7 OTHER methods are smoke/shape checks, not tautologies:** singleton-accessor
  isinstance checks (`test_accessor_returns_service`, `test_service_initialization` x2),
  dict-shape contract checks with no data (`test_statistics_shape`,
  `test_audit_compliance_clean_shape`), and `test_continues_on_operation_failure` which
  asserts an `errors` key exists but never actually triggers a failure (its own docstring
  admits "we verify the error handling structure exists").

- **Two volunteer-assignment files overlap heavily.** `_simple` (13 methods) is a strict
  subset of the full file (19 methods) minus board/team/multi-source aggregation — same
  service, same asserts. Redundant coverage; the simple file adds little beyond the full one.

- **Strong regression/discriminator tests in test_termination_utils.py.** Several EDGE tests
  are false-positive guards for a real bug (audit join on `member_name` full-name vs `member`
  ID): `..._valid_request_not_flagged_orphaned` and `..._same_fullname_different_members_not_duplicate`
  deliberately construct two distinct members sharing a full_name — a genuinely meaningful edge.

- **Permission-service file leans HAPPY (15/20)** but its 3 UNHAPPY are true row-level
  denial tests (board member / regular member denied other chapters + write). Heavy per-test
  role-cache/SQL scaffolding to defeat Frappe role-caching pollution; assertions themselves
  are meaningful (query-condition string contents, boolean access results).

## Co-located termination test files found (glob services/termination/test_*.py)

1. `verenigingen/services/termination/test_termination_utils.py`
2. `verenigingen/services/termination/test_termination_integration.py`
3. `verenigingen/services/termination/test_termination_integration_coverage.py`
4. `verenigingen/services/termination/test_termination_integration_extra_coverage.py`
