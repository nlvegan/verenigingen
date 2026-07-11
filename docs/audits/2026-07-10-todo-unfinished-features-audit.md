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

## Verification log — 2026-07-10 (in progress)

Each item independently re-checked against current code + reachability (callers / schema / whitelist).
Verdicts: **CONFIRMED** (real, as described) · **NUANCED** (real but severity/reachability differs) · **pending** (not yet re-verified).

- **B1 (email tracking) — NUANCED.** The stub is real (real 22 KB impl sits at `analytics_tracker.py.disabled`; live stub only defines `class EmailAnalyticsTracker`, missing the module-level `track_open`/`track_click`/`get_member_engagement`/`get_email_analytics` that callers import → `ImportError`). BUT the `email_tracking.py` webhook wrappers (`process_tracking_webhook`, `get_member_engagement_stats`) have **zero callers** → dead, not "silently failing in prod". The genuinely-reachable consumers are `utils/email_campaign.py:117` (imports missing `get_email_analytics`) and `email/validation_utils.py:53` (instantiates the stub). Net: email analytics is **unbuilt**, not actively erroring on a live path. Fix = restore the `.disabled` impl, or delete the dead wrappers + stub.
- **B2 (automated campaigns) — CONFIRMED → ✅ FIXED (PR #140).** `process_scheduled_campaigns` is scheduled **daily**; `campaign_type`/`content_config` confirmed **absent** from ERPNext's `Email Campaign` DocFields → `_execute_campaign` `KeyError`ed for any due campaign. **Correction:** the fake "Sarah Johnson" content was actually **unreachable** (KeyError fired first). Root: a scaffolded-but-unbuilt "Phase 3" feature (missing custom-field schema). **Fix (graceful-degrade + FUTURE GOAL, per owner):** `_execute_campaign` now returns `{skipped: True}` instead of KeyError; scheduler routes skips out of `errors`; fabricated placeholder content removed; module docstring documents the FUTURE GOAL (build via Frappe CRM or custom fields — undecided).
- **B3 (eBoekhouden addresses) — CONFIRMED → ✅ FIXED (PR #140).** `_add_party_address` (`party_resolver.py:651`) was a no-op called on the live customer/supplier import paths → addresses dropped. **Nuance:** only the party-extractor / enrichment-queue paths; the primary `RelationMigrationService` migration already imported them. **Fix:** implemented `_add_party_address` to create a linked `Address` mirroring `RelationMigrationService._create_address`; 3 real-DB mutation-verified tests.
- **B4 (migration pre-validation) — CONFIRMED (low-harm).** `_run_pre_validation` always returns `can_proceed:True` and the caller (`:272`) relies on it → the gate is vacuous. But it validates nothing to begin with, so it's an **unimplemented safety feature**, not an active data-loss bug.
- **C1 (ANBI tax receipts) — CONFIRMED → ✅ FIXED (PR #141).** Live `@frappe.whitelist` + `@critical_api(FINANCIAL)` (`:285`). Called `generate_tax_receipt_content()` (a placeholder string), **discarded it**, only added a "receipt generated" comment, and returned "N generated" → real ANBI compliance gap (no receipt produced/saved/emailed). **Also found:** the report's "Generate Tax Receipts" button was mis-wired to a **nonexistent** `anbi_operations.generate_tax_receipts` (Method Not Found). **Fix:** per-agreement confirmation receipt is now rendered → PDF → attached to the agreement as a private File (idempotent-replace, no email, donor/org fields HTML-escaped since `render_template` doesn't autoescape and output feeds wkhtmltopdf); button repointed to the real endpoint + confirm dialog; audit comment written only after the File saves. 6 real-DB mutation tests.
- **C2 (Mollie dashboard) — CONFIRMED → ✅ FIXED / decommissioned (PR #142).** Live `@frappe.whitelist` + `@high_security_api(FINANCIAL)` (`:12`); returned hardcoded placeholder balances/settlements. **Orphaned** — the Mollie dashboard UI (`www/mollie_dashboard.html`) uses the real `FinancialDashboard` (`dashboards/financial_dashboard.py`, live Mollie clients). Deleted `simple_dashboard.py` (no callers).
- **C3 (SEPA execute_with_retry) — CONFIRMED → ✅ FIXED / decommissioned (PR #142).** Live `@frappe.whitelist` + `@critical_api(FINANCIAL)` (`:611`); faked success via `mock_operation()` for every op type except `batch_creation`. **Orphaned** — the retry handler in use is `sepa_error_handler.SEPAErrorHandler.execute_with_retry` (via `direct_debit_batch` `sepa_processor`). Removed the 3 orphaned whitelisted API funcs (`execute_with_retry`/`get_retry_statistics`/`reset_retry_circuit_breaker`), keeping the tested `SEPARetryManager` engine.
- **C4 (sepa_retry_batch.process_single_operation) — CONFIRMED (internal).** Not a direct endpoint (internal method `:161`), reachable via the batch controller; simulates retry outcomes by string-matching.
- **C5 (fix_schedule_dates) — NUANCED.** The `def` at `:327` is a **nested function** (indented inside another), not a top-level whitelisted endpoint as originally rated → lower reachability/severity; needs a closer look before actioning.
- **A6 (Billing Interval Change) — CONFIRMED, NUANCED.** It IS a real selectable `amendment_type` (`contribution_amendment_request.json:91`), and the approval service's `apply_billing_change` (`:382`) throws "not yet implemented" (dispatched at `:237`). BUT a **parallel handler exists** in `mollie_subscription_sync_service.py:510` for the same type → subscription-backed members may route through the Mollie path instead of dead-ending. Confirm which path a real approved amendment takes before fixing.
- **D (require_permission bypass) — CONFIRMED.** The always-`True` `require_permission` (singular, `error_handling.py:594`) has **zero callers** (the grep hits are `require_permissions`, plural — a different, real function). Latent landmine, as described.
- **A1, A3, A4, A5 (user-facing stubs) — CONFIRMED visible.** A1 "Generate PDF" is wired to an `add_custom_button` (`periodic_donation_agreement.js:92`→`generate_agreement_pdf`, shows "Phase 3"); A3 "Make Payment" is an `onclick` button (`payment_plans.html:343`→`showPaymentForm`, "coming soon"); A4 "Set subscription" is an `onclick` button (`mollie_member_reconciliation.html:448`→`setMemberSubscription`, "coming soon"); A5 the dashboard renders an "Expense Approvals (N)" header (`chapter_dashboard.html:236`) fed by a hardcoded `pending_expenses = []` (`chapter_dashboard.py:543`) → always 0.
- **A2 (donate ANBI section) — CONFIRMED, lower severity.** `{% if false %}` (`donate.html:517`) with a "Disabling ... for now" comment — a cleanly *hidden* section, not a broken/visible control. No user sees a dead button; the benefit copy just doesn't render.
- **E1 (submit batch to bank) — RESOLVED: intended manual-upload design, NOT a defect** (investigated 2026-07-10). Full lifecycle trace confirms the SEPA collection workflow is complete and works:
  1. `generate_sepa_xml_for_batch` (`services/sepa_xml_generation_service.py:34`) produces a **real pain.008.001.08-compliant** file via `SEPAXMLAdapter` (schema-validated; covered by `tests/test_sepa_xml_compliance.py`), saves it, and **attaches it to the batch** (`sepa_file` field, `:181`).
  2. The form exposes a **"Download SEPA File"** button (`direct_debit_batch.js:146` → `window.open(frm.doc.sepa_file)`).
  3. Admin downloads the pain.008 and **uploads it to the bank portal manually** — the standard SEPA-DD submission path.
  4. "Submit to Bank" (`process_batch`) only flips status → "Submitted" (bookkeeping); invoices are marked paid separately via later bank-transaction reconciliation, not here.
  The only unbuilt piece is **optional automated bank-API submission** — not required for the manual workflow, and its absence does not stop collections. The original HIGH rating was a false positive from reading `process_batch`'s "placeholder" comment in isolation. **No action needed** unless automated bank-API submission is a desired enhancement.
- **E2 (IBAN validator) — CONFIRMED, low blast radius.** `sepa_configuration_service.py:128` validates only the **company's own settings IBAN** via `SEPAUtilities.validate_dutch_iban` (documented as loose). Not member IBANs; one value. Swap to the canonical validator when convenient.
- **F (dead/cleanup) — spot-verified CONFIRMED.** `financial_mixin.process_payment` has **zero callers** (dead). `remove_optimizations` has no internal callers but is `@frappe.whitelist` → reachable as a no-op API. Remaining F items consistent with "dead/latent"; not individually re-verified.
- **C6 (audit_trail compliance score) — CONFIRMED → ✅ FIXED (PR #143).** `_check_audit_trail_gaps` returned a hardcoded `score: 85.0` (self-labelled "Stub"), called at `:341` and feeding `_calculate_overall_compliance_score` → a **fabricated number in the overall compliance score**. Impact = wherever that analytics compliance report is surfaced. **Fix:** `_check_audit_trail_gaps` now measures real Frappe change-tracking (`track_changes`) coverage across `AUDIT_CRITICAL_DOCTYPES` via a new `_audit_trail_coverage` helper — a queryable proxy for "changes to this record are auditable". Not-installed doctypes are skipped (score reflects only existing doctypes); untracked doctypes surface as actionable recommendations. Real-DB coverage tests added.
- **C7 (SEPA XML `_validate_xml_structure` no-op) — RESOLVED (redundant, not a hole).** The no-op (`sepa_xml_enhanced_generator.py:690`, called internally at `:220`) IS on the live generation path (`EnhancedSEPAXMLGenerator` is the real generator), BUT actual pain.008.001.08 **schema validation is performed downstream** by `SEPAXMLValidator.validate_sepa_xml_schema` in `sepa_xml_generation_service.py:98` (and the controller's `_validate_sepa_xml_schema:339`). So generated files ARE validated; `_validate_xml_structure` is a vestigial internal hook. Cleanup candidate (delegate or remove the misleading placeholder), not a validation gap. Original HIGH rating was a false positive.

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
