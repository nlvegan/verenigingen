# Handoff — ImplicitCommitError bug class: 6 broken endpoints + standing gate

**Branch:** `fix/implicit-commit-guard-db-begin` (6 commits, **not pushed**, no PR yet)
**Base:** `develop` @ `d264ba2a`
**Date:** 2026-07-26
**Audit doc:** `docs/audits/2026-07-26-known-test-failures-baseline-triage.md` — read
this first; it has the per-site evidence and the full baseline triage.

```
878445ea fix(sepa): repair race-protected batch creation; add idempotent-bootstrap reason
946af195 docs(audit): record the sixth broken endpoint and the two defects behind it
262b1e99 fix(sepa): remove the SET-ISOLATION/begin() that broke race-protected batching
023aa153 fix(cleanup): guard NULL aggregates in the version/deleted-document cleanups
de05e6f2 fix(transactions): 5th broken endpoint + address skeptical review
6efd604d fix(transactions): repair 4 endpoints broken by frappe.db.begin()
```

⚠️ The working tree also contains ~28 **unrelated** modified/untracked files from
concurrent work (`verenigingen/mijnrood_sync/*`, `utils/service_logger.py`,
`patches.txt`, a new `patches/v2_2/` patch, a mijnrood handoff doc). None of them are
part of this branch and none were touched. **Do not `git add -A`** here.

---

## 1. Where this came from

The ask was "check the tests that have been baselined for issues we should address
rather than ignore" — i.e. triage `verenigingen/tests/known_test_failures.txt`. Three of
the baselined Mollie tests turned out to be flagging a live production bug, and pulling
that thread produced everything below.

**The original task is only half done.** See §6.

---

## 2. The bug class

`frappe.db.begin()` emits `START TRANSACTION`. Frappe refuses it — and every other
statement in `IMPLICIT_COMMIT_QUERY_TYPES` — once the current transaction has pending
writes:

```python
# frappe/database/database.py
IMPLICIT_COMMIT_QUERY_TYPES = frozenset(("start", "alter", "drop", "create", "begin", "truncate"))
...
if query_type in IMPLICIT_COMMIT_QUERY_TYPES and self.transaction_writes:
    raise ImplicitCommitError("This statement can cause implicit commit", query)
```

Measured facts (probes on `test_site_1`, all reproducible):

| Fact | Value |
|---|---|
| Any `set_value` / `insert` / File attach | `transaction_writes` 0 → 1 |
| `frappe.log_error()` | 0 → 1 — **it is a write** |
| `@critical_api` / `@high_security_api` | audit row written **AFTER** the body: 0 inside, 1 after it returns |
| `frappe.db.commit()` | `COMMIT` **followed by `begin()`** — a transaction is always open afterwards |
| Raw `frappe.db.sql("TRUNCATE …")` | trips the same guard independently of `begin()` |

**Why it cannot be reasoned about locally:** whether writes are pending depends on the
CALLER. A site is safe only while every caller happens to arrive clean, and one upstream
`save()` — or one preceding decorated helper — arms it. Three of the six bugs had the
poisoning write in a caller, not in the function.

**Why it stayed hidden:** every one of these call sites is wrapped by something that
swallows the exception into a generic "operation failed" response. Nothing reaches a log
reader.

### The fix is almost never a savepoint

These sites bracket a `SELECT … FOR UPDATE`, and the explicit `commit()` on an early
return is what RELEASES the row lock. **Releasing a savepoint does not free row locks** —
converting would silently hold them until request end. The correct fix, now applied
across the repo, is: **delete `begin()`, keep the `FOR UPDATE` and the existing
`commit()`/`rollback()`**. The lock is taken in the ambient request transaction and
released by the same commit as before.

(`services/infrastructure/base_service.py:242` correctly *does* use a savepoint — it has
no row lock. Different problem; don't copy this fix there.)

---

## 3. What was broken and fixed

All six verified by a failing test or a direct measurement **before** the fix.

| # | Endpoint | Failure |
|---|---|---|
| 1 | `CompletePaymentService._create_owner_subscription` | Any caller that saved a document first got "Subscription creation failed. Please try again or contact support." Module went 3 failures → 48 OK |
| 2 | `retry_phantom_attachment` (SEPA phantom-hash admin) | `attach_file_to_document()` inserts a File right before `begin()`, so it fired every time; the handler then rolled that File back, stranding the entry at `[RETRY_IN_PROGRESS]` — still blocking re-upload, the exact thing the tool exists to clear. **Zero test coverage** beforehand |
| 3 | `clear_all_audit_logs` | The deliberate forensic `frappe.log_error()` immediately above is a pending write. Raw TRUNCATE trips the guard independently, so it also moved to `sql_ddl()`; the "rolled back" handler was dropped (DDL cannot be rolled back) |
| 4 | `reconcile_full_sepa_batch` | The live caller calls `acquire_processing_lock()` (`@high_security_api`) then `check_batch_processing_status()` (`@critical_api`), each writing an audit row on return. SEPA batch reconciliation against a bank transaction could never complete |
| 5 | `clear_all_deleted_documents` | `get_deleted_document_statistics()` is `@high_security_api` → audit row pending → raw TRUNCATE raises. **Plus** a second defect: the decorator serialises the helper's `OperationResult` to a dict, but the caller read `.success` by attribute |
| 6 | `create_sepa_batch_with_race_protection` | **Four stacked defects — had never worked.** See below |

### #6 in detail

1. Opened with `SET TRANSACTION ISOLATION LEVEL SERIALIZABLE` → MariaDB **1568**
   *"Transaction characteristics can't be changed while a transaction is in progress"*.
   Legal only with no transaction open, and one is always open (see the `commit()` fact
   above). Not the ImplicitCommitError class at all — the validator flagged the `begin()`
   on the next line and investigating that surfaced it.
2. `_create_batch_document()` called `insert()` before appending any `invoices` child
   rows → "No invoices added to batch".
3. `batch_doc.description = …` — no such field. The mandatory one is `batch_description`,
   so it was silently dropped. `currency` was never set either, also mandatory.
4. Child rows omitted `member` and `membership`, both mandatory.

Repaired: rows populated before `insert()`, `add_comment()` after it, redundant
`_link_invoices_to_batch` step dropped from the flow (calling it too would double every
row), helper split into `_append_invoice_rows` + a saving wrapper.

⚠️ The row fallback needed a second pass after review. The lock SELECT read
`si.membership_dues_schedule_display AS membership` — a Link to *Membership Dues
Schedule* aliased over the real `si.membership` column — so the fallback fed a
dues-schedule name into a `Link → Membership` field and failed inside `insert()`. The
alias is now `dues_schedule`, `si.member` and the real `si.membership` are both selected,
and a missing value now raises an error naming the invoice and the field instead of a
bare `MandatoryError`. No deeper resolution is attempted: deriving a Membership from a
dues schedule is the canonical batch builder's job (`api/sepa_batch_ui.py:472-493`) and
duplicating it here would put that logic in a third place.

### Also fixed

`clear_all_versions` raised `TypeError` on a second consecutive call — `SUM()` over an
empty table returns NULL. Surfaced by the new tests, not by review, and only on a
*second* run because the first truncates the table.

---

## 4. The standing gate

`scripts/validation/db_begin_validator.py` + 26 unit tests, wired as the **advisory**
pre-push hook `db-begin-validator`.

Flags, in production Python only (test modules and archived trees excluded):

1. any `<x>.db.begin()`;
2. `<x>.db.sql("<stmt> …")` with a **literal** first arg where `<stmt>` is any of
   `IMPLICIT_COMMIT_QUERY_TYPES`.

**It flags every call site rather than inferring danger.** A narrower "is there a write
earlier in this function" rule was tried and would have caught **1 of 3** of the original
bugs. Since caller-cleanliness is not statically provable, each site is made an explicit
annotated decision.

```python
frappe.db.begin()  # db-begin-ok: own-connection
```

| Reason | Means |
|---|---|
| `own-connection` | Runs on its own fresh connection (thread/job that called `frappe.connect()`), so writes are 0 by construction |
| `patch-context` | Runs under a patch. NB the guarantee is that `execute_patch()` commits immediately before invoking it (`frappe/modules/patch_handler.py:179`) — patches DO run inside a transaction |
| `verified-clean-caller` | EVERY caller provably arrives clean. Name them; this claim rots the moment a caller adds a `save()` |
| `idempotent-bootstrap` | An idempotent `CREATE TABLE IF NOT EXISTS` whose failure is caught and logged, changes no data, and is completed by a later clean call |
| `false-positive` | Analyzer is wrong — please report it too |

An unrecognised reason is itself reported. Advisory (exit 0); `--strict` /
`DB_BEGIN_STRICT=1` makes it blocking.

```bash
python scripts/validation/db_begin_validator.py --all verenigingen   # inventory
python scripts/validation/tests/test_db_begin_validator.py           # 26 unit tests
```

**Inventory: 16 → 5 findings, 8 suppressed.**

---

## 5. Things to know before touching this

- **`bench --site X run-tests --module A --module B` silently runs only B.** One module
  per invocation.
- Test on `test_site_1`, never `veg11`.
- To capture an exception a service swallows, patch `log_error` from a standalone script
  — `bench console` is IPython and executes each line as its own cell, so closures and
  function bodies break:
  `cd ~/frappe-bench/sites && ../env/bin/python probe.py` with `frappe.init(site=…)` +
  `frappe.connect()`.
- **`verenigingen.utils.error_handling.PermissionError` subclasses
  `frappe.ValidationError`** (MRO: `→ VerenigingenException → ValidationError →
  PermissionError`). Any `assertRaises(frappe.ValidationError)` silently swallows an
  authorization denial. Two tests in `test_volunteer_api` were passing for that wrong
  reason; a third matched `"required"` against the denial text *"Access denied. Required:
  high…"*. **Worth a repo-wide sweep — this was not done.**
- `AuthorizationPolicy` grants HIGH/CRITICAL **only** via an assigned Role Profile
  (Rule 4). A bare role caps at MEDIUM. Test users need
  `grant_matching_role_profiles(...)`, not just `add_roles`.
- pre-commit's `black` formats `frappe.db.sql("""…""")` blocks differently from a local
  `black` run, which **moves `# db-begin-ok:` markers**. Suppression still holds (the
  marker lands inside the call node's span) but re-verify after a hook reformat — one
  commit attempt failed on exactly this.
- Two of the tests here TRUNCATE shared tables (`tabAPI Audit Log`, `tabVersion`,
  `tabDeleted Document`). That is the behaviour under test. Both modules say so in their
  docstrings; **not parallel-safe**.

### The recurring trap: tests that encode a production bug as a harness quirk

Twice, a test documented one of these bugs as a limitation of the test environment:

- `test_full_reconciliation_creates_payment_entries` — `@unittest.skip("…the
  FrappeTestCase transaction wrapper rejects with 'This statement can cause implicit
  commit'")`. It was the production bug. Un-skipped; passes.
- `test_isolation_level_blocks_full_flow_in_txn` — asserted the 1568 and explained it
  away: *"(In production this runs at request start with no open transaction, so the
  statement is valid.)"* It does not. Replaced.

When a test says "this can't be exercised in the harness", check whether production
actually differs.

---

## 6. Outstanding

**The original task, still open.** `known_test_failures.txt` has **13 stale entries** —
tests that now pass, so the gate is blind to them. Listed in §1 of the audit doc. Confirm
against a green develop CI run before pruning, per the file's own header. Also still open
from that triage: 11 test-side defects, 2 lower-severity product issues (a validator
inconsistency that lets the client-side pre-check green-light an under-16 applicant; a
441-vs-400 query-count breach), and 3 threading tests that cannot pass as written.

**5 validator findings left**, needed before the gate can go `--strict`:

| Site | Suggested |
|---|---|
| `production_readiness.py:202` | Its "test transaction capabilities" step *is* `begin(); rollback()`, so the health check reports the DB unhealthy after any write. The one place a **savepoint** is genuinely right — no row lock |
| `payment_service.py:345` `_create_or_get_mollie_customer` | No production caller (only `create_recurring_first_payment`, referenced solely by a test). Delete rather than annotate? |
| `membership_dues_schedule_hooks.py:234` `run_bulk_sync_with_transaction` | Same — unwired wrapper |
| `pain002_ingestion_service.py:352` | **Untraced.** Verdict unknown |
| `invoice_management.py:812` | **Untraced.** Verdict unknown |

Given six broken endpoints came out of what began as a test-baseline triage, assume the
two untraced ones deserve a real trace rather than an annotation.

**Gate blind spot worth recording:** `verenigingen_payments/utils/shared/db_helpers.py`
`ensure_table_exists()` runs `frappe.db.sql(create_sql)` with a **variable**, so the
validator cannot see it (literal SQL only). It is worse than the five annotated inline
sites: on error it calls `frappe.db.rollback()` — discarding the caller's pending writes
— and then swallows. Its production caller is `SEPADistributedLock._ensure_lock_table`,
reached from `SEPABatchRaceConditionManager.__init__`, i.e. from three whitelisted
endpoints.

**Validator false positive worth fixing properly:**
`scripts/validation/security/permission_bypass_validator.py` matches
`ignore_permissions\s*=\s*True` on any line and skips only lines starting with `#`, so
**docstring prose** describing a bypass is flagged as if it were code. That is why
`member_cleanup_service.py` failed CI on two `Security:` docstring bullets. Worked around
here by dropping the `=True` from the prose (the justification lookup only needs the bare
`ignore_permissions` token). The real fix is to make the scanner docstring-aware.

**Shard risk:** the two TRUNCATE-ing test modules are documented as not parallel-safe but
nothing enforces it, and `run-parallel-tests` shards share one database. TRUNCATE takes an
exclusive metadata lock that can block another shard. Consider gating them on an env var.

**Not done:** the `assertRaises(frappe.ValidationError)` sweep (see §5);
`_link_invoices_to_batch` is now dead and its stated justification is weak — appending
rows to a *saved* batch under-counts `entry_count`/`total_amount`, because
`DirectDebitBatch.calculate_totals()` switches to SQL aggregation for a non-new doc and
`validate()` runs before the child rows are written. Delete it or fix that path. Pushing
the branch / opening a PR.
