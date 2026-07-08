# Test Inventory — Domain DON (tests/donor)

> Complete. 20 files, 296 class-level test methods classified. Nested helper `test_user_access` (inside `test_production_concurrent_access_scenarios` in `test_donor_security_enhanced.py`) was excluded per method-only scope, so that file has 10 class-level tests rather than the 11 a naive `grep def test_` would count.

Classification legend: HAPPY = nominal success path; UNHAPPY = expects error/throw/validation-failure/permission-denial; EDGE = boundary/empty/null/duplicate/idempotency/malformed/eleven-proof/encryption-at-rest; OTHER = smoke/import-safety/setup-only/tautological/no-assert/skip-dominated.

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_anbi_donation_agreement_validation.py | 17 | 7 | 7 | 3 | 0 |
| test_anbi_validation_service.py | 17 | 6 | 6 | 4 | 1 |
| test_campaign_donation_integration.py | 6 | 3 | 0 | 3 | 0 |
| test_donation_agreement.py | 12 | 10 | 0 | 2 | 0 |
| test_donor_auto_creation_comprehensive.py | 15 | 9 | 2 | 4 | 0 |
| test_donor_auto_creation_helpers.py | 7 | 2 | 0 | 5 | 0 |
| test_donor_auto_creation.py | 12 | 6 | 2 | 4 | 0 |
| test_donor_customer_api.py | 14 | 9 | 4 | 0 | 1 |
| test_donor_customer_integration.py | 13 | 7 | 1 | 3 | 2 |
| test_donor_customer_sync_coverage.py | 4 | 2 | 0 | 2 | 0 |
| test_donor_customer_sync_utils.py | 14 | 5 | 2 | 6 | 1 |
| test_donor_member_reconciliation_coverage.py | 15 | 5 | 1 | 9 | 0 |
| test_donor_permissions.py | 15 | 4 | 7 | 2 | 2 |
| test_donor_permissions_security.py | 14 | 3 | 4 | 4 | 3 |
| test_donor_security_comprehensive.py | 18 | 5 | 4 | 4 | 5 |
| test_donor_security_core.py | 12 | 2 | 4 | 5 | 1 |
| test_donor_security_enhanced_fixed.py | 12 | 5 | 4 | 2 | 1 |
| test_donor_security_enhanced.py | 10 | 3 | 4 | 2 | 1 |
| test_donor_security_working.py | 14 | 4 | 3 | 6 | 1 |
| test_other_service_coverage.py | 55 | 19 | 13 | 16 | 7 |
| **DOMAIN TOTALS** | **296** | **116** | **68** | **86** | **26** |

## Observations

- **EDGE-heavy domain (86/296, 29%).** The donor suite invests disproportionately in boundary/guard-condition coverage: empty/None inputs, nonexistent/dangling references, disabled-flag short-circuits, duplicate-prevention/idempotency, malformed/unicode/injection inputs, and threshold boundaries (min donation amount, €500 reportable, file-size cap, 5-year ANBI minimum). This is appropriate for a domain full of tax-compliance (ANBI/BSN/RSIN) and permission logic.
- **Security-permissions cluster is large and heavily duplicated.** Seven files (`test_donor_permissions*.py` + five `test_donor_security_*.py`) cover the same `has_donor_permission` / `get_donor_permission_query` surface. `test_donor_security_enhanced.py` and `..._enhanced_fixed.py` are near-identical (same test names, different fixtures); `..._core.py`, `..._working.py`, and `..._comprehensive.py` re-exercise SQL-injection escaping, admin override, orphaned-donor denial, and doc-vs-string handling repeatedly. Strong consolidation candidate.
- **Many security tests are mixed grant+deny matrices** (access-isolation, org-permission-matrix, context-switching). I classified these by their distinctive/protective assertion: isolation/matrix/session-leak → UNHAPPY (the risky assertion is the denial), positive chain/role/query-generation validation → HAPPY. A reasonable auditor could shift ~6-8 of these between HAPPY/UNHAPPY.
- **OTHER (26/296, 9%) concentrates in three patterns:** (1) performance/timing tests (`test_performance_*`, `..._under_attack`, `..._under_load`) that assert only wall-clock bounds; (2) tautological/no-assert tests (`assertTrue(True)`, `assertTrue(error_handled)` from try/except, `sync_only_when_changes_detected` has no assertion, TeamService `sync_with_volunteers`/`validate_team_member_changes` always return True); (3) structural "shape" smoke on dashboard aggregates that only assert dict-key presence or `isinstance(..., list)`.
- **One skip:** `test_concurrent_access_simulation` (`test_donor_permissions_security.py`) is `@unittest.skip`-ed with a detailed rationale (Frappe thread-local DB makes raw `threading.Thread` workers deterministically fail) — counted under OTHER. A second threading test (`test_production_concurrent_access_scenarios`) actually runs and asserts a grant/deny matrix across threads but is fragile for the same reason; also OTHER.
- **UNHAPPY (68/296, 23%) is genuine, not incidental:** real `assertRaises(frappe.ValidationError)` for ANBI duration/duplicate/zero-amount, date ordering, nonexistent role profiles; typed error envelopes (`DONOR_NOT_FOUND`, `NO_CUSTOMER_LINKED`); permission denials for guests/unauthorized/orphaned/cross-member; and account-validation rejections (no/invalid email, banned status, name mismatch).

## Notes on file/method counts

- No zero-method files; all 20 files contain class-level tests.
- `test_donor_security_enhanced.py`: 10 class-level methods (a nested helper named `test_user_access` is excluded).
- All other files' class-level method counts match `grep -cE "^\s+def test_"`.
