# False-Confidence Remediation — Tracker

Branch: refactor/test-false-confidence-remediation · Gate: Codecov delta (no regression)
Legend: ⬜ pending · 🟨 in wave · ✅ done
"Added" column format: `<offset> (+<unhappy gap-fill>)` — offset adds and bounded unhappy gap-fill (§2.5) counted separately.

| # | Module | Status | Flagged | Deleted | Rewritten | Added | Coverage Δ | Commit | Backlog refs |
|---|--------|--------|--------:|--------:|----------:|------:|:----------:|--------|--------------|
| 1 | SEPA | ✅ | ~24 | 1 file + 15 methods | 8 | 0 (+2) | ≥0 (dels zero-cov) | 0ba7be09 | dead-code ×2, missing ×11 |
| 2 | Payments (mollie/ing/ponto) | ✅ | ~10 | 4 files | 10 | 0 (+0) | ≥0 (dels zero-cov) | bc9bff01 | dead-code ×1, missing ×1 |
| 3 | Billing/dues/fee | ✅ | ~11 | 10 files | 1 | 0 (+1) | ≥0 (dels zero-cov) | 60efc52e | — |
| 4 | Member-financial & history | ✅ | ~25 | 1 file + 13 methods | 19 | 0 (+1) | ≥0 (dels cov-elsewhere) | 95a114ef | dead-code ×1, missing ×1 |
| 5 | e_boekhouden | ✅ | ~12 | 1 method (+2 keep-note) | 7 | 0 (+0) | ≥0 | 12f9c3e7 | dead-code ×1 |
| 6 | Membership/termination | ✅ | ~21 | 1 file (8 methods) + 6 methods | 7 | 0 (+1) | ≥0 (dels asserted-nothing) | ba1bebd6 | dead-code ×1, missing ×1 |
| 7 | Chapter/volunteer/donation/donor | ✅ | ~25 | 16 methods | 9 | 0 (+1) | ≥0 (dels dead) | 553b136a | dead-code ×1 |
| 8 | Report/api/portal | ✅ | ~9 | 1 method | 7 | 0 (+1) | ≥0 (del dead-stub) | 2b8ad114 | dead-code ×1 |
| 9 | Utils/infra/security | ✅ | ~31 | 1 file (17) + 2 methods | 17 | 0 (+0) | ≥0 (dels dead/removed-API) | 0c714ace | missing ×2 |
| 10 | Co-located doctype + mijnrood_sync | ⬜ | | | | | | | |

## Wave log
- **Wave 1 (2026-07-08) — SEPA / Payments / Billing — ✅ DONE.** 3 agents (distinct test sites 1/2/3),
  then a skeptical-code-reviewer pass (all 3 APPROVED, 0 Critical/Important). Net: **15 test files
  deleted + 24 tautological methods removed, 11 rewritten to assert real behavior, 3 new UNHAPPY
  gap-fill tests** (invalid compliance_status, member-with-mandate deletion, negative-dues-rate), all
  mutation-verified. Test-files-only; zero prod files modified. Commits `0ba7be09`/`bc9bff01`/`60efc52e`
  on the accumulating branch.
  - Controller cleanup before commit: `ruff --fix`/`black` (25 unused imports), fixed a hardcoded
    `set_user("Administrator")` bypass and extracted upload-log seeding into a `_create_upload_log`
    factory helper (test-quality-enforcer compliance).
  - **Real prod bugs surfaced (backlogged, NOT fixed — test-files-only):** (1) `PaymentContextResolver`
    queries a non-existent `Member.payment_id` column → strategy-4 fallback unreachable; (2)
    `sepa_batch_processor.add_invoices_to_batch_optimized` calls `frappe.log_error` with swapped
    title/message args. See `backlog-dead-code.md`.
  - Skeptical-review Minor notes carried to final whole-branch review: resolver tests pin `None` from
    the masked bug (fragile coupling); `test_mandate_cleanup_on_member_deletion` is a characterization
    test pinning a known defect (labelled + backlogged); one api_regression assertion is env-gated on a
    bare site; one sepa_health test mildly re-derives its expected value.
  - **Process fix for next waves:** add "run `pre-commit run --files <your files>` and fix violations"
    to the agent contract — Wave-1 agents ran bench tests but not the pre-commit test-quality hooks,
    causing controller-side cleanup at commit time.
- **Wave 2 (2026-07-08) — Member-financial / e_boekhouden / Membership-termination — ✅ DONE.** 3 agents
  (test sites 2/3/4, one fell back to 5), then a skeptical-code-reviewer pass (all 3 APPROVED, 0
  Critical/Important). Net: **3 test files deleted + ~27 tautological methods removed, 33 rewritten to
  call REAL production code (validators, status-service, PaymentProcessor) instead of in-test
  reimplementations, 2 new UNHAPPY gap-fill tests**, all mutation-verified. Test-files-only; zero prod
  files modified. Commits `95a114ef`/`12f9c3e7`/`ba1bebd6`.
  - Controller cleanup: `ruff --fix`/`black` again removed unused imports the agents left (esp.
    e_boekhouden test_transaction_type_classification) — the pre-commit-in-contract fix helped but did
    not fully prevent it; keep verifying at commit time.
  - Skeptical Minor notes → final review: a loose `assertIn("permission")` message check;
    `test_party_resolver` pre-existing config-shape tests (left as-is); `test_membership_status_transitions`
    may guard `validate_status_transition`, which has no production caller (backlogged as dead-code).
  - New backlog items: e_boekhouden `validate_status_transition` unwired; member fee-override 0-is-no-op
    quirk (docstring contradicts behavior); membership_type `default_for_new_members` enforced JS-only.
- **Wave 3 (2026-07-08) — Chapter-donor-volunteer / Report-api-portal / Utils-infra-security — ✅ DONE.**
  3 agents (sites 2/3/4), then a skeptical-code-reviewer pass (all 3 APPROVED, 0 Critical/Important).
  Net: **~19 test methods + 1 file deleted, 33 rewritten, 2 new UNHAPPY**, all mutation-verified.
  Test-files-only; zero prod files modified. Commits `553b136a`/`2b8ad114`/`0c714ace`.
  - Highlight: the security agent **strengthened** 6 previously-`@unittest.skip`'d penetration tests into
    real boundary assertions (webhook HMAC tamper/replay/forgery → SecurityException, token-bucket deny,
    @high_security_api gating) — reviewer confirmed no genuine pen-test was weakened.
  - Known-bug tripwire added: `security_monitoring_dashboard` filters key off `process_type` values that
    are not valid SEPA-Audit-Log Select options → can never match (documented, pins current behavior).
  - Two dead stubs flagged: `is_membership_related` (return-True, zero callers; byte-identical dup in
    verenigingen_payments) and the archived Volunteer-Expense permission flow (doctype+fns removed).
  - Process note: Module 8 agent returned early (waited on a background test) but its report + edits were
    complete and verified; controller confirmed. ruff/enforcer re-verified clean at commit for all 3.
  - Skeptical Minor notes → final review: member_test_utilities can't detect member-scoping regressions;
    two permission tests coupled to factory email-suffix behavior; donor `_enhanced`/`_enhanced_fixed`
    confirmed NOT duplicates (kept).
