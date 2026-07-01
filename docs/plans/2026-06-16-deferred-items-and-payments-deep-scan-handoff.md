# Handoff — Deferred Test-Meaningfulness Items + Payments/Mollie/Ponto Deep Scan (2026-06-16)

Follow-on to `2026-06-15-test-meaningfulness-remediation-handoff.md`. This session
closed out the 5 deferred items from that handoff and then ran the deep test-assertion
read across the money-path chunks (payments/ponto/mollie/utils/api), acting on the findings.

## Result: 10 commits, PUSHED to `origin/develop` (`a759ec7e..5c0d43c4`)

```
96859f82 fix(eboekhouden): clean item names in tegenrekening mapper (f-string bug)   [item 2 + scratch delete]
d9111fe7 chore(eboekhouden): remove dead is_enhanced_processing_enabled method        [item 3]
e1b20934 test(eboekhouden): harden range-overlap test; auditor recognizes self.fail   [item 1]
7f398e4c fix(eboekhouden): add Stock Reconciliation eboekhouden_mutation_nr field      [item 4]
4af9c3ab fix(dd-batch): persist approval_status in approve_batch/reject_batch          [scan finding]
c7660351 chore(payments): remove leftover debug logging from bulk_transaction_importer [scan finding]
5671b1a4 test(mollie): run webhook-wrapper & dues-processor suites without a Mollie key [scan finding]
12e1ecb7 test(dd-batch): replace vacuous scheduler-notification tests with real guards  [scan finding]
c648534e fix(roles): use the real 'Verenigingen Financial Manager' role, not 'Finance Manager' [scan finding, Foppe-approved]
5c0d43c4 test(sepa): document that rollback compensation executors are stubs           [scan finding, Foppe-approved]
```
(`6a0df274 chore: remove dead performance subsystem and orphaned validators` is a CONCURRENT
session's commit, also on develop — not ours.) All touched modules verified green individually on
veg11; all commits passed pre-commit + pre-push.

### Branch-divergence resolution (the bit that nearly went wrong)
My commits were landing on a feature branch `chore/remove-dead-perf-and-validators` (created by the
concurrent agent in the shared working tree), while local `develop` quietly diverged and was MISSING
my last 4 commits (mollie un-skip, scheduler tests, role rename, rollback relabel). The two
"remove dead performance subsystem" commits on the two branches were **patch-identical** (same
patch-id `354395b5…`). Resolved by **cherry-picking the 4 missing commits onto `develop`** (zero file
overlap with the dead-perf removal → no duplicate, clean), then pushing `develop` and deleting the
now-redundant feature branch. The last 4 commits were re-hashed by the cherry-pick (hashes above are
the final pushed ones). **Lesson: in a shared working tree with a concurrent agent, verify
`git rev-parse --abbrev-ref HEAD` before assuming you're on `develop`.**

## Deferred items 1–5 (from the prior handoff) — all done
1. **Auditor MOCK_ONLY=17 triage** — almost all legitimate: `progress_utils` ×14 is a void
   persistence shim (the db_set/commit calls ARE the only observable behaviour); the rest are
   real mock-contract / `self.fail()` / singleton tests. Real finds: deleted scratch script
   `test_intelligent_item_creation.py` (a `__main__` print script, not tests); strengthened the
   vacuous `test_check_range_overlaps_logs_warning` (now Error-Log-count asserted). Taught the
   auditor that `self.fail()/failUnless/failIf` count as assertions (killed 2 false positives).
2. **f-string bug** in `smart_tegenrekening_mapper._generate_item_name` — was LIVE (fallback path
   in `create_invoice_line_for_tegenrekening`, used by the REST migration), not dead. Fixed +
   flipped the bug-documenting test.
3. **Dead `is_enhanced_processing_enabled`** — removed (zero callers).
4. **Stock Reconciliation `eboekhouden_mutation_nr` field** (Foppe: add it) — added to
   `fixtures/custom_field.json` (read-only/unique/system-generated, mirrors Journal Entry),
   migrated veg11 (column now exists). Added `test_mutation_nr_persists_and_enables_duplicate_detection`.
   Was the only one of 5 import doctypes missing it; the processor set it, the coordinator required
   it, and `base_processor.check_duplicate` queried it — so the stash was silently dropped and stock
   re-imports could duplicate.
5. **Deep money-path scan** (Foppe: full pass) — below.

## The deep scan (item 5 + Foppe's "also mollie/utils/api")
5 parallel `skeptical-code-reviewer` agents read ~68 sweep-added test files (SEPA, payment
gateways/MT940/bank/DD-batch, Ponto, Mollie, utils/api/components) against the production code.
**Headline: unlike eBoekhouden, NO test was masking a hidden bug — the suites are genuinely strong.**
Actioned findings:

- **`approve_batch`/`reject_batch` never persisted `approval_status`** (`dd_batch_workflow_controller.py`)
  — computed/returned `next_state` but only wrote `approval_notes`. Latent (endpoints registered in
  `critical_operation_rule.json` but unwired). Fixed + strengthened the 2 tests to assert the persisted field. `4af9c3ab`
- **`bulk_transaction_importer`** wrote a `log_error("DEBUG: ...")` Error Log on every import + six
  `logger().error("🔍 ...")` lines — removed. `c7660351`
- **Two Mollie `_unit.py` suites silently skipped their entire high-value regression guards**
  (reversal/idempotency/503; duplicate-Bank-Transaction) on credential-less CI. Un-gated: webhook
  wrapper constructs credential-free; dues processor patches `MollieClient` during `__init__`. `5671b1a4`
- **The "Finance Manager" role bug** (Foppe: rename) — the string was hard-coded in ~20 places but
  that Role doesn't exist; the app's role is **"Verenigingen Financial Manager"**. Renamed 29 prod
  refs across 8 modules + the COR fixture + a test. Skeptical-reviewed (APPROVE-WITH-NITS). `c648534e`
- **SEPA rollback compensation executors are stubs** (Foppe: document+relabel) — `_create_credit_note`
  etc. only flip the tracking row to "completed" without booking anything. Relabeled the tests +
  added a "no real return SI produced" assertion. `5c0d43c4`

## Open / flagged for a future session
- **Role rename caveats (from the skeptical review):**
  - The `critical_operation_rule.json` edit is **documentary only**: CORs are insert-only (not synced
    fixtures), so the 7 live veg11 rows still say "Finance Manager". AND that `required_roles` field is
    not consumed for access decisions (parsed comma-split but stored newline-separated; gating is via
    the `@critical_api`/`@require_sepa_permission` decorators). If live COR rows must change, write a
    one-off `bench execute` patch — but functionally it changes nothing.
  - The two DD-batch workflow-setup files (`dd_batch_workflow_setup.py`, `simple_dd_workflow_setup.py`)
    are **not wired into install/migrate** (no caller but `__main__`/a whitelist wrapper); the related
    membership workflow is commented out as "DISABLED... has bugs". The rename there is latent-correct.
  - **Recommended follow-up:** add `Roles.FINANCIAL_MANAGER = "Verenigingen Financial Manager"` in
    `utils/constants.py` and use it everywhere (now ~10 hardcoded literals) to prevent the next
    typo-driven silent-deny.
- **SEPA rollback executors** — implementing real Credit Note / Payment-reversal / invoice-cancel /
  Journal-Entry booking is tracked feature work (Foppe chose document-only for now).
- **Remaining low-value weak tests** (prod code is CORRECT; tests merely under-assert — not bug-masking):
  - `verenigingen_payments/api/test_dd_batch_optimizer.py::test_validate_all_pending_invoices_shape`
    — highest-priority of these: seeds nothing, only checks result keys, and the endpoint swallows SQL
    errors into `validation_errors`, so a future `si.member`/`mds.status` 1054 would pass silently.
    Fix: seed a terminated-member unpaid invoice, assert it's detected with `validation_errors == []`.
  - `tests/backend/components/test_setup_init.py::test_check_termination_system_status` /
    `test_verify_app_dependencies` — `assertIsInstance(result, dict)`-only.
  - `tests/payment/test_balances_client.py::test_error_handling` and several SEPA `assertRaises(Exception)`
    that DO follow with a message assertion (mostly fine).
  - Stale "PRODUCT BUG / xfailed" docstrings in `test_sepa_rulebook_validator.py`,
    `test_sepa_reconciliation.py`, `test_sepa_batch_ui_secure.py`, `test_bank_transaction_reconciliation.py`
    — describe already-fixed bugs as live; bodies are correct, only the headers mislead.

## Env gotchas worth remembering
- **pre-commit stash/abort:** committing a file that black/ruff then reformats leaves an unstaged diff;
  the next commit's stash conflicts and ABORTS silently (a trailing `&& echo DONE` lies). The role
  rename hit this (longer string → over line-length → black wraps). Fix: `git add` the reformatted
  files and re-commit; always verify `git log` moved, don't trust the echo.
- **`frappe.get_list("Has Role", ...)` in a test** did not return a freshly-seeded role-user (the
  reason the DD-batch notification "fires" test was abandoned for a robust empty-audience guard).
- **"Finance Manager" is ALSO a Chapter Role** (board position) in
  `test_volunteer_board_finance_persona.py` — do NOT rename that; it's a different doctype/concept.
- Stock Reconciliation now has the custom field on veg11 (via migrate); CI gets it via fixture sync.
