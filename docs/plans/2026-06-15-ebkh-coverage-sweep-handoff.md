# eBoekhouden coverage sweep + migrate DDL fix — handoff (2026-06-15)

## Status: PUSHED to origin/develop (`4f4022a5..74d4eacb`). All pre-commit + pre-push hooks green, no SKIP.

## What happened
Codecov showed `verenigingen/e_boekhouden/` as the biggest untouched coverage gap
(utils/ ~7%, ~10.6k missed lines). Ran a probe-then-fan-out sweep (1 probe + 4
parallel agents on distinct test sites), a 4-reviewer skeptical audit for test
*meaningfulness*, then 2 agents to strengthen the weak tests. Separately, fixed a
`bench migrate` failure on veg11 and the app-wide DDL anti-pattern behind it.

**Result: 17 new eBoekhouden test files, ~479 tests, all green.**

## My commits (mine, all pushed)
- `d9c0d129` fix(eboekhouden): repair 3 bugs surfaced by coverage sweep
- `6f6ecfe6` test(eboekhouden): coverage sweep for utils/services/doctype (~440 tests)
- `f1fe1fa9` test(eboekhouden): strengthen weak assertions flagged by review
- `077848c0` fix(migrate): run index/DDL through sql_ddl() to avoid ImplicitCommitError

## Concurrent-session commits (NOT mine, also pushed — a parallel session fixed the bugs I flagged)
- `700317f2` fix(eboekhouden): repair mapping API queries on non-existent columns  → my flag #1
- `cb4c36f6` fix(eboekhouden): stop bank-name "ing" matching inside "rekening"      → my flag #2
- `0e31f258` fix(eboekhouden): drop inverted, never-created UOM conversion setup    → my flag #3
- `729e82a6` test(chapter): harden chapter_subscribers event-handler tests
- `05696429` test(eboekhouden): strengthen weak tests + add money-core integration tests
- `74d4eacb` docs(testing): add test-meaningfulness review inventory + remediation record
- (`b96c1987`, `a759ec7e` were committed locally AFTER my push — left for the concurrent session to push)

## Bugs FIXED this session (mine)
1. **`migration_status_summary()` was dead on EVERY site (incl. veg11).** Counted a
   non-existent Cost Center custom field AND the non-existent `EBoekhouden REST
   Mutation Cache` table → 1054/1146 swallowed into an error dict. Both counts now
   guarded (`has_field`/`table_exists`). (`utils/eboekhouden_rest_full_migration.py`)
2. **`base_processor.get_description()` crashed** with TypeError on integer
   `MutatieNr`. Coerced to `str`. (`utils/processors/base_processor.py`)
3. **`_get_group_name()` returned literal `"Group {group_code}"`** (missing
   f-prefix). (`utils/eboekhouden_migration_enhancements.py`)
4. **`bench migrate` aborted + app-wide DDL bug (`077848c0`).** CREATE INDEX /
   ALTER autocommit in MariaDB, so running them via `frappe.db.sql()` mid-migration
   raises `ImplicitCommitError`. Fixed the aborting hook + the *same* anti-pattern
   in EVERY index patch and `performance_optimization_setup` → `frappe.db.sql_ddl()`.
   Many of those were wrapped in try/except and **silently swallowed** the error, so
   their performance indexes had **never been created on any site** (latent perf
   bug). Verified: veg11 migrate now completes and indexes materialize.

## Still OPEN (verify / decide)
1. **api.py mapping endpoints — Python columns fixed (`700317f2`), but the JS path
   may still be wrong.** The JS calls `verenigingen.e_boekhouden.api.get_migration_config_status`,
   but `e_boekhouden/api/__init__.py` is empty and the fns live in the doctype
   module. Confirm the UI actually reaches the endpoint (manual test) — the column
   fix alone doesn't rewire the method path.
2. **Dangling `EBoekhouden REST Mutation Cache` doctype.** Referenced 4× in
   `eboekhouden_rest_full_migration.py` (incl. `frappe.new_doc(...)` and
   `_cache_all_mutations`, which has no callers) but has no JSON / table anywhere.
   The status-report count is now guarded, but the cache mechanism is dead/dangling
   — was it removed or renamed? Decide cleanup vs. restore.
3. **Stale index patches on veg11 not re-materialized.** The `patches.txt`-registered
   index patches (`v15_0`/`v2_1`) are already recorded as "run", so the `sql_ddl()`
   fix does NOT recreate their previously-swallowed indexes. To materialize them on
   veg11, re-run each manually: `bench --site veg11.veganisme.org execute
   verenigingen.patches.<...>.execute` (idempotent). The `after_migrate` ones
   (coverage, chapter_dashboard, performance_optimization_setup) self-heal on migrate.

## Deferred test gaps (coverage % overstates protection here)
Covered the *deciders* (routing, classification, parsing, name-building), not the
heavy *creators* needing a full integration harness (submitted invoices/GL/fiscal
year): `_process_single_mutation`, `_create_sales_invoice`/`_create_purchase_invoice`/
`_create_journal_entry`/`_create_payment_entry`, opening-balance JE end-to-end; the
*active* payment-gateway amount-adjustment + `_allocate_*`/submit; full
`_create_stock_reconciliation`; `create_journal_entry_impl`/`create_*_invoice_impl`;
`cleanup_utils` destructive bulk paths. (Note: the concurrent session's `05696429`
added "money-core integration tests" — re-check which of these it closed.)

## Test-meaningfulness review (done)
4 skeptical reviewers read each test + the production code under test. Verdict:
tests are genuinely meaningful ("substantially better than typical coverage-
padding"); ~13 weak ones (existence-only assertions masking silent fallbacks,
shape-only tests on risky delete paths, an order-dependent test) were strengthened
in `f1fe1fa9`. The `skeptical-code-reviewer` agent
(`.claude/agents/skeptical-code-reviewer.md`) was permanently updated with a
"Step 5b: Test Meaningfulness Adjudication" + verdict output, so this is now
standing behavior.

## Reusable gotchas
- **DDL in migrations MUST use `frappe.db.sql_ddl()`**, never `frappe.db.sql()` —
  CREATE/ALTER/DROP autocommit in MariaDB and trip `ImplicitCommitError`. Beware
  `try/except` that silently swallows it (index never created).
- `_Test Company`=INR, `_Test Company 2`=EUR on all test sites → `_persist_eur_company()`.
- `run-tests --module A --module B` runs ONLY B.
- ruff + black EXCLUDE `verenigingen/tests/`; `ruff format <glob>` reformats tracked
  tests too — revert those.
- E-Boekhouden Settings singleton has no `api_token` on test sites; if code under
  test does its own `settings.save()`, populate mandatory fields at the DOC level
  (a `_persist_` helper) — and re-run new singleton-save tests on a SECOND site,
  it's site-state dependent.
- Concurrent session active on develop — commit with explicit pathspec; expect
  extra commits to appear; don't push a moving branch you don't own.
