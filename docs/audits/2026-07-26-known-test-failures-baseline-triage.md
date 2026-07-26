# known_test_failures.txt baseline triage — 2026-07-26

Re-ran all 17 modules that contribute an entry to
`verenigingen/tests/known_test_failures.txt` and root-caused every failure, to
separate "legitimately ignore" from "real issue we baselined and forgot".

**Environment:** single local run, `bench --site test_site_1 run-tests --app
verenigingen --module <m>` (one module per invocation — `--module A --module B`
only runs B). Stack: frappe v16.19.0 / erpnext v16.20.0 / Python 3.14.0.
Raw logs: `scratchpad/baseline_triage/*.log` (session-local, not committed).

**Caveat:** one local run, not the CI shard matrix. Order-dependent /
shard-interaction failures may differ. Confirm the "now passing" set against a
green develop CI run before pruning entries, per the file's own header.

## Result at a glance

| Verdict | Count |
|---|---|
| Now passing → stale baseline entry | 13 |
| Real production bug | 3 |
| Real, lower severity | 2 |
| Test-side defect (dark coverage) | 11 |
| Structurally cannot pass as written | 3 |
| **Baselined total** | **32** |

The header's claim that the residual cluster is "HTTP/auth-integration tests that
cannot authenticate in CI, external-dependency skips, and a few timing/flaky perf
tests" is inaccurate for most of what remains.

## 1. Stale entries — 13 tests now pass

The gate is blind to these. Six modules ran fully green.

| Module | Baselined tests now passing |
|---|---|
| `tests.payment.test_mollie_dues_payment_processor` | `test_creates_pe_allocated_to_invoice`, `test_idempotent_returns_existing_pe` |
| `tests.integration.test_team_background_jobs` | `test_background_job_parameter_acceptance`, `test_member_addition_to_existing_team_full_workflow` |
| `tests.backend.integration.test_erpnext_expense_integration_real` | `test_cost_center_resolution_real_database`, `test_organization_cost_center_real_database` |
| `tests.sepa.test_sepa_mandate_service_integration` | `test_complete_mandate_creation_workflow` |
| `tests.payment.test_payment_system_functionality` | `test_basic_payment_history_addition` |
| `tests.payment.test_payment_history_race_condition` | `test_bulk_processing_extended_timeout` |
| `tests.payment.test_event_driven_payment_history` | `test_migration_helper_function` |
| `tests.backend.components.test_chapter_assignment_comprehensive` | `test_chapter_transfer_with_financial_implications` |
| `tests.backend.components.test_volunteer_api` | `test_api_error_handling` |
| `tests.member.test_member_lifecycle_workflows` | `test_dutch_name_handling_with_tussenvoegsel` |

## 2. Real production bug — `frappe.db.begin()` ImplicitCommitError (3 tests)

`test_create_subscription_without_iban_provisions_no_mandate`,
`test_create_subscription_with_iban_provisions_mandate`,
`test_create_member_subscription_routes_through_gateway`.

**Root cause (confirmed, not inferred).**
`CompletePaymentService._create_owner_subscription`
(`verenigingen_payments/mollie/services/complete_payment_service.py:258`) opens
its FOR UPDATE lock with `frappe.db.begin()`. Frappe refuses `START TRANSACTION`
once `transaction_writes > 0`:

```
frappe.exceptions.ImplicitCommitError: ('This statement can cause implicit commit', 'START TRANSACTION')
  frappe/database/database.py:489 check_implicit_commit
```

`MollieGateway.create_subscription`
(`verenigingen_payments/utils/payment_gateways.py:608`) catches it and returns
the generic `"Subscription creation failed. Please try again or contact
support."`, so the real cause never surfaces to caller or log reader.

**Verified two ways:**
1. Direct probe — one `frappe.db.set_value(...)` then `frappe.db.begin()` raises
   (`transaction_writes` 0 → 1 → raise).
2. Instrumented the swallowed exception inside the failing test; the traceback
   above is verbatim from that run.

**Impact:** any request that has already written anything before reaching
subscription creation fails 100% of the time, silently. Same bug class as the
2026-07-26 cleanup-engine `begin()` failure (`@critical_api` writes an audit row
before the function body, so the live path failed from the UI while dry runs
looked healthy).

**Blast radius — other non-test `frappe.db.begin()` call sites (~15):**

```
services/billing/invoice_management.py:812
services/infrastructure/production_readiness.py:202
services/member/account/account_creation_api.py:662
services/payment/pain002_ingestion_service.py:352
api/sepa_phantom_hash_admin.py:353, :394
patches/v2_0/migrate_team_role_integration.py:62
verenigingen_payments/api/sepa_reconciliation.py:528
verenigingen_payments/mollie/services/payment_service.py:345
verenigingen_payments/mollie/services/complete_payment_service.py:258, :736
verenigingen_payments/utils/payment_gateways.py:1868
verenigingen_payments/utils/sepa_race_condition_manager.py:479
verenigingen/doctype/api_audit_log/api_audit_log.py:208
verenigingen/doctype/membership_dues_schedule/membership_dues_schedule_hooks.py:234
```

Several nearby files already carry "do NOT call `frappe.db.begin()` here"
comments — the trap is known and was fixed case-by-case rather than swept.

### 2a. Call-site audit (2026-07-26)

**Savepoints are the WRONG conversion for most of these.** Releasing a savepoint
does not free row locks — only COMMIT/ROLLBACK does. Every one of these sites
uses `begin()` to bracket a `SELECT … FOR UPDATE`, where the explicit `commit()`
on an early return is what releases the lock. Converting to
`frappe.db.savepoint()` would silently hold row locks until request end.

The correct fix — and the one this repo already applied three times — is to
**delete `frappe.db.begin()` and keep the `FOR UPDATE` + explicit
`commit()`/`rollback()`**. The lock is taken inside the ambient request
transaction and released by the same commit as before. Prior art:
`api/sepa_phantom_hash_admin.py:118` and `:225`,
`api/schedule_maintenance.py:165`,
`verenigingen_payments/mollie/api/payment_webhook.py:912`.
(`base_role_profile_manager.py:449` uses a real savepoint, but that code wants
nested rollback, not lock release — different problem, don't copy it here.)

**Measured decorator behaviour** (probe on test_site_1): `@critical_api` and
`@high_security_api` write their audit row **after** the function body, not
before — `transaction_writes` is 0 inside the body and 1 after it returns. So a
*first* decorated call in a fresh request is safe; the poison comes from the
endpoint's own writes, or from a second decorated call in the same request.
`frappe.log_error()` also counts as a write (0 → 1). Independently,
`frappe.db.sql("TRUNCATE …")` trips the same guard when writes are pending.

| Site | Verdict |
|---|---|
| `mollie/services/complete_payment_service.py:258` `_create_owner_subscription` | **BROKEN — confirmed & fixed.** Deleting `begin()` turns the module from `FAILED (failures=3)` to `Ran 48 tests … OK` |
| `api/sepa_phantom_hash_admin.py:353` + `:394` `retry_phantom_attachment` | **BROKEN, 100% — fixed 2026-07-26.** `attach_file_to_document()` inserts a File doc immediately before `begin()`, so the guard always fires; the error handler then rolls that File insert back, leaving the entry stranded at `[RETRY_IN_PROGRESS]` — still blocking re-upload. Same file's other two functions were already fixed; this one was missed. Fix: drop both `begin()` calls, and `rollback()` first in the error handler so the failure is recorded against clean state. New regression test `TestPhantomHashRetry` in `tests/services/payment/test_sepa_upload_integration.py` (endpoint previously had **zero** coverage) |
| `doctype/api_audit_log/api_audit_log.py:208` `clear_all_audit_logs` | **BROKEN, 100% — fixed 2026-07-26.** A deliberate `frappe.log_error()` audit record is written immediately before `begin()`. Second landmine in the same function: raw `TRUNCATE TABLE` trips the guard independently. Fix: `commit()` the forensic record first, drop `begin()`, switch to `frappe.db.sql_ddl()`, and drop the misleading "rolled back" handler (TRUNCATE is DDL — it cannot be rolled back). New tests `TestClearAllAuditLogs` in `doctype/api_audit_log/test_api_audit_log.py`. Note the endpoint's own `@critical_api` audit row lands *after* the truncate, so the table is legitimately non-empty afterwards |
| `mollie/services/complete_payment_service.py:736` `_resolve_customer_by_email` | **Not broken, but FIXED anyway 2026-07-26** — annotating a whole-call-chain invariant that nothing enforces is what failed for `sepa_reconciliation`, and leaving one function in this file with `begin()` and its sibling without was the real inconsistency. Was: loaded but unarmed. Measured directly: with a clean transaction it sails past `begin()`; with a single pending write it raises `ImplicitCommitError`. Both live callers happen to arrive clean — the public-donation path (`public_donation_service.py:623`) runs `_save_donation_as_system_user`, which ends in `frappe.db.commit()` (measured: `transaction_writes == 0` on exit and after the settings reads that follow), and `unified_payment_api.create_subscription:207` is a standalone endpoint whose decorator writes its audit row *after* the body. One write anywhere upstream arms it |
| `mollie/services/payment_service.py:345` `_create_or_get_mollie_customer` | **NOT broken — corrected 2026-07-26.** No production caller at all: its only caller is `create_recurring_first_payment`, which a full-repo grep shows is referenced solely by `mollie/tests/test_api_integration.py` (and a 2026-06-18 dead-code handoff that listed it as "live", which is now stale) |
| `services/payment/pain002_ingestion_service.py:352` `update_batch_status` | Conditional — depends on caller; not verified |
| `verenigingen_payments/api/sepa_reconciliation.py:528` | **BROKEN, 100% — found and fixed 2026-07-26 while triaging the gate inventory.** The "PHASE 1 read-only / PHASE 2 begin" structure is sound *within* the function, but the live caller `process_sepa_transaction_conservative` first calls `acquire_processing_lock()` (`@high_security_api`) and `check_batch_processing_status()` (`@critical_api`), each of which writes an audit row when it returns. Measured: `transaction_writes` 0 → 1 after the first helper, then `begin()` raises. SEPA batch reconciliation against a bank transaction could never complete. Fix: drop `begin()`, keep the `FOR UPDATE` + existing commit/rollback. Both reconciliation suites re-run clean (`test_sepa_reconciliation` 48 OK; the one error in `test_sepa_bank_reconciliation_coverage` is **pre-existing** — reproduced with the change stashed) |
| `services/billing/invoice_management.py:812` | Conditional. `@development_only_api`; no writes in the function before `begin()` |
| `utils/sepa_race_condition_manager.py:479` | Conditional, plus `SET TRANSACTION ISOLATION LEVEL SERIALIZABLE` immediately before `begin()` is itself transaction-control and may trip the guard |
| `utils/payment_gateways.py:1868` `_process_subscription_payment` | Probably safe — carries a reasoned comment that its sole caller (the Mollie webhook) only reads first. Comment also correctly warns against savepoint conversion |
| `doctype/membership_dues_schedule/membership_dues_schedule_hooks.py:234` | Probably safe — scheduled-job entry point, fresh transaction |
| `services/member/account/account_creation_api.py:662` | **Safe.** Runs in a worker thread that calls `frappe.connect()` itself, so `transaction_writes` is 0 |
| `patches/v2_0/migrate_team_role_integration.py:62` | **Safe — annotated `patch-context`.** Correction: patches DO run inside a transaction. The guarantee is that frappe's `execute_patch()` (`patch_handler.py:179`) calls `frappe.db.commit()` immediately before invoking a patch, and this patch's `execute()` only reads before reaching `begin()` |
| `services/infrastructure/production_readiness.py:202` `_validate_database_access` | Self-inflicted false negative — the health check's "test transaction capabilities" step is `begin(); rollback()`, so it reports the database unhealthy whenever called after a write |

### 2b. Standing gate (2026-07-26)

`scripts/validation/db_begin_validator.py` + 19 unit tests in
`scripts/validation/tests/test_db_begin_validator.py`, wired as the **advisory**
pre-push hook `db-begin-validator`.

It flags two things in production Python (test modules and archived trees are out
of scope):

1. any `<x>.db.begin()` — `frappe.db.begin()`, `frappe.local.db.begin()`;
2. `<x>.db.sql("<stmt> …")` with a literal first argument where `<stmt>` is any of
   Frappe's `IMPLICIT_COMMIT_QUERY_TYPES` — TRUNCATE / ALTER / DROP / CREATE /
   START / BEGIN. (Initially only TRUNCATE; widened after review pointed out that
   `CREATE TABLE`/`ALTER` trip the identical guard, with 5 live instances in
   `sepa_notification_manager.py` and `sepa_rollback_manager.py`.) Runtime-built
   SQL and aliased handles (`db = frappe.db`) are deliberately not guessed at.

The suppression scan is scoped to the flagged **call node** and reads only real
COMMENT tokens (via `tokenize`). Both matter: a statement-wide raw-source scan let
a marker written for one call silence a different call in the same statement, and
honoured a marker that merely appeared inside a string literal.

Design note: the gate flags *every* call site rather than trying to infer
danger. Three of the four bugs found today were invisible locally — the poisoning
write came from a **caller** (`complete_payment_service.py:258`) or from a helper
(`sepa_phantom_hash_admin.py:353`). A narrower rule that only looked for a write
earlier in the same function would have caught 1 of 3. Since caller-cleanliness
is not statically provable, the honest gate makes each site an explicit, annotated
decision: `# db-begin-ok: own-connection|patch-context|verified-clean-caller|false-positive`.
An unrecognised reason is itself reported.

Advisory (exit 0) while the inventory is triaged; `--strict` / `DB_BEGIN_STRICT=1`
makes it blocking. The hook sets `verbose: true` — pre-commit hides stdout for
passing hooks, and an advisory hook always "passes", so findings would otherwise
be invisible.

**Inventory after this round: 12 findings**, 3 suppressed
(`python scripts/validation/db_begin_validator.py --all verenigingen`). The four
TRUNCATE sites are fixed and the five `CREATE TABLE` sites the widened rule found
took their place. It first reported 16, which cross-checked the manual audit
exactly (15 `begin()` sites minus 3 fixed, plus 4 raw TRUNCATEs the manual audit
had missed):

| Raw TRUNCATE site | Notes |
|---|---|
| `utils/version_cleanup.py:56` `clear_all_versions` | Reads only before the truncate, so it was clean — **hardened to `sql_ddl()`** |
| `utils/version_cleanup.py:314` + `:319` `nuclear_truncate_version_and_deleted_tables` | Double landmine: `begin()` at `:310` guarded two raw TRUNCATEs. **Fixed**: `begin()` dropped, both truncates on `sql_ddl()`, and the "TRANSACTION ROLLED BACK" handler removed — DDL commits implicitly, so that rollback never provided the atomicity it advertised |
| `utils/deleted_document_cleanup.py:144` `clear_all_deleted_documents` | **BROKEN, 100% — found 2026-07-26 while triaging this inventory, and fixed.** See below |

### 2c. Fifth broken endpoint: `clear_all_deleted_documents`

`utils/deleted_document_cleanup.py` calls `get_deleted_document_statistics()` at
`:132`, which is `@high_security_api` and so writes an API Audit Log row when it
returns; the very next statement was a raw TRUNCATE. Measured:
`transaction_writes` 0 → 1 → `ImplicitCommitError`. I had classified this site as
"conditional, clean today" without checking the decorator on the helper above it
— the same mistake made once already on `sepa_reconciliation`.

Writing the regression test surfaced a **second, independent** defect in the same
function: the `@high_security_api` decorator serialises the helper's
`OperationResult` to a plain dict, but the caller read `stats_before_result.success`
by attribute — `'dict' object has no attribute 'success'`, swallowed by the outer
`except` into a generic "Failed to clear deleted documents". Both fixed; tests in
`tests/backend/unit/utils/test_truncating_cleanup_endpoints.py` (5 tests, all four
truncating endpoints, each failing first against the unfixed code).

### 2d. Sixth broken endpoint: `create_sepa_batch_with_race_protection`

Found while triaging the gate's remaining inventory.
`sepa_race_condition_manager.py` `_execute_batch_creation_with_isolation` opened
with:

```python
frappe.db.sql("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
frappe.db.begin()
```

`SET TRANSACTION ISOLATION LEVEL` is only legal with no transaction open — and
one is **always** open, because `frappe.db.commit()` is `COMMIT` followed by
`begin()` (`frappe/database/database.py`). The distributed-lock acquisition
immediately before this call commits, and so leaves a fresh transaction running.
Measured: MariaDB `(1568, "Transaction characteristics can't be changed while a
transaction is in progress")` on every call; `@handle_api_error` on the public
endpoint turned it into a generic failure.

This is a *different* failure from the ImplicitCommitError class. The validator
flagged the `begin()` on the next line and investigating that surfaced it —
`SET TRANSACTION …` is not in `IMPLICIT_COMMIT_QUERY_TYPES`, so the gate cannot
catch it directly.

The test suite had characterised it as a harness limitation, in the same shape as
the skipped reconciliation test: `test_isolation_level_blocks_full_flow_in_txn`
asserted the 1568 and explained it away — *"(In production this runs at request
start with no open transaction, so the statement is valid.)"* That is false.

**Two further defects behind it, both masked until now:**

1. `_create_batch_document()` calls `insert()` before any `invoices` child rows
   are appended — they are only added afterwards by `_link_invoices_to_batch` —
   so Direct Debit Batch validation rejects it with "No invoices added to batch".
2. It calls `batch_doc.add_comment(...)` *before* `insert()`, against a document
   with no name.

Taken together, **this endpoint had never worked**. **Repaired 2026-07-26** —
each defect was only visible once the one above it was gone, so the repair
uncovered two more:

3. `batch_doc.description = ...` — Direct Debit Batch has no `description` field
   (the mandatory one is `batch_description`), so the assignment was silently
   dropped and the insert failed its mandatory check. `currency` was never set
   either, and is likewise mandatory.
4. The child rows omitted `member` and `membership`, both mandatory on
   Direct Debit Batch Invoice.

The repair: row population moved inside `_create_batch_document` before
`insert()`, `add_comment()` after it, the redundant `_link_invoices_to_batch`
step dropped from the flow (calling it as well would have doubled every row) and
the helper split into an append-only `_append_invoice_rows` plus a saving wrapper
kept for callers that add rows to an existing batch. `batch_description` and
`currency` set correctly; `member`/`membership` taken from the caller's
`invoice_list` entry with a fallback to the locked Sales Invoice row, and
`si.member` added to that lock SELECT so the fallback can work.

`test_full_batch_creation_flow_creates_the_batch` now drives the whole path
against real fixtures and asserts the batch exists with exactly one invoice row —
the row count matters, since a leftover link step would double it.

## 3. Real, lower severity (2 tests)

- **`test_age_validation`** (`tests.backend.components.test_membership_application`).
  Product rejects under-16s: `Member must be at least 16 years old (current age:
  10.0)`. The test wrongly asserts a 10-year-old is accepted "with an age
  warning" — the test is stale. **But** `validate_birth_date` in
  `utils/validation/application_validators.py:91` accepts any age >= 0, so the
  pre-submit validator returns green and submission then fails. Genuine UX
  inconsistency between the two validators.
- **`test_bulk_mandate_processing_performance`** (`tests.sepa.test_sepa_mandate_integration`).
  `assertQueryCount(400)` sees 441. Trace shows per-mandate
  `Member SEPA Mandate Link` lookups. Either an N+1 crept in or the budget is
  stale — cheap to determine, worth doing rather than re-baselining.

## 4. Test-side defects — dark coverage worth restoring (11 tests)

- **8 × `tests.backend.components.test_volunteer_api`** — single root cause.
  `TestDataFactory.create_test_user` (`tests/utils/test_utils.py`) grants bare
  roles, but `AuthorizationPolicy` (`utils/security/authorization_policy.py`)
  grants HIGH/CRITICAL **only** via an assigned Role Profile (Rule 4;
  `PROFILE_ONLY_LEVELS`). Denial: `profiles: none, roles: Verenigingen
  Administrator, All, Guest, Desk User`. The PR #165 fix
  (`tests/fixtures/role_profile_helper.grant_matching_role_profiles`) was never
  applied to this factory. Failing: `test_add_activity_api`,
  `..._with_all_fields`, `test_api_data_integrity`, `test_concurrent_api_calls`,
  `test_end_activity_api`, `test_end_activity_api_validation`,
  `test_get_aggregated_assignments_api`, `test_get_volunteer_history_api`.
  **FIXED 2026-07-26** — `grant_matching_role_profiles(...)` added to the test's
  `setUp` (not to the shared factory: `EnhancedTestDataFactory.create_test_user`
  deliberately withholds profiles so denial-semantics tests keep working, and
  `tests/utils/test_utils.TestDataFactory` has exactly one consumer anyway).
  `Ran 12 tests … FAILED (errors=8)` → `Ran 12 tests … OK`, verified twice.

  **Reusable hazard uncovered here.** `verenigingen.utils.error_handling.PermissionError`
  has MRO `PermissionError → VerenigingenException → frappe ValidationError →
  frappe PermissionError`, i.e. it **is** a `frappe.ValidationError` subclass
  (verified: `issubclass(...) is True`; against `DoesNotExistError` it is False).
  So any `assertRaises(frappe.ValidationError)` in the suite silently swallows an
  authorization denial and passes for the wrong reason. Two tests in this class
  were doing exactly that — `test_add_activity_api_validation_errors` and
  `test_api_error_handling` (the latter also matched its `"required" in
  str(exception)` assertion against the denial text *"Access denied. Required:
  high…"*). Both now pass genuinely, confirmed by printing the real exception
  types under the fixed user. Worth a sweep for the same pattern elsewhere.

  Left alone, flagged: in `test_end_activity_api_validation` the block commented
  "Test missing activity_name" asserts `frappe.ValidationError` for
  `end_activity(activity_name="")`, but production has no empty-string check —
  `VolunteerActivityService.end_activity` (`services/volunteer/activity_service.py:143`)
  passes straight to `frappe.get_doc(...)` and raises `DoesNotExistError`. The
  assertion passes legitimately (subclass) but proves "not found", not
  "missing argument" — a near-duplicate of the block after it.
- **`test_security_manager_dashboard_integration`** (`tests.payment.test_mollie_edge_cases_integration`)
  — mocks `settings.get_password`; the implementation
  (`core/security/mollie_security_manager.py:69`) calls
  `settings.get_webhook_secret()`. The Mock reaches `hmac.new()` as a key →
  `TypeError: key: expected bytes or bytearray, but got 'Mock'`. Product code is
  fine; it has a proper missing-secret guard.
- **`test_seeder_self_heals_stale_settings_company`** (`tests.backend.integration.test_chapter_cost_center_seeding`)
  — the *negative precondition* ("resolver must return None with a stale company
  + many companies") depends on `Global Defaults.default_company` being unset.
  Here it resolves `_Test Company`. The behaviour under test is fine; the setup
  assumption is environment-coupled.
- **`test_member_application_to_active_transition_complete_workflow`** (`tests.member.test_member_lifecycle_workflows`)
  — asserts the factory creates members in `Approved`; it creates `Pending`.
  Factory/test drift.

## 5. Structurally cannot pass as written — delete or rewrite (3 tests)

All three spawn real threads while the parent test holds an open transaction.

- **`test_concurrent_database_access`** (`tests.backend.performance.test_performance_edge_cases`)
  — worker threads `frappe.connect()` on their own connections and cannot see
  the uncommitted fixture rows; every op fails `Member … not found`. Result: 0
  reads, 0 writes, 13 exceptions.
- **`test_concurrent_member_creation`** (same module) — all 5 threads hit
  `(1205, 'Lock wait timeout exceeded; try restarting transaction')` contending
  on the naming-series row the parent transaction holds. Burns ~50s per run and
  proves nothing. 0/50 members created.
- **`test_race_condition_protection`** (`tests.financial.test_mollie_financial_safeguards`)
  — **not fully resolved.** All 3 workers see `Sales Invoice ACC-SINV-… has
  already been fully paid` *before* any concurrency happens, so the race is never
  exercised (0 successful, 3 errors). Either fixture bleed (this test commits its
  fixtures, so residue accumulates on the shared site) or a genuine gap where the
  already-paid path errors instead of returning `duplicate` (the test counts
  `duplicate` as success). Needs its own investigation.

## Reproducing

```bash
# one module per invocation — `--module A --module B` silently runs only B
bench --site test_site_1 run-tests --app verenigingen --module <dotted.module>
```

To capture an exception a service swallows into a generic error, patch
`log_error` from a standalone script rather than `bench console` — IPython
executes each line as its own cell, so closures and function bodies break:

```bash
cd ~/frappe-bench/sites && ../env/bin/python <script.py>   # frappe.init(site=...)+connect()
```
