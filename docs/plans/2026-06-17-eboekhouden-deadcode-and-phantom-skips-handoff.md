# Handoff — eBoekhouden dead-code triage + phantom-skip fixes (2026-06-17, session 2)

Follow-on to `2026-06-17-eboekhouden-rest-migration-coverage-handoff.md`. Two pieces of work this
session, both on the eBoekhouden import layer, both LOCAL/UNPUSHED on `develop`.

## State
- Branch `develop`. **My 2 commits this session: `084671fb`, `ab5854e9`** (interleaved with a concurrent
  Mollie-coverage session's commits `d4730a9f`/`400be88a`/`71ccfd4b`/`15e16001`/`a4e13f8b`).
- Working tree: only `verenigingen/public/css/email_brand.css` modified — **pre-existing, not mine**
  (it was dirty at session start; leave it).
- These join the still-unpushed eBoekhouden stack from session 1 (`c9e171e9..ee805664`). Nothing pushed.

## Commit 1 — `084671fb` dead-code triage (Foppe chose "delete all")
Deleted two fully-orphaned helper clusters from `eboekhouden_rest_full_migration.py` (verified: zero
non-test callers, no dynamic/string dispatch) + their coverage-sweep tests; 306 prod LOC, 531 net test
lines. **41 live-code tests green** afterward.
- **Cluster 1 (money-transfer, dead):** `_process_money_transfer_mutation`, `_resolve_money_source_account`,
  `_resolve_money_destination_account`, `_get_appropriate_income/expense/payment_account` (the appropriate-
  account helpers were reachable only via the two dead resolvers). Superseded by the live
  `_create_money_transfer_payment_entry`→`PaymentProcessor._process_money_transfer`.
- **Cluster 2 (generic party, dead):** `_get_or_create_generic_party`/`_generic_customer`/`_generic_supplier`.
  Superseded by `party_resolver.resolve_customer/_supplier`.
- **KEPT (verified LIVE — my first grep mis-named the wrappers):** the company-party trio
  `_get_or_create_company_party`/`_as_customer`/`_as_supplier` (called from `_classify_opening_balance_account`
  + `_assign_party_to_entry`), and the unrelated `BankTransactionParser._get_or_create_generic_party` *class
  method*. **Lesson: grep EXACT wrapper names + check `self.`/`parser.` receivers; a bare `\bname\b` grep
  conflates a module fn with a same-named class method.**
- **+1 gap test** (amended in): `_assign_party_to_entry`'s type-7 Receivable→company-as-customer branch was
  tested but the Payable→company-as-supplier mirror was not. Added
  `test_memorial_payable_uses_company_as_supplier` to `test_rest_journal_entry_creation.py`.

## Commit 2 — `ab5854e9` phantom always-skip tests (Foppe: "fix all 3")
Three tests **silently skipped on every run** (green, asserting nothing). Detect the pattern by running the
module and reading `OK (skipped=N)`; the shape is `if result is None: self.skipTest(...)` placed BEFORE the
real assertions.
- **`test_e_boekhouden_migration_integration.py` ×2** (customer + supplier payment processing): skipped
  whenever `PaymentEntryHandler.process_payment_mutation` returned None. **Root cause: setUp built a Bank-type
  GL account + ledger mapping but NOT the `Bank Account` *master* doctype** that `_determine_bank_account`→
  `resolve_bank_account_for_ledger` needs. Added the master (mirrors `_ensure_bank_account_master` in
  `tests/payment/test_payment_entry_handler.py`) + replaced each skip with a hard assertion.
  - Supplier test then failed with 0 references → **NOT a product bug**: the handler COMMITS PEs
    (`atomic_migration_operation`), so a repeating `get_next_sequence('mutation_id')` id collided with a prior
    run's committed PE → duplicate-detection early-return → 0 refs. **Fix = time-based unique ids**
    (`int(time.time()*1000) % 1e8 + offset`). The allocation path is correct; these tests now genuinely verify
    payment→invoice allocation (their unique value vs the handler unit tests, which use fake invoice strings).
- **`test_payment_entry_handler.py::test_payment_without_party`**: asserted a PE the handler never creates —
  `_get_or_create_party` returns None for a falsy relationId (party-less money = types 5/6 → JEs), so a type-3
  w/o relationId ALWAYS returns None → always skipped. Rewrote to assert the real contract (returns None, no
  PE persisted, logs "party"); renamed `test_payment_without_party_returns_none`.
- **Verified:** migration module **33/33 OK** (was skipped=2); handler module **9/9 OK** (was skipped=1).
- **Left alone (defensible):** `test_rest_migration_helpers.py:476` interior-gap skip (data-dependent;
  `get_mutation_gap_report` is covered by 41 other passing tests in that file). The session-1 handoff's old
  force-reimport skip is already resolved/gone.

## STILL OPEN — orchestration coverage (NOT started)
The original ask this session. Scoped but not begun. Uncovered API-heavy targets in
`eboekhouden_rest_full_migration.py`:
- `start_full_rest_import` (3182) — top entrypoint: mutation-type selection (type-0 auto-add, date filter),
  type-0 opening-balance routing, empty-mutations branch, token-missing/no-company early returns, final stats.
- `_import_rest_mutations_batch_enhanced` (3737) — takes a mutations list (no HTTP itself): empty / no-cost-
  center / missing-id / already-imported / should-skip / success / error paths + per-mutation savepoint +
  summary + retry.
- `_process_mutation_with_coordinator` (3413) — richest target; testable with a FAKE coordinator object
  (duck-typed `process_mutation` + `last_processor_debug_info`), no HTTP: success/new, legit-skip, None→legacy
  fallback, raise→legacy, legacy-success, failed, stock-error branches.
- `_cache_all_mutations` (539).
- **Already covered, do NOT redo:** the batch helpers `_categorize_batch_errors`/`_log_batch_summary`/
  `_get_bank_transaction_stats`/`_retry_transient_failures` (in `test_rest_party_dispatch.py`), and whitelist
  endpoints `migration_status_summary`/`analyze_import_failures`/`get_mutation_gap_report`
  (in `test_rest_migration_helpers.py`).

**Boundary to stub:** `EBoekhoudenRESTIterator` — `fetch_mutations_by_type(mutation_type, limit)` and
`fetch_mutation_detail(id)` — plus `settings.get_password("api_token")`. Reuse the `_FakeIterator` pattern in
`test_rest_party_dispatch.py` (instance replaces the class; `__call__`/construction returns self;
`fetch_*` returns canned data). `start_full_rest_import` also needs a real `E-Boekhouden Migration` doc +
`E-Boekhouden Settings` single. Suggested approach: probe the iterator-stub recipe once, then fan out 3
parallel agents (distinct test sites) — one per orchestration cluster — per the proven sweep pattern.

## Gotchas carried forward
- **Concurrent Mollie session is active on develop** — HEAD moves under you; it `git add`s its untracked
  files into the SHARED INDEX, which breaks your `--amend`/commit pre-commit (their
  `test_unprivileged_user_denied` trips the permission-bypass validator). Fix: `git restore --staged <their
  files>`, re-add your pathspec, re-commit. ALWAYS verify `git log -1` is your hash after committing.
- eBoekhouden payment tests: the handler COMMITS PEs → use **time-based unique mutation ids**, never a
  repeating sequence, or you get phantom 0-reference failures via the duplicate early-return.
- `PaymentEntryHandler` needs a **Bank Account master** (not just a Bank-type GL account + ledger mapping).
- Run a single test method: `bench --site <site> run-tests --app verenigingen --module <mod> --test <method>`.
- `black` not importable in this env — use `ruff`; the project ruff hook skips `tests/` paths
  (`(no files to check)`), so pre-existing unused imports there won't block a commit.
