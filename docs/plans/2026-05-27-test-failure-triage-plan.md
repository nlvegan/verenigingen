# Test Failure Triage Plan — Post Group-C/G CI Sweep

**Date:** 2026-05-27
**Trigger:** After merging PRs #93 (Group C), #94 (G1), #95 (G2), #96 (G3) — cumulative -6,994 LOC of dead/broken test code; remaining failure inventory needs surgical triage rather than bulk deletions.
**Source:** Bench-verified test runs against `veg11.veganisme.org` show three remaining patterns that aren't import/path/field-rename issues.

## Triage rubric

For every failing test method, classify into one bucket:

| Bucket | Meaning | Action |
|---|---|---|
| **A. Scenario valid + currently broken** | Test asserts behavior that the app actually has, but the test is broken (wrong helper field name, schema drift, fixture missing, etc.) | Fix the test |
| **B. Scenario dead** | Test asserts behavior that no longer exists in the app (deleted feature, archived DocType, removed API) | Delete the test (or skip with re-enable trigger if the feature might return) |
| **C. Coverage gap** | Test is a unique assertion of a real behavior, AND no other test covers the same scenario | Fix the test + flag as critical-to-preserve. If unfixable, file a "needs new test" issue for the underlying behavior. |
| **D. Pre-existing infra** | Test fails on local bench because of environment state (e.g., BOM Secondary Item orphan), not the test itself | Document; CI is the authoritative runner |

## Known concrete starting points (from G3 verification, 2026-05-27)

### `test_enhanced_membership_lifecycle.py` — 9 errors, `AttributeError: predefined_tiers`

`setUp` calls `self.create_tier_based_membership_type()` / `self.create_calculator_based_membership_type()` which set a `predefined_tiers` field that doesn't exist on the current `Membership Type` schema.

- Check actual Membership Type fields → find canonical name for tier definition
- If tier definitions moved to a separate DocType (e.g., `Membership Tier`), rewrite the helper
- Bucket: A or C depending on whether tier-based membership tests have equivalent coverage elsewhere

### `test_ponto_webhook_handler.py` — 3 assertion-string failures

| Test | Expected | Actual |
|---|---|---|
| `test_handle_account_revoked` | `logged` | `admin_notified` |
| `test_handle_sync_failed_logs_error` | `sync_failure_logged` | `error_logged` |
| `test_handle_sync_no_change` | `logged` | `no_action_needed` |

Handler return-value strings changed; tests were not updated. Almost certainly Bucket A — update test expectations to match current handler contracts. Check handler implementations in `verenigingen/verenigingen_payments/ponto/api/webhook_handlers.py` to confirm the new strings are intentional vs accidental.

### `test_iban_validation_integration.py` — 1 failure + 1 error

| Test | Issue |
|---|---|
| `test_iban_validation_comprehensive` | Expects `Unsupported country code: XX` but gets `Invalid IBAN checksum` — validation order in `validate_iban` changed |
| `test_member_iban_validation` | `ValidationError: Account Holder Name is required for SEPA Direct Debit payment method` — test omits a now-reqd field |

Both Bucket A. The country-code one might also be a UX regression (less specific error message); check if checksum-before-country is intentional.

### `test_membership_application_workflow.py` — 1 failure + 1 error

| Test | Issue |
|---|---|
| `test_approval_idempotency` | `LinkValidationError: Could not find Membership Type: Annual Membership` — missing fixture |
| `test_member_workflow_integration` | Expected `Approved`, got `Pending` — workflow state assertion |

Bucket A for the fixture issue. Workflow state needs investigation — could be timing (commit not propagated) or a real regression.

## Tier-based deferred work from prior PRs

### From PR #96 (G3) — 8 `enhanced_membership_application` files left untouched

These files import a mix of migrated (`validate_contribution_amount`) + deleted (`get_membership_types_for_application`, `submit_enhanced_application`) functions:

- `test_membership_dues_enhanced_features.py`
- `test_membership_dues_security_validation.py`
- `test_membership_dues_stress_testing.py`
- `test_membership_dues_system.py`
- `test_enhanced_membership_portal.py`
- `test_membership_application_workflow.py` (already partially handled in #96 — 1 method skipped)
- `test_enhanced_membership_lifecycle.py` (already partially handled in #96 — 3 methods skipped)
- `run_membership_dues_tests.py`

**Triage approach per file:** load module → list test methods → for each method using a deleted function, classify Bucket B (skip/delete) vs Bucket C (rewrite against `templates/pages/membership_application.validate_contribution_amount`). Key data point: **`validate_contribution_amount` at its new canonical location currently has zero passing test coverage** — any test that exercised it in the dues family is a candidate for migration.

### Production bug surfaced but NOT fixed (P1)

`services/member/approval/application_helpers.py:260-264` and `templates/pages/apply_for_membership.py:85` both import `get_membership_types_with_contributions` as a module-level function from `templates/pages/membership_application` — but it's now only `MembershipApplicationService.get_membership_types_with_contributions` (instance method). The helpers.py path catches the `ImportError` in a bare `except` → silent degradation. The apply_for_membership.py path has NO except → hard `ImportError` on the `/apply_for_membership` web page.

**Action:** separate production fix PR (not test triage). Suggested fix in PR #96 description.

## Group C surgical follow-ups (still open)

From the PR #93 scope notes:
- `test_volunteer_portal_security.py::test_expense_access_control_by_volunteer` — direct `frappe.get_doc("Volunteer Expense", ...)` insert
- `test_volunteer_portal_edge_cases.py::tearDown` — `frappe.get_all("Volunteer Expense", ...)` makes entire class error
- ~17 dead methods in kept `test_erpnext_expense_integration.py`
- 1 dead method in kept `test_erpnext_expense_integration_real.py`
- 4 remaining callers of the now-`NotImplementedError`-raising `create_test_volunteer_expense` helper

## Group G4 still pending (separate from this triage)

Frappe API drift + missing fixtures + archived DocType orphans:
- `frappe.cache` (renamed/moved)
- `frappe.sessions.validate_csrf_token` (Frappe API removed)
- Missing `verenigingen/tests/fixtures/email_template.json`
- Drop orphan tabDocType rows for "Verenigingen Volunteer" + "Volunteer Team" (PR #84 pattern)

## Process notes

1. **Run-tests-first** before claiming any fix works — see `feedback_check_error_log_when_running_tests`. Bench-execute or `bench run-tests --module X` against a working site is mandatory.
2. **Local bench BOM Secondary Item orphan** blocks `bench run-tests` from loading test_records. Workaround: load test classes via `unittest.TestLoader` + `TextTestRunner` from a temp helper. See PR #96 verification approach.
3. **Double-review every PR** — senior + skeptical in parallel per `feedback_always_request_pr_review`. Per-PR-#94/95/96, the review-driven scope corrections were material.
4. **Don't ship "fixes" you can't run** — the 4 MAJOR-PR pattern in #94/#95/#96 came from static-analysis-only commits. Run-tests-first kills the MAJOR rate.

## Suggested sequencing

1. Run a fresh CI on develop post-PR-#96 to get the new failure baseline number
2. Pick one cluster from the "concrete starting points" above
3. Triage per the rubric, fix in scope, verify via bench-run
4. Open PR with the pass/skip/fail counts in the description as evidence
5. Repeat until the post-Bucket-A+B baseline is reached
6. Generate the Bucket C coverage-gap list as input to a "needs new test" planning doc
