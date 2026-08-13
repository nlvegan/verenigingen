# Handoff 2026-08-13 — build the instrument first, then believe nothing

Two PRs merged, three open, five issues filed. The session began with #309's least
glamorous item — a logger nobody could read — and everything after it is a consequence of
that logger starting to work.

**The through-line: every defect found here was already happening, in the open, unlogged.
And every test written to prove a fix passed for the wrong reason at least once.** Both
halves matter. The first is why the instrument was worth building; the second is why a
green suite is not evidence that it works.

---

## 1. What merged

| PR | | Merge |
|---|---|---|
| #310 | previous handoff | `044b84fa` |
| #311 | the harness gets a logger whose output exists | `f9b12e35` |

## 2. What is open

| PR | | State |
|---|---|---|
| #315 | settings restore + `VereningingenTestCase` owns the settings company | one shard red — **blocked on #318** |
| #317 | email capture: retarget one patch, delete two, fail loudly | green bar the CI flake (#319) |
| #318 | SEPA reconciliation cleans up the rows it commits | green locally; CI shards red on #319 |

Suggested order: **#318 → rebase #315 → #317**. #315's remaining red shard is the bug #318
fixes, not its own.

## 3. Issues filed

| | |
|---|---|
| #312 | three harness defects #311 made visible (settings restore, two dead email patches) — being fixed by #315/#317 |
| #313 | the pre-push hook runs the suite against the **live** site, and dies from a worktree |
| #314 | `tests/utils/__init__` swallows the failure of the one thing it exists to do |
| #316 | ~146 test files still borrow the settings company from whatever ran first |
| #319 | CI shards fail **before running any tests** when the wkhtmltopdf download is throttled |

---

## 4. The logger, and what it immediately found

Every bare `frappe.logger()` in the setup harness discarded `.warning()`, `.info()` and
`.debug()`. `get_logger` sets the level to `frappe.log_level or default_log_level`
(`frappe/utils/logger.py:80`), and `default_log_level` is `WARNING if frappe._dev_server
else ERROR` (`:12`). `DEV_SERVER` is unset under `bench run-tests`, and `frappe.log_level`
is assigned **only** by `bench console` (`frappe/commands/utils.py:640`). Measured:

    frappe._dev_server: 0    frappe.log_level: None
    effective level: 40 ERROR    isEnabledFor(WARNING): False

#291 called this "a log file, not stdout". It is worse: **no record at all**. 61 call
sites across `enhanced_test_factory.py`, `tests/setup/__init__.py` and
`tests/utils/__init__.py` now use `verenigingen/tests/harness_logger.py`, which differs in
the two ways that matter — an explicit level, and a **stderr** handler, because
`frappe.logger()` sets `propagate = False` and writes only to files CI does not surface.

Within one test run it exposed, all firing on **every** `EnhancedTestCase` test:

- `tearDown` calling `self.factory._restore_verenigingen_settings()` when the method is on
  `EnhancedTestCase` — so the **committed** repointing of `Verenigingen Settings.company`
  was never undone. Committed global state surviving the rollback: the pollution class
  #291/#308 exist to fight, inside the harness.
- Two patches against `frappe.utils.email_lib`, a module that no longer exists, and one
  against a removed `email_queue.send_one`. `captured_emails == []` meant "nothing was
  watching".
- `Captured-insert drain: N record(s) could not be deleted`, **32 times in one module** —
  the thread that led to #318.

**Rule:** a handler that "logs and continues" is worth exactly as much as its logger.
Verify the logger emits before arguing about the handler.

---

## 5. The chain that started when the leak stopped

Fixing the settings restore turned five CI tests red across three shards. They were not
regressions; they were **latent order-dependent tests that the leak had been feeding**.

Much production code resolves "which company" from the `Verenigingen Settings` single
rather than from its arguments — `sepa_config_manager.get_company_sepa_config()`
(`:98-105`), `chapter_finance_service`, `invoice_generator`, `department_sync_service`,
`user_role_profile_calculator`, ~15 more. `EnhancedTestCase` sets that single;
`VereningingenTestCase` never did. Its tests passed only when an Enhanced test ran earlier
**in the same shard** and left the value behind.

Proven pre-existing: on develop, unmodified, with only the site's value pointed elsewhere,
`test_enhanced_sepa_processing`, `test_multi_chapter_membership` and
`test_invoice_generation_and_payment_history_sync` all fail.

The fix went into the base class rather than the five modules CI named, because **the
borrower set is not enumerable from a CI log** — which tests break depends on shard
composition. #316 carries the ~146 files neither harness reaches.

### Then shard 3, which was somebody else's bug

`test_sepa_reconciliation` leaves **submitted** Payment Entries; a later test's Bank
Transaction is then linked to one, and its `bt.cancel()` fails with `LinkExistsError`.
Reproducible on develop with none of this session's changes. The harness cannot clean them
because `_drain_captured_inserts` **deletes without cancelling** — which is what those 32
warnings were saying.

This branch's only role was **adding a test file**, which re-packs every LPT bin and put
polluter and victim in the same shard. That is #291's thesis, reproduced by accident.

---

## 6. Measured facts worth keeping

- **`frappe.logger()` at `.error()` DOES emit** under `bench run-tests` (40 ≥ 40) — into
  `logs/frappe.log`, never stdout. Only `.warning()`/`.info()`/`.debug()` vanish. Do not
  flatten "reached a file nobody reads" into "was never written": check the level of the
  specific call.
- **`Company.default_bank_account` is a Link to `Account`**, not to `Bank Account`. Reading
  it and then testing `exists("Bank Account", ...)` is a branch that can never be true.
- **`Accounts Settings.delete_linked_ledger_entries` is 0 by default**, so
  `delete_doc(force=True)` on a submitted Payment Entry leaves orphan `GL Entry` /
  `Payment Ledger Entry` rows naming a document that no longer exists.
- **`doc.cancel()` enqueues** (this app registers a payment-history handler on
  `Payment Entry.on_cancel`), and frappe refuses to enqueue past a queue-length guard. A
  dev bench with a backed-up queue silently defeats any cancel-based cleanup:
  `Too many queued background jobs (1550)`. `bench purge-jobs` fixes it. This cost three
  verification runs that looked like the fix failing.
- **`unittest` reports cleanup errors IN ADDITION to the test result.** "A cleanup that
  raises would mask the test's own result" is false, and it was the stated justification
  for a swallow.
- **Nothing re-links an existing Payment Entry to a later Bank Transaction** — every writer
  of `custom_bank_transaction` sets it at creation. The likely mechanism behind "orphan PE
  points at a new BT" is **naming-series reuse**: `tabSeries` increments are transactional,
  so a rolled-back test frees `ACC-BTN-...NN` for a later row.
- **The compat `FrappeTestCase` has no per-test rollback** — only
  `addClassCleanup(_rollback_db)` (`frappe/deprecation_dumpster.py:617-632`). A per-test
  `frappe.db.commit()` in a base class therefore makes every untracked row durable.
- **`test-quality-enforcer` matches factory helpers by name** (`_grant_`, `_make_`,
  `_insert_`, `_as_`, with the trailing underscore). `ignore_permissions=True` outside one
  is rejected — including in `tests/support/`.
- **`bench run-tests --module A --module B` runs only B.** To reproduce a shard's ordering,
  drive `unittest` directly with an explicit module list.

## 7. Traps that cost time here

- **A commit rejected by a pre-commit hook still lets the following `git push` run**, which
  creates the remote branch at the *base* commit with none of the work. `tail` on the push
  output looks like success. Verify with `git log` and compare local vs remote heads.
- **`gh run rerun <id> --failed` fails with "its workflow file may be broken"** while the
  run still has jobs in progress. Wait for completion.
- **A cleanup probe that counts successful deletions reports "0 cleared" when it deleted
  nothing because everything failed.** Mine did, and I read it as "site is clean" for
  several runs. Count what remains, not what succeeded.
- **A solo test run proves nothing about an order-dependent failure** (#308 says this; it
  is still easy to forget). Both branch and develop passed the victim solo while the pair
  failed on both.

---

## 8. On the tests written here

Worth stating plainly, because it recurred in every single PR:

| PR | the test that passed for the wrong reason |
|---|---|
| #311 | asserted the resolved level against `DEFAULT_LEVEL`, the *fallback* — so the suite went **red** under the env var its own docstring told you to set |
| #315 | picked a sentinel company that was already the harness's own, making the assertion a no-op that passed either way |
| #317 | asserted on an error string **the test itself raised**, so reverting the production behaviour still passed |
| #318 | asserted "the account belongs to my company", which a borrow satisfies by luck — and did |

In each case the *first repair of the test* still did not catch the mutant. What found them
was running the mutation and watching the suite stay green. Manual verification —
"I ran it and counted the orphans" — found none of them.

**If a test is the evidence for a claim, mutate the claim and watch it fail. Otherwise the
evidence is that the test runs, not that it constrains anything.**

## 9. Open threads

- **#309's main list is untouched.** The logger prerequisite is done; the 12 swallowed
  setup handlers (8 of which should raise) are still there. Highest-value single one
  remains line ~3606, the root `Department "All Departments"`.
- **#308 has four of five borrow sites left.** #318 closes the SEPA reconciliation one.
- **#316** is the largest: ~146 files inheriting a frappe base class directly, still
  borrowing. Also records that `_harness_company()` lacks the chart-of-accounts guarantee
  `_get_test_company()` carries.
- **#313 is an operator hazard, not just tidiness** — until it is fixed, every `git push`
  from the installed checkout runs the suite against **veg11**. Push with
  `SKIP=pytest-coverage-critical`.
- `Member.user` uniqueness is **cleared for production** (operator-confirmed 2026-08-12);
  the #310 handoff's warning about `test_site_1` blocking migrate is **stale** — that site
  is clean and the index is built.
