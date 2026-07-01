# Handoff — Error Log guard + fail-mode audit + 7 bug fixes (2026-06-20)

## TL;DR
Built an **Error Log guard** for the test suite, ran the whole suite in **fail-mode**
(`VERENIGINGEN_FAIL_ON_ERROR_LOG=1`) to surface swallowed-error bugs, triaged the
findings with parallel agents, and fixed the real ones with TDD.

**9 commits PUSHED to `origin/develop`** (`35021c96..6efbaf41`), pre-push green:

| Commit | What |
|---|---|
| `a278ac75` | (pre-existing) mt940 TRCD booking-code read |
| `e6faebff` | **Error Log guard** on both base test classes (warn default, opt-in fail) |
| `54e5009c` | Mollie bulk-payment webhook URL → real endpoint (was nonexistent module, 120 silent 404s) |
| `e626ad13` | Disciplinary termination: invalid Select `"Disciplinary"`→`"Disciplinary Action"` + phantom field + dead guard |
| `36bb501b` | Member age validation: enforce (throw-then-swallow) + remove hardcoded fallbacks (min age solely from Verenigingen Settings) |
| `f145142f` | SEPA: skip an invalid debtor IBAN instead of failing the whole batch |
| `3b299ad7` | Termination approval/execution emails: provide `member`/`doc` context so templates render |
| `7c4b03c5` | Disciplinary dialog ↔ API contract (termination_type, secondary_approver, request_id) |
| `6efbaf41` | Dues invoice due_date clamped to posting_date (retroactive billing) |

## The Error Log guard (`e6faebff`)
`verenigingen/tests/utils/error_log_guard.py` — `ErrorLogGuardMixin`, mixed into BOTH
`VereningingenTestCase` (base.py) and `EnhancedTestCase` (enhanced_test_factory.py).
- tearDown snapshots Error Logs written during the test (captured **before** rollback).
  Default = **WARN**; `VERENIGINGEN_FAIL_ON_ERROR_LOG=1` makes it **FAIL**.
- `with self.assertNoErrorLog(ignore=[...]):` fails a wrapped block regardless of the env flag.
- `self.expectErrorLog("substr")` opts a test out of the auto-check only.
- Documented in `docs/DEVELOPER_TESTING_GUIDE.md`. Replaced the old non-failing `_check_test_errors`.
- CAVEAT: `log_error(defer_insert=True)` / `frappe.flags.read_only` logs flush post-request → invisible.

## The fail-mode audit — headline
Ran the whole suite **sharded across all 6 sites** via Frappe's `run-parallel-tests
--total-builds 6 --build-number N` (1-based; veg11=shard1 needs `--lightmode`; test_site_1..5
= shards 2-6). **~1,066 / ~11k tests flip under the flag (~9.5%), but the overwhelming
majority are TEST-ARTIFACTS, not product bugs:**
1. Async-work-outlives-rolled-back-data (test enqueues a job/hook, tearDown rolls back,
   job runs against deleted record → swallowed "X not found"). Can't happen in prod.
2. No background worker in tests ("Too many queued background jobs (800)").
3. Missing external config (Mollie / SMTP / HTTP / rate-limit).
4. Dual fiscal-year env state ("Fiscal Year Auto-Creation Error" 398x).

**Conclusion: the flag is a one-time AUDIT tool, NOT a CI gate** (a gate would need ~1k
`expectErrorLog` annotations). Keep it off by default; use surgical `assertNoErrorLog()`.

## Real bugs fixed (all TDD)
All seven below were confirmed reproducible and fixed with a failing-then-passing test.

1. **Disciplinary termination dead in prod** (`e626ad13`, `7c4b03c5`). The entry point
   failed on every call (invalid Select value `"Disciplinary"`; wrote to a phantom
   `supporting_documentation` field; duplicate-guard keyed to the dead value). Then wired
   the request-form dialog to the API (arg names, chosen subtype, secondary_approver,
   `request_id`). Dropped 4 phantom field writes (disciplinary_procedure,
   investigation_required, requires_board_approval, requires_governance_review).

2. **Age validation** (`36bb501b`). `member_age_service` caught its own `frappe.throw` in a
   broad `except Exception` → under-age members saved silently. Re-raise `ValidationError`.
   Per Foppe: minimum age is sourced **solely from Verenigingen Settings**
   (`minimum_membership_age` etc.) — removed the hardcoded `min_age` fallbacks from
   `AgeValidator.CONTEXTS` and `_get_configurable_min_age` (which even *disagreed* with the
   setting defaults: student 18 vs 14, youth 16 vs 12).

3. **SEPA one-bad-IBAN-kills-whole-batch** (`f145142f`). IBANs were validated only at the
   final XML build, which raised for the entire batch. Now validated per-transaction in
   `SEPAXMLAdapter._build_transaction` so the bad row is skipped into BatchValidationSummary.

4. **Termination approval/execution emails never rendered** (`3b299ad7`). Templates reference
   `member`/`doc` objects but senders passed flattened context → jinja UndefinedError on every
   send (swallowed). Built each sender's context in a helper providing member+doc+approver_name
   +base_url+company; fixed a phantom `reason_for_termination` → `termination_reason` template ref.

5. **Dues invoice due_date before posting** (`6efbaf41`) — the 641-occurrence cluster.
   `due_date = add_days(coverage_start, 45)`; for retroactive billing coverage_start is months
   in the past → due < posting → ERPNext rejects. Fix: `max(getdate(coverage_start),
   getdate(posting_date))`.

6. Mollie bulk-payment webhook URL (`54e5009c`) — pointed at a nonexistent module.

## ⚠️ Suite-wide blind spot discovered (FOLLOW-UP WORTH DOING)
`EnhancedTestCase.setUp` sets `frappe.flags.in_import = True` (to skip user-creation
throttling). ERPNext's `validate_due_date` self-heals a past due_date to posting **only
under `in_import`** — so **the entire test suite was masking the invoice due-date bug** (and
likely masks any retroactive-billing money-path date bug). The regression test for #5 sets
`frappe.flags.in_import = False` to mirror production. **Recommendation: tests exercising
invoice submission should neutralize `in_import`.**

## Remaining flags (not fixed — by design / out of scope)
- **Test-artifact clusters to annotate** (not prod bugs): "Secure Operation Failed: insert on
  Communication" (negative-control security tests run roleless), "Chapter Manager Error"
  (logs-then-re-raises correctly), "Customer Creation Error"/"customer_handling Error"
  (duplicate test-member names colliding on Customer PK), "Dues Schedule Creation Failed"
  (intentional swallow + fixture amount mismatch). These flip under fail-mode but need
  `expectErrorLog`/unique fixtures, not code fixes.
- **Disciplinary feature, deeper**: the `termination_data` execution-time options
  (cancel_sepa_mandates, unsubscribe_newsletters, end_board_positions) collected by the dialog
  are applied at *execution*, not initiation — currently not threaded through. Initiation
  creates a Draft; submission/approval is a separate form step.

## Gotchas for the next session
- **Run ERPNext-dependent `FrappeTestCase` modules on an idle `test_site_N`, not veg11** — veg11
  hits erpnext `BootStrapTestData` DuplicateEntryError (`Price List 'Standard Buying'`),
  especially when another agent/session is running tests on veg11 concurrently.
- **Don't stack a retry on top of 6 concurrent shards** → OOM-kills a shard.
- **test-quality-enforcer CRITICAL-blocks `inv.flags.ignore_permissions = True`** in test
  helpers — drop it; EnhancedTestCase runs as Administrator.
- **`git stash` to test on a clean tree**: the `stash pop` can fail silently if the shell cwd
  resets mid-command — re-check `git stash list` and pop explicitly.
- **Export-on-save pollution**: running tests in developer mode re-exports touched Module
  Onboarding / Onboarding Step JSON to disk (timestamps + reformatting + DB-state fields). After
  a test session, `git checkout -- verenigingen/verenigingen/module_onboarding/
  verenigingen/verenigingen/onboarding_step/` to clean them. **Do NOT commit them** — the DB
  copy was missing the `Verenigingen-Configure-Security` onboarding step, so committing would
  drop it from source.
- **Editing `email_template.json` fixtures**: edit with a surgical string replace, NOT
  `json.dump` (which reformats all 1000+ lines). The change applies to running sites on the next
  `bench migrate`.

## Next codecov targets (per the audit snapshot)
Overall **62.19%**. Smallest+lowest gap = `verenigingen_payments/workflows` (645 missed, 18%).
Other big gaps: `e_boekhouden/utils` (5446, 51%), `verenigingen/doctype` (4310, 70%).
