# Handoff — Test-Meaningfulness Review & Remediation (2026-06-15)

## What prompted this
Question: had the recent coverage-sweep batches been reviewed for *meaningfulness*
(do the added tests actually assert behaviour, or just pad coverage)? Answer: they were
gated by `test-quality-enforcer` and skeptically reviewed **for their bug fixes**, but the
**test assertions themselves were never audited**. This session built that audit and acted on it.

Full detail: `docs/plans/2026-06-15-test-meaningfulness-review-inventory.md`.

## Scope reviewed
The 2026-06-14/15 coverage-sweep wave (`4716acae..HEAD` at the time): **145 test files,
~4,130 test functions**. Audited in two passes:
1. **Fast mechanical pass** (new AST tool, below) over all 145 files → flagged ~100 smells
   (mostly NO_ASSERTION), concentrated in `chapter_subscribers` (33).
2. **Deep per-file review** (6 agents) of the two real gaps: the `chapter_subscribers` hotspot
   and the eBoekhouden batch (`6f6ecfe6`, which had had no prior review of any kind).

The deep pass found the suite is **mostly genuinely meaningful** (not coverage padding), but
surfaced three real problems that were then fixed.

## Done & committed (develop, NOT pushed — 7 commits)
```
700317f2 fix(eboekhouden): repair mapping API queries on non-existent columns      [A1]
cb4c36f6 fix(eboekhouden): stop bank-name "ing" matching inside "rekening"          [A2]
0e31f258 fix(eboekhouden): drop inverted, never-created UOM conversion setup        [A3]
729e82a6 test(chapter): harden chapter_subscribers event-handler tests             [B]
05696429 test(eboekhouden): strengthen weak tests + add money-core integration ...  [C+D]
74d4eacb docs(testing): add test-meaningfulness review inventory + remediation ...
<auditor> tooling(testing): add reusable test-meaningfulness AST auditor
```

### Production bugs fixed (each had a `test_PRODUCT_BUG_*` test that passed *because* the code was broken)
- **A1** — `e_boekhouden_account_mapping/api.py`: `get_migration_config_status` /
  `preview_migration_impact` selected non-existent columns (`category`/`confidence`/
  `target_document_type`) → MySQL 1054 on every call. Confirmed live before/after.
- **A2** — `eboekhouden_coa_import.py`: substring matching made `"ing"` match inside
  `"rekening"` → Knab/Rabobank accounts imported as ING Bank. Fixed with a word-boundary helper
  (`_matches_bank_keyword`) across all four matching loops.
- **A3** — `uom_manager.py`: the conversion table was **inverted** vs ERPNext's `1 from = value × to`
  convention AND never inserted (missing mandatory `category`, swallowed). Foppe chose to **delete**
  the broken setup (it was redundant with ERPNext's built-ins and harmful if enabled).

### Test hardening
- **B** `chapter_subscribers` (38/38): Error-Log-count guard (verified via failure injection) +
  email-mock assertions; rebuilt 2 vacuous bulk-import tests against real records.
- **C** 8 eBoekhouden modules: deleted 2 vacuous stub-asserting tests, fixed the mislabelled
  smart-typing-vs-fallback class (+ real forced-ImportError test), replaced shape-only/tautological/
  idempotency tests with real DB-state assertions, made the deprecated tegenrekening passthrough test
  honestly document its dead code.
- **D** 5 new money-core integration tests: Payment Entry create path (receipt / supplier payment /
  receipt allocated to a Sales Invoice) and Stock Reconciliation create path (item/warehouse/qty/
  valuation + a real Stock Ledger Entry). No bug found in the create paths.

All touched modules verified green individually on veg11; all 7 commits passed pre-commit
(including `test-quality-enforcer`). Nothing pushed.

## The reusable tool
`scripts/testing/test_meaningfulness_auditor.py` — static AST auditor flagging tests that cannot
catch a regression (NO_ASSERTION / TAUTOLOGY / BROAD_RAISES / MOCK_ONLY). Resolves assertion-bearing
helper methods transitively to keep false positives low (a test delegating to `self._ok(...)` is not
flagged — this matters; the naive version had ~19 false positives in `test_sepa_input_validation.py`).

```bash
# triage a future sweep: scan its new tests
python scripts/testing/test_meaningfulness_auditor.py --changed-since <baseline-ref>
# scan a directory or specific files
python scripts/testing/test_meaningfulness_auditor.py verenigingen/tests/e_boekhouden
```
Advisory only (always exits 0). It finds *missing/trivial* assertions; it CANNOT judge whether an
existing assertion checks the right thing — that still needs a deep read. The proven workflow:
**auditor to triage → deep per-file agent review of the flagged files → fix.**

## Residual / deferred (NOT done — for a future session)
1. **MOCK_ONLY = 17** across the broader `verenigingen/tests/e_boekhouden/` dir (run the auditor on
   that dir). Mostly pre-existing (not sweep tests); worth a look — tests asserting only that a mock
   was called.
2. **Deprecated `_generate_item_name` f-string bug** (`smart_tegenrekening_mapper.py:283-285`): uses
   literal `"{self.company}"` in `.replace()` so cleanup never runs. Left unfixed (deprecated module,
   out of prod path); now honestly documented by its test rather than masked.
3. **Dead `is_enhanced_processing_enabled`** (`payment_processor.py`, `return True`): its vacuous test
   was deleted; the method itself was left for a future product cleanup.
4. **Stock Reconciliation lacks `eboekhouden_mutation_nr` custom field** (Payment Entry / Sales Invoice
   have it). The processor sets it as an in-memory attr that's silently dropped on save, so the
   idempotency/duplicate-handling branch can't be exercised. Add the custom field if that branch
   matters, then test it.
5. The wider sweep wave (member, payments, ponto, mollie, dues — chunks B/C/D/E/F/G in the inventory)
   had only fix-level review, not the deep test-assertion read. The auditor `--changed-since` count is
   now low after this session's hardening, but a deep pass on the money-path chunks (payments/ponto)
   is the next-highest-value follow-up if you want full confidence.

## Env gotchas worth remembering
- `test-quality-enforcer` allows `insert(ignore_permissions=True)` only in helper methods whose name
  matches its allowlist (`_make_`/`_create_`/`_insert_`/`_persist_`/`_with_`/`_setup_`/`setUp` …) — see
  `scripts/validation/test_quality_enforcer.py:506-534`. `_seed_` is NOT on the list (caught a helper
  during commit; renamed to `_make_`).
- The `get_mutation_gap_report` product function is **global/un-scoped** and veg11 holds ~10k mutations,
  so a literal `gaps==[2]` assertion is impossible — the integration test seeds one gap and asserts the
  delta instead.
- Test-runner FiscalYear quirk: erpnext's test setup restricts the current FY to `_Test Company`, so
  submit-based tests on other companies need a module fixture that drops the `Fiscal Year Company` rows
  (handled in the new integration tests).
