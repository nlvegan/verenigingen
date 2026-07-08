# Domain A3 — Donation & Donor Services: Test Inventory

Read-only classification of every `def test_*` method across the 11 donation/donor
service test files. Covers donation creation/financial paths, Journal-Entry money
paths (donation + refund), donation reporting aggregation, donor auto-creation,
donor↔customer sync, donor management, donor↔member reconciliation, and the donor
service wrapper.

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_donation_financial_service.py | 9 | 6 | 1 | 2 | 0 |
| test_donation_journal_entry_creator.py | 17 | 2 | 1 | 9 | 5 |
| test_donation_journal_entry_creator_coverage.py | 10 | 3 | 3 | 4 | 0 |
| test_donation_refactoring_integration.py | 0 | 0 | 0 | 0 | 0 |
| test_donation_refund_journal_entry_creator_coverage.py | 9 | 2 | 2 | 5 | 0 |
| test_donation_reporting_service.py | 13 | 9 | 1 | 3 | 0 |
| test_donor_auto_creation.py | 19 | 8 | 7 | 4 | 0 |
| test_donor_customer_sync.py | 10 | 5 | 0 | 5 | 0 |
| test_donor_management_service.py | 17 | 8 | 3 | 5 | 1 |
| test_donor_member_reconciliation.py | 18 | 7 | 1 | 10 | 0 |
| test_donor_service.py | 24 | 9 | 3 | 10 | 2 |
| **DOMAIN TOTALS** | **146** | **59** | **22** | **57** | **8** |

## Notable per-file detail

**test_donation_financial_service.py** (EnhancedTestCase) — mostly happy creation
paths (bank transfer, SEPA one-off/recurring, chapter). EDGE = no-donation_type,
default-notes. UNHAPPY = invalid-chapter throws. `reconcile...clean` classed HAPPY
(runs the report and checks structure/discrepancy count).

**test_donation_journal_entry_creator.py** (unittest + EnhancedTestCase) — heaviest
OTHER count (5): 4 are `@unittest.skip` stubs (`test_reconcile_bank_transaction_*`,
`test_full_mollie_payment_flow`) plus `test_factory_function_returns_instance`
(isInstance smoke). `test_get_config_returns_valid_config` also flagged OTHER — it
asserts "either valid config OR an error key", accepting both outcomes, so it can
never fail meaningfully. Many EDGE tests are mock-based company-resolution
fallbacks and idempotency checks.

**test_donation_journal_entry_creator_coverage.py** (EnhancedTestCase) — real-DB
money path. Strong: asserts actual Debit-clearing/Credit-income legs, amounts,
posting-date parsing, write-back, idempotency counts, and error branches. Good
balance.

**test_donation_refactoring_integration.py** — **NO `def test_*` methods.** It is a
script-style manual harness (`run_full_test()` / `run_integration_test()`) that
prints ✅/❌ and returns booleans; not collectible by the test runner. Not counted.

**test_donation_refund_journal_entry_creator_coverage.py** (EnhancedTestCase) —
load-bearing correctness test asserts the REVERSED legs (Debit income / Credit
clearing). Solid EDGE coverage (null/unparseable date, idempotency).

**test_donation_reporting_service.py** (EnhancedTestCase) — happy-skewed aggregation
tests with real assertions on totals/paid/outstanding and per-chapter/per-campaign
sub-dicts. One UNHAPPY (invalid chapter throws).

**test_donor_auto_creation.py** (EnhancedTestCase) — richest UNHAPPY coverage (7):
every `test_auto_creation_conditions` failure branch asserts the specific
`failure_reason` string (disabled / no-GL / missing-customer / group-ineligible /
below-minimum / already-exists). `test_group_ineligible_when_not_in_list` classed
UNHAPPY (rejection).

**test_donor_customer_sync.py** (EnhancedTestCase) — EDGE-heavy on skip-flag /
inert-in-test / no-op branches; the NULL+empty→"Unknown" fold is an explicit
regression guard. No UNHAPPY.

**test_donor_management_service.py** (EnhancedTestCase) — OperationResult pattern
(never raises), so failures surface as `result.success=False` → classed UNHAPPY
(duplicate, no-address, missing-customer). Phone-formatting variants split
happy(mobile/landline) vs edge(prefixed/no-zero/spaces). OTHER = factory isInstance
smoke.

**test_donor_member_reconciliation.py** (EnhancedTestCase) — EDGE-dominant (10):
empty/None inputs, no-match→None, duplicate-most-recent-wins, invalid-link
fallback, ambiguous employee resolution. One UNHAPPY (invalid primary → error).

**test_donor_service.py** (VereningingenTestCase — the only file NOT on
EnhancedTestCase) — broadest single file. 2 OTHER:
`test_update_donor_donation_history_does_not_raise` (smoke "does not raise",
asserts IsNone) and `test_factory_returns_service` (isInstance smoke). Several
tests document behavior of schema-absent fields (privacy_consent always reported).

## Observations

- **Balanced-to-edge-heavy domain.** 146 methods: 40% Happy, 39% Edge, 15%
  Unhappy, 5% Other. Edge coverage is genuinely strong — idempotency, null/empty
  inputs, duplicate-donor resolution, date-parse fallbacks, and skip-flag branches
  are all exercised against the real DB.
- **One file contributes zero collectible tests.**
  `test_donation_refactoring_integration.py` has no `def test_*` methods — it is a
  print-based manual script (`run_full_test`). It inflates the file count but adds
  nothing to the runner's assertions; worth flagging for conversion or removal.
- **The 8 OTHER tests cluster in two files.**
  `test_donation_journal_entry_creator.py` carries 4 `@unittest.skip` stubs (Bank
  Transaction / full-Mollie-flow "requires setup") plus 2 weak smokes
  (factory-isInstance, and `test_get_config_returns_valid_config` which accepts
  either a valid config OR an error key so it cannot fail). Its real money-path
  coverage lives in the sibling `_coverage.py` file, which is much stronger — the
  mock-based original is largely redundant.
- **Base-class consistency:** 10 of 11 files use `EnhancedTestCase`;
  `test_donor_service.py` alone uses `VereningingenTestCase`. Both are real-DB
  integration bases (no business-logic mocking) except the mock-based unit class in
  `test_donation_journal_entry_creator.py`.
- **UNHAPPY is well-served for guarded services but style-dependent:**
  OperationResult/condition services (donor auto-creation, donor management) express
  failures as return values that these tests assert on; the throwing services
  (financial, reporting, donor_service) assert `frappe.ValidationError`. No gaps in
  error-branch coverage were evident.
- **Minor weak spot:** `test_get_config_returns_valid_config` and
  `test_update_donor_donation_history_does_not_raise` assert little of substance and
  would survive most regressions in the code under test.
