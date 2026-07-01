# Plan — e_boekhouden/utils coverage sweep (2026-06-22)

**Status: PREPARED, NOT STARTED.** This is the scoping doc. Do not write tests until kicked off.

**Foppe's scoping decisions (2026-06-22):**
- **Dead code → FLAG ONLY, don't touch.** Sweep tests LIVE files only. Produce a separate
  list of the ~911-miss dead candidates with zero-caller evidence for Foppe to delete later.
  No deletions in this sweep.
- **Sweep size → FULL.** 4 writers covering ALL LIVE files, including the
  `eboekhouden_rest_full_migration.py` spine + `cleanup_utils.py`. Use Batches A–D below.

## Why this cluster

Codecov develop @ `092f2678`: overall 80.5% (note: headline includes test-file lines;
production-only is lower). `e_boekhouden/utils` is the **#1 production gap by a wide margin**:

| Misses | Lines | Cov% | Cluster |
|---:|---:|---:|---|
| **4,944** | 11,106 | **55.5%** | `e_boekhouden/utils` (67 files) |
| 3,030 | 14,353 | 78.9% | `verenigingen/doctype` |
| 2,050 | 9,746 | 79.0% | `verenigingen_payments/utils` |

Nearly 2× the next cluster. Named as next target in `2026-06-22-gate-greening-after-v16-sweep-handoff.md`.

## Critical context

1. **There is already a ~40-file suite at `verenigingen/tests/e_boekhouden/`.** This cluster
   has been partially worked. Writers MUST read the existing test for a file (if any) before
   adding more — gap-fill, don't duplicate. Files with existing tests: http_client_mixin,
   bank_transaction_parser, progress_utils, invoice_classifier, cleanup_utils, coa_import,
   item_naming, tegenrekening_mapper, party_extractor, processors_base, uom_manager,
   transaction_utils, consolidated_utils, invoice_helpers, cost_center_fix,
   configurable_account_mapper, payment_entry_handler, and more (see `grep -rl` in handoff).

2. **eBoekhouden has BOTH a legacy SOAP path and the current REST path.** REST is current.
   Do not write tests pinning SOAP-only behavior. Many "fix"/"reconcile"/"setup" scripts are
   one-off and already-run — dead, not testable.

3. **Lots of 0%-coverage files are dead one-off scripts, not live code.** Blindly testing them
   inflates coverage without value. The classification below separates LIVE from DEAD.

## Live-vs-dead classification (Explore probe — VERIFY the two flagged transitive claims)

### LIVE — sweep targets (write meaningful tests)
| File | Misses | Cov% | Notes |
|---|---:|---:|---|
| eboekhouden_rest_iterator.py | 167 | 11% | core REST pagination; imported by ledger_mapping, import_manager, party_resolver |
| stock_account_handler.py | 166 | 0% | @frappe.whitelist + @high_security_api |
| eboekhouden_enhanced_migration.py | 154 | 0% | called from e_boekhouden_migration on_submit |
| transaction_utils.py | 185 | 31% | imported by rest_full_migration (has existing test — gap-fill) |
| smart_tegenrekening_mapper.py | 125 | 38% | @whitelist; counter-account resolution (has existing test — gap-fill) |
| error_handling_framework.py | 112 | 0% | imported by party_manager (ErrorHandler/safe_get_value) |
| import_manager.py | 112 | 21% | imported by eboekhouden_clean_reimport API |
| eboekhouden_ledger_mapping.py | 109 | 19% | @whitelist; imported by smart_tegenrekening_mapper |
| eboekhouden_rest_client.py | 80 | 31% | core REST client; many importers |
| eboekhouden_payment_mapping.py | 75 | 0% | imported by enhanced_migration + migration doctype |
| eboekhouden_migration_config.py | 66 | 0% | imported by bank_account_utils + payment_mapping |
| create_eboekhouden_custom_fields.py | 45 | 0% | @whitelist + @critical_api; migration setup |
| eboekhouden_account_group_fix.py | 42 | 0% | deprecated wrapper but @whitelist endpoints active |
| **consolidated/account_manager.py** | 141 | 12% | ⚠️ VERIFY: claimed live only via DEAD migration_coordinator — confirm a real caller before testing |
| **eboekhouden_smart_account_typing.py** | 50 | 27% | ⚠️ VERIFY: claimed live only via DEAD migration_utils — confirm a real caller before testing |

**Bigger partially-covered LIVE files worth gap-filling (not in probe list, confirm live first):**
- eboekhouden_rest_full_migration.py — 330 miss, 79% (the migration spine; high value)
- cleanup_utils.py — 214 miss, 48% (has existing test)
- processors/payment_processor.py — 175 miss, 64%
- invoice_helpers.py — 169 miss, 65% (has existing test)
- party_resolver.py — 139 miss, 59%

### DEAD — DO NOT test; flag for Foppe's delete decision

**⚠️ CRITICAL CORRECTION (skeptical review, post C&D): the `consolidated/` package is NOT
dead.** Its *utility submodules* are on the live REST migration import path and must NOT be
deleted: `ledger_utils`, `bank_account_utils`, `invoice_line_utils`, `date_utils`,
`cost_center_utils`, `payment_entry_creation`, `party_utils`, `progress_utils` are imported by
`processors/payment_processor.py`, `eboekhouden_rest_full_migration.py`, `invoice_helpers.py`,
`payment_entry_handler.py`, `transaction_coordinator.py`. Only the three *manager classes* are
call-dead.

**Call-dead (API never invoked), but import-EXECUTED via `consolidated/__init__.py` on every
live migration — deleting requires making `__init__` lazy first, else live imports break:**
- consolidated/party_manager.py (199, DEPRECATED manager)
- consolidated/migration_coordinator.py (186, DEPRECATED manager)
- consolidated/account_manager.py (141, call-dead — verified no live caller)
- error_handling_framework.py (112, only lazy-imported inside dead party_manager → never executed)

**Fully dead one-off scripts / orphans (safe-to-delete candidates, verify once more):**
- migration_utils.py (108)
- e_boekhouden_account_mapping_setup.py (97)
- bank_transaction_analysis.py (86)
- payment_processing/overpayment_detector.py (78)
- account_type_validator.py (64)
- data_quality_utils.py (58)
- bank_transaction_summary.py (35)
- `eboekhouden_enhanced_migration.py::_get_standard_item` (dead method — no callers, reads a
  non-existent `settings.standaard_item` field; flagged by Batch B)

### DEV-TOOL — skip or light smoke only
- debug_helpers.py (44, @development_only_api)
- reconcile_eboekhouden_balances.py (54, manual reconciliation endpoint)

**Realistically reclaimable LIVE target: ~1,600 misses** (minus API-required paths that the
enforcer won't let us mock — expect a meaningful fraction OOS, as on prior eBoekhouden sweeps).

## Execution plan (when kicked off)

1. **Probe (1 agent or inline):** confirm the two ⚠️ transitive-live claims; pull the existing
   test for each LIVE target; identify which lines are API-required (need live eBoekhouden REST)
   vs pure/DB-testable. Output a per-file "testable surface" note.
2. **Parallel writers (3–4 agents, own test sites):** batch the LIVE files. Suggested batches:
   - Batch A (REST core): rest_iterator, rest_client, ledger_mapping, smart_tegenrekening_mapper
   - Batch B (migration flow): enhanced_migration, import_manager, transaction_utils, payment_mapping, migration_config
   - Batch C (whitelist/setup + account): stock_account_handler, create_custom_fields, account_group_fix, error_handling_framework, (verified) account_manager, smart_account_typing
   - Batch D (gap-fill spine): rest_full_migration, cleanup_utils, payment_processor, party_resolver
3. **Skeptical review:** skeptical-code-reviewer reads prod-under-test, flags tautological /
   stub-defeated / characterization-without-correctness tests.
4. **Integration-run on canonical veg11** (`--lightmode`), tighten weak tests.
5. **Fix real bugs found** (eBoekhouden sweeps reliably surface phantom-field / dead-branch bugs).
6. **Commit** to develop; **green the gate** before pushing.

## Gotchas (from prior sweeps — memory)

- **test-quality-enforcer BANS business-logic mocks** (`patch("frappe.db.exists")`,
  `patch("frappe.db.sql")`, etc.) in integration tests → extract a pure helper and test that,
  or use real DB. API-required paths that need a live eBoekhouden token are genuinely OOS.
- Enforcer blocks `ignore_permissions` / `set_user("Administrator")` in test BODIES — only in
  `_make_*` / `create_*` / `setUp` helpers.
- **`frappe.db.sql_ddl()` AUTO-COMMITS** → leaks rows past FrappeTestCase rollback; purge in setUp.
- **FY order-dependence:** never append to shared `FY-<year>`; give each test company its own
  scoped `FY-<abbr>-<year>` (canonical: `sepa_test_company._ensure_current_fiscal_year`). A
  submitted JE needs a current FY for its company → use a DRAFT JE if you only need a lookup.
- **EnhancedTestCase `in_import=True` masks ERPNext validation** — use `production_validation()`
  ctx mgr to see real invoice/due-date/Select validation.
- Wrap exercised calls in `assertNoErrorLog()` (ErrorLogGuardMixin) — catches swallowed+logged
  bugs that otherwise leave tests green. Re-run a suspect module under
  `VERENIGINGEN_FAIL_ON_ERROR_LOG=1` to surface masked bugs.
- `log_error` title truncates at 140 / CharacterLengthExceededError — a latent prod crash class.
- Concurrent sessions share the working tree → use explicit per-file `git add`, avoid shared
  `/tmp/commit_msg.txt`, commit with `-F file` (backticks in `-m` trigger shell substitution).
- Local `bench run-tests` on ERPNext-dep modules can die `DuplicateEntryError Price List` — run
  order-dependence checks on veg11, not isolated.

## Snapshot
- develop @ `092f2678`, in sync with origin, gate GREEN (run 27966859313).
- Codecov read (no token): `api.codecov.io/api/v2/github/nlvegan/repos/verenigingen/totals/?branch=develop`
