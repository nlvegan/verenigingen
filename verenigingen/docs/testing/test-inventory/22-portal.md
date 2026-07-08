# Test Inventory — Domain 22: tests/backend/portal

**COMPLETE** — all 41 files audited. Classification of every class-level `def test_*` method into HAPPY / UNHAPPY / EDGE / OTHER.

Legend:
- **HAPPY** = nominal success / expected-valid path
- **UNHAPPY** = expects error/throw/validation-failure/permission-denial/rejection/auth-redirect-block
- **EDGE** = boundary, empty/null/zero, duplicate, concurrency, idempotency, malformed input, unauthenticated/guest access edge, ordering
- **OTHER** = smoke/import-safety/setup-only/tautological, debug-script-no-assert, mock-into-tautology, or skip-dominated

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_donation_portal_behavior.py | 5 | 3 | 2 | 0 | 0 |
| test_guest_donation_flow.py | 9 | 8 | 0 | 1 | 0 |
| test_page_address_change_coverage.py | 9 | 4 | 4 | 1 | 0 |
| test_page_brand_css.py | 4 | 3 | 0 | 1 | 0 |
| test_page_brand_management.py | 5 | 2 | 3 | 0 | 0 |
| test_page_campaign.py | 9 | 3 | 4 | 2 | 0 |
| test_page_chapter_dashboard.py | 11 | 6 | 2 | 3 | 0 |
| test_page_chapter_join.py | 10 | 2 | 4 | 4 | 0 |
| test_page_contact_request.py | 6 | 2 | 3 | 1 | 0 |
| test_page_donate.py | 13 | 7 | 3 | 3 | 0 |
| test_page_donation_dashboard.py | 3 | 1 | 1 | 1 | 0 |
| test_page_dues_schedule_admin.py | 3 | 2 | 1 | 0 | 0 |
| test_page_join_chapter.py | 9 | 2 | 4 | 3 | 0 |
| test_page_manage_donations_coverage.py | 14 | 2 | 8 | 4 | 0 |
| test_page_manage_donations.py | 13 | 7 | 4 | 2 | 0 |
| test_page_member_portal_coverage.py | 23 | 15 | 2 | 6 | 0 |
| test_page_membership_adjustment_coverage.py | 19 | 8 | 9 | 2 | 0 |
| test_page_mollie_bulk_payment_creation.py | 24 | 5 | 15 | 4 | 0 |
| test_page_mollie_payment_processing.py | 29 | 11 | 15 | 3 | 0 |
| test_page_mollie_payments_debug.py | 45 | 20 | 24 | 1 | 0 |
| test_page_mollie_subscription_recreation.py | 25 | 7 | 15 | 3 | 0 |
| test_page_payment_dashboard.py | 10 | 4 | 3 | 3 | 0 |
| test_page_payment_plans.py | 4 | 1 | 1 | 2 | 0 |
| test_page_payment_retry.py | 4 | 1 | 1 | 2 | 0 |
| test_page_payment_success.py | 21 | 7 | 9 | 5 | 0 |
| test_page_payment_success_coverage.py | 33 | 10 | 10 | 13 | 0 |
| test_page_personal_details_coverage.py | 24 | 10 | 10 | 4 | 0 |
| test_page_ponto_api_debug.py | 14 | 6 | 8 | 0 | 0 |
| test_page_ponto_pay.py | 8 | 3 | 2 | 3 | 0 |
| test_page_portal_cluster.py | 55 | 27 | 12 | 16 | 0 |
| test_page_sepa_reconciliation_dashboard.py | 5 | 2 | 3 | 0 | 0 |
| test_page_simple_controllers_coverage.py | 27 | 16 | 7 | 4 | 0 |
| test_page_team_members.py | 9 | 3 | 5 | 1 | 0 |
| test_page_volunteer_apply.py | 2 | 1 | 0 | 1 | 0 |
| test_page_volunteer_dashboard.py | 10 | 6 | 1 | 3 | 0 |
| test_page_volunteer_expense_claim_new.py | 3 | 1 | 1 | 1 | 0 |
| test_page_volunteer_expenses.py | 13 | 4 | 6 | 3 | 0 |
| test_page_volunteer_profile.py | 6 | 4 | 1 | 1 | 0 |
| test_page_volunteer_skills.py | 11 | 5 | 2 | 4 | 0 |
| test_page_workflow_demo.py | 6 | 3 | 3 | 0 | 0 |
| test_portal_functions.py | 2 | 2 | 0 | 0 | 0 |
| **DOMAIN TOTALS** | **555** | **236** | **208** | **111** | **0** |

## Observations

- **Permission/guard-heavy domain.** UNHAPPY (208, ~37%) is unusually large for a portal domain because nearly every page controller and whitelisted endpoint is tested for role/guest rejection (`frappe.PermissionError`, `SecurityPermissionError`, `frappe.ValidationError`, `frappe.Redirect` to `/login`). The Mollie admin tool pages (`mollie_payments_debug`, `mollie_payment_processing`, `mollie_bulk_payment_creation`, `mollie_subscription_recreation`) alone account for ~69 UNHAPPY methods — each read/mutation endpoint has a paired "denied for non-admin/guard" + "admin passthrough" test.
- **EDGE (111, ~20%) is dominated by portal-context edge states**, not classic numeric boundaries: "user has no Member/Volunteer record → graceful error context", guest/anonymous render short-circuits, empty-collection returns, unknown-id-handled-gracefully, and input clamping/coercion (limits clamped, invalid mode coerced, CSV-formula sanitisation). These are genuinely reachable production states, not contrived.
- **No OTHER (0).** Every method carries a real behavioural assertion. Even the mock-based Mollie passthrough tests assert argument forwarding/coercion and that the fake service was invoked with the expected args (or NOT instantiated when the decorator gate fires first) — they are not tautological. No skip-dominated or debug-no-assert methods were found (skips are conditional `skipTest` guards for site-config, with real assertions on the happy branch).
- **Classification boundary calls (documented for reproducibility):** input-validation rejections that assert an error/throw (`_is_error`, `_throws`, `_rejects`) were counted UNHAPPY even when triggered by boundary/out-of-range values; EDGE was reserved for empty/null/zero/duplicate/idempotent-no-op, guest-or-unauthenticated render, graceful "no record" fallbacks, input clamping/coercion (no error), and non-terminal payment states (pending/authorized/expired/cancelled status mappings). "Denied/False" permission-helper results were counted UNHAPPY (a rejection), while "feature-disabled short-circuit that returns an alternate view" was counted EDGE.
- **Payment-status state machines inflate EDGE**, especially `payment_success_coverage.py` (13 EDGE of 33): the Ponto/ING return handlers are exhaustively exercised across every status code (pending/authorized/cancelled/expired/refunded/unknown-fallback), most of which are non-error intermediate states → EDGE.
- **Two duplicated-name method pairs exist within `portal_cluster.py`** (`test_existing_member_short_circuits` appears in both the `apply_for_membership` and `membership_application` test classes; `test_no_member_record` appears in five different page classes). These are distinct methods on different classes (not shadowing) and all were counted individually.

## Notes on files

- No zero-method files: all 41 files contain at least 2 class-level `def test_*` methods (smallest: `test_page_volunteer_apply.py` and `test_portal_functions.py` at 2 each; largest: `test_page_portal_cluster.py` at 55).
- No missing/expected-but-absent files relative to the 41-file `find` listing.
- Method counts were taken from `grep -cE "^\s+def test_"`; nested helper functions and non-`test_`-prefixed methods (e.g. `_make_*`, `_ctx_with_team`, `setUp`/`tearDown`) were excluded from classification.
