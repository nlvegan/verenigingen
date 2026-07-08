# False-Confidence Remediation — Tracker

Branch: refactor/test-false-confidence-remediation · Gate: Codecov delta (no regression)
Legend: ⬜ pending · 🟨 in wave · ✅ done
"Added" column format: `<offset> (+<unhappy gap-fill>)` — offset adds and bounded unhappy gap-fill (§2.5) counted separately.

| # | Module | Status | Flagged | Deleted | Rewritten | Added | Coverage Δ | Commit | Backlog refs |
|---|--------|--------|--------:|--------:|----------:|------:|:----------:|--------|--------------|
| 1 | SEPA | ✅ | ~24 | 1 file + 15 methods | 8 | 0 (+2) | ≥0 (dels zero-cov) | 0ba7be09 | dead-code ×2, missing ×11 |
| 2 | Payments (mollie/ing/ponto) | ✅ | ~10 | 4 files | 10 | 0 (+0) | ≥0 (dels zero-cov) | bc9bff01 | dead-code ×1, missing ×1 |
| 3 | Billing/dues/fee | ✅ | ~11 | 10 files | 1 | 0 (+1) | ≥0 (dels zero-cov) | 60efc52e | — |
| 4 | Member-financial & history | ⬜ | | | | | | | |
| 5 | e_boekhouden | ⬜ | | | | | | | |
| 6 | Membership/termination | ⬜ | | | | | | | |
| 7 | Chapter/volunteer/donation/donor | ⬜ | | | | | | | |
| 8 | Report/api/portal | ⬜ | | | | | | | |
| 9 | Utils/infra/security | ⬜ | | | | | | | |
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
