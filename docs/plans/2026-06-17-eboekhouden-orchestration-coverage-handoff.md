# Handoff — eBoekhouden REST orchestration coverage + cache-ref cleanup (2026-06-17, session 3)

Follow-on to `2026-06-17-eboekhouden-rest-migration-coverage-handoff.md` and
`2026-06-17-eboekhouden-deadcode-and-phantom-skips-handoff.md`. Closes the
"API-heavy orchestration uncovered" open item from those.

## State — DONE & PUSHED
- Branch `develop`, **0 ahead of origin** (pushed 2026-06-17, range `ab5854e9..3eb8e59e`).
- My two commits in that push:
  - **`c18bf895`** `test(eboekhouden): cover REST full-migration orchestration layer` (20 tests)
  - **`1ee585a8`** `refactor(eboekhouden): remove dead 'EBoekhouden REST Mutation Cache' references` (7 files, 410 del)
  - (the other two pushed commits — `630f3bbb`, `3eb8e59e` — are a concurrent session's `setup` work, not mine.)
- Pre-push was fully clean, **no SKIP needed** (critical-tests coverage gate, lint, API contracts, JS-Python param validator all passed).
- Working tree: only pre-existing noise (`email_brand.css`, untracked `docs/plans/*` handoffs, an untracked
  `test_setup_btw_eboekhouden.py` that belongs to the concurrent session). Nothing of mine uncommitted.

## What got covered — 3 new test files in `verenigingen/tests/e_boekhouden/`
Target: `verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py`.
- `test_rest_orchestration_dispatch.py` (7) — `_process_mutation_with_coordinator` (L3413): coordinator
  success/skip/None-fallback/raise dispatch + legacy fallback + non-stock error classification.
- `test_rest_orchestration_batch.py` (7) — `_import_rest_mutations_batch_enhanced` (L3737): empty / missing-id /
  already-imported / should-skip / success / error / no-cost-center tally branches; success creates a real
  submitted balanced JE.
- `test_rest_orchestration_start.py` (6) — `start_full_rest_import` (L3182): token gate, happy-path real type-7
  → JE + progress=100, mutation_types normalization, date-window filtering (with positive control), per-type
  fetch-exception capture.

Run them:
```
cd /home/frappeuser/frappe-bench
bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.e_boekhouden.test_rest_orchestration_dispatch
bench --site test_site_2 run-tests --app verenigingen --module verenigingen.tests.e_boekhouden.test_rest_orchestration_batch
bench --site test_site_3 run-tests --app verenigingen --module verenigingen.tests.e_boekhouden.test_rest_orchestration_start
```

## Hard-won gotchas (read before extending these suites)
- **Enforcer bans `patch(...process_...)`** (`scripts/validation/test_quality_enforcer.py` `never_mock_patterns`
  = `process_`/`validate_`/`business_rule`). Can't patch `_process_single_mutation`/`_process_mutation_with_coordinator`.
  Instead pass the coordinator as a **test-double ARGUMENT** (it's a function param, not a patch). Also bans
  patching `frappe.get_doc/get_all/new_doc/db.*`. Only the HTTP boundary (`EBoekhoudenRESTIterator`/`EBoekhoudenAPI`)
  may be patched — established precedent in `test_rest_party_dispatch.py`.
- **`ignore_permissions=True` only in `_make_`/`_ensure_`/`_setup_` helpers, never a test body** (extracted a
  bare-company create into `_ensure_company_without_cost_center`; renamed `_configure_settings`→`_setup_settings`).
- **New-processors path skips the iterator for inline type-7 memorials** → to reach the legacy iterator-error
  branch, toggle `frappe.conf["eboekhouden_use_new_processors"]=False` (config flag, not a business-logic mock).
- **Error branches induced via a uniquely-TAGGED iterator exception** (`_RaisingIterator`, asserting the tag is
  in the result) so the failure is deterministic — do NOT lean on the incidental missing-token ctor crash
  (coupled to ambient site state; was the skeptical reviewer's main ask).
- **`E-Boekhouden Ledger Mapping` is keyed by `ledger_id` GLOBALLY and persists across suites** on the shared
  test sites → a suite's `_ensure_ledger_mappings` no-ops when 8100/4100 were already mapped by another suite,
  so the JE uses THAT suite's accounts. Don't assert `self.income`; resolve expected accounts from the live
  mapping (`get_value("E-Boekhouden Ledger Mapping", {"ledger_id":"8100"}, "erpnext_account")`).
  `total_debit == 25.0` is robust regardless.
- `start_full_rest_import`'s `api_token` is a **mandatory Password field** → can't `save()` the single empty;
  write the encrypted password directly (`set_encrypted_password`) to exercise the no-token gate.
- Concurrent session shares the git index → a `git commit` can be aborted mid-pre-commit (files left staged);
  just re-stage with explicit pathspec + re-commit.

## Cache-ref cleanup (`1ee585a8`)
`EBoekhouden REST Mutation Cache` doctype is **not shipped** (no JSON / no table on any site) → every reference
was dead. Removed: `_cache_all_mutations` (0 callers); the cache-status block in `migration_status_summary`;
`export_unprocessed_mutations` + `_csv` (read ONLY the absent cache → always errored; their 2 Critical Operation
Rule fixtures too); cache lookups in `check_equity_import_status` (eboekhouden_api), `check_migration_progress`,
`scripts/api_maintenance/fix_eboekhouden_import.py`; the cache reset/count steps in BOTH nuke utilities. The nuke
scripts themselves are **LIVE** (invoked from `/admin_tools`) — kept; only their cache steps stripped.
`test_rest_migration_helpers` (42 tests, covers `migration_status_summary`) still green.

## STILL OPEN (eBoekhouden rest_full_migration)
- The deep **type-0 opening-balance path** through `start_full_rest_import` (→ `_import_opening_balances`) is
  not covered by the orchestration suite (it's heavy; the start tests deliberately skip type 0).
- `test_opening_balance_import.py` force-reimport skip was already resolved on a dedicated company in the prior
  session (see the rest-migration-coverage handoff) — nothing left there.
