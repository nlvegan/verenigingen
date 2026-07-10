# TODO / Unfinished-Feature Audit — 2026-07-10

Codebase-wide sweep for `TODO`/`FIXME`/`XXX`/`HACK` markers, `NotImplementedError`,
`pass`-only stubs, disabled features (`if False:` / `{% if false %}`), and
functions that report success / return placeholder data without doing the work.

**Method:** 5 parallel agents over disjoint subtrees (payments; core doctypes+reports+pages;
services+email; utils+api; e_boekhouden+mijnrood+templates+www). ~64 findings after each
grep hit was read in context and triaged (~28 LOW/boilerplate omitted here). Grouped by
**impact**, not by tree.

**Caveat:** several HIGH items sit on entry points that are *themselves currently unreachable*
(noted per item) — real code smell, lower urgency. The genuinely live issues are in
sections B and C. Each entry is `file:line — description`. Verify reachability before acting.

---

## A. User-facing features that appear available but don't work
- `verenigingen/verenigingen/doctype/periodic_donation_agreement/periodic_donation_agreement.js:347` — **"Generate PDF"** button shows "will be implemented in Phase 3".
- `verenigingen/templates/pages/donate.html:517` — entire **ANBI tax-deduction section** disabled via `{% if false %}`.
- `verenigingen/templates/pages/payment_plans.html:436` — **"Make Payment"** button → "coming soon" stub.
- `verenigingen/www/mollie_member_reconciliation.html:526` — **"Set subscription"** quick-fix button is an unimplemented stub.
- `verenigingen/templates/pages/chapter_dashboard.py:543` — **"Expense Approvals"** dashboard section wired in template; backend always returns `[]`.
- `verenigingen/services/approval/contribution_amendment_approval_service.py:384` — **"Billing Interval Change"** is a UI-selectable amendment type, but `apply_billing_change()` just `frappe.throw("...not yet implemented")` → those amendments dead-end after approval.

## B. Silent production failures (look wired, fail quietly)  ⚠ highest real impact
- `verenigingen/email/analytics_tracker.py` + caller `verenigingen/utils/email_tracking.py:63,78,122` — **email open/click tracking & engagement analytics are DEAD**: the real 615-line impl was renamed to `analytics_tracker.py.disabled` and replaced by a 39-line stub missing `track_open`/`track_click`/`get_member_engagement`/`get_email_analytics`; callers swallow the `ImportError`.
- `verenigingen/email/automated_campaigns.py:219,251` — daily `process_scheduled_campaigns` reads `campaign_type`/`content_config` off ERPNext's standard `Email Campaign` DocType, which **has neither field** → `KeyError` on every real due campaign (caught + logged). `:265` — falls back to **hardcoded fake newsletter content** (fabricated member counts, a fake volunteer "Sarah Johnson").
- `verenigingen/e_boekhouden/utils/party_resolver.py:651` — `_add_party_address` is a **no-op stub called on the live relation-import path** → eBoekhouden addresses never imported.
- `verenigingen/e_boekhouden/utils/eboekhouden_enhanced_migration.py:351` — `_run_pre_validation()` always returns `can_proceed: True` → **migration safety gate is vacuous**.

## C. Whitelisted APIs that falsely report success / return fake data
- `verenigingen/api/periodic_donation_operations.py:314` (ANBI) — `generate_tax_receipts()` builds receipt text, **discards it, never saves/emails/attaches**, reports success → compliance gap.
- `verenigingen/verenigingen_payments/dashboards/simple_dashboard.py:16` (FINANCIAL) — `get_dashboard_data()` returns **hardcoded fake Mollie balances/settlements**.
- `verenigingen/verenigingen_payments/utils/sepa_retry_manager.py:638` (FINANCIAL) — `execute_with_retry()` **fakes success** via `mock_operation()` for most op types.
- `verenigingen/verenigingen_payments/doctype/sepa_retry_batch/sepa_retry_batch.py:120` — `process_single_operation()` **simulates** retry outcomes by string-matching the error category; can mark failed SEPA ops "Success".
- `verenigingen/verenigingen/report/members_without_dues_schedule/members_without_dues_schedule.py:328` (FINANCIAL) — `fix_schedule_dates()` reports `success:True` **without fixing anything**.
- `verenigingen/utils/analytics_engine.py:1211` — `_check_audit_trail_gaps()` returns a **hardcoded score 85.0** into overall compliance scoring.
- `verenigingen/verenigingen_payments/utils/sepa_xml_enhanced_generator.py:690` — `_validate_xml_structure()` is a **`pass`-only no-op called unconditionally** in the real bank-file SEPA XML pipeline.

## D. Latent security landmine
- `verenigingen/utils/error_handling.py:594` — `require_permission()` contains `has_perm = True  # Replace with actual permission check` → **always grants**. Zero callers today (verified), but a live bypass if ever wired.

## E. SEPA batch submission / IBAN validation gaps
- `verenigingen/verenigingen_payments/doctype/direct_debit_batch/direct_debit_batch.py:302` + duplicate `verenigingen/verenigingen_payments/services/batch_processing_service.py:100` — **"submit batch to bank" is a documented no-op** in two places.
- `verenigingen/verenigingen_payments/services/sepa_configuration_service.py:128` — still uses `SEPAUtilities.validate_dutch_iban()`, documented as **incomplete/unsafe** ("may accept invalid Dutch IBANs"), instead of the canonical validator.

## F. Dead / latent stubs (cleanup candidates — mostly no callers)
- `verenigingen/verenigingen/doctype/member/mixins/financial_mixin.py:47` — `process_payment()` "not yet implemented" (SEPA & Bank Transfer); no callers.
- `verenigingen/verenigingen/doctype/membership/scheduler.py:249` — `generate_direct_debit_batch()` placeholder (hardcoded zeros, no XML); not scheduled/whitelisted.
- `verenigingen/verenigingen/doctype/membership/dues_schedule_manager.py:236` — `get_member_bank_details()` always `{}` (its `create_direct_debit_batch` entry point is itself dead).
- `verenigingen/verenigingen/doctype/performance_optimization_setup/performance_optimization_setup.py:424` — whitelisted `remove_optimizations()` no-op.
- `verenigingen/verenigingen/doctype/analytics_alert_rule/analytics_alert_rule.py:427` — "Update Field" alert action no-op.
- `verenigingen/utils/performance_utils.py:513` — dead `PerformanceCollector` (working equiv exists in `performance_dashboard.py`).
- `verenigingen/utils/error_handling.py:777` — `setup_error_monitoring()` no-op, never called (docstring claims it is).
- `verenigingen/utils/exceptions.py:159` — self-documented FIXME: `PermissionError` doesn't extend `frappe.PermissionError`; dead code.
- `verenigingen/verenigingen_payments/dashboards/financial_dashboard.py:502` — chargeback metrics hard-disabled, self-imposed removal deadline 2026-04-21.
- `verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py:540` — pending-chargeback branch empty (`TODO: implement when needed`).
- `verenigingen/e_boekhouden/utils/stock_account_handler.py:426` — `remap_to_asset` "not yet implemented".
- `verenigingen/e_boekhouden/utils/eboekhouden_ledger_mapping.py:255` — hardcoded-company/date temporary debug API left live.
- `verenigingen/email/advanced_segmentation.py:354` — `_get_custom_segment_recipients()` returns "not yet implemented"; `:187` — "engagement" segment ignores its criteria and returns all-active-members.
- `verenigingen/verenigingen/doctype/chapter/utils/ChapterValidation.js:454` — attachment-size validation placeholder (never enforced).

---

## Suggested triage order
1. **B — silent failures** (email tracking, campaigns, eBoekhouden addresses): verify each actually fires in prod, then fix or explicitly decommission. These are the most likely to be silently hurting users/data.
2. **C — fake-success APIs**, prioritising ANBI receipts and the FINANCIAL SEPA endpoints (compliance/financial correctness).
3. **A — user-facing stubs**: either build or hide the control (a visible button that says "coming soon" is worse than no button).
4. **D** — remove or wire `require_permission` before it can be misused.
5. **E/F** — opportunistic cleanup when touching those areas.
