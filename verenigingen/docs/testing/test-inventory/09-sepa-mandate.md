# Domain A9 — SEPA Mandate Services: Test Inventory

Read-only classification of every `def test_*` method across the 11 glob-matched
`tests/sepa/test_*mandate*.py` files plus the 2 mandate-manager files under
`tests/services/`. 13 files, 267 test methods total.

Classification key: HAPPY = nominal success; UNHAPPY = expects error/throw/validation-
failure/permission-denial; EDGE = boundary/empty/duplicate/concurrency/idempotency/
malformed/date-boundary/FRST-RCUR sequence/mandate-reuse/IBAN edges; OTHER =
smoke/placeholder/tautological.

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| tests/sepa/test_sepa_mandate_identity_service.py | 25 | 11 | 1 | 13 | 0 |
| tests/sepa/test_sepa_mandate_integration.py | 10 | 8 | 1 | 1 | 0 |
| tests/sepa/test_sepa_mandate_lifecycle.py | 8 | 5 | 1 | 2 | 0 |
| tests/sepa/test_sepa_mandate_lifecycle_service.py | 33 | 14 | 3 | 16 | 0 |
| tests/sepa/test_sepa_mandate_member_integration_service.py | 30 | 13 | 6 | 10 | 1 |
| tests/sepa/test_sepa_mandate_naming.py | 8 | 5 | 0 | 3 | 0 |
| tests/sepa/test_sepa_mandate_regression.py | 7 | 1 | 0 | 6 | 0 |
| tests/sepa/test_sepa_mandate_retry_report_coverage.py | 51 | 22 | 8 | 21 | 0 |
| tests/sepa/test_sepa_mandate_runner.py | 11 | 7 | 0 | 2 | 2 |
| tests/sepa/test_sepa_mandate_service_integration.py | 8 | 3 | 2 | 3 | 0 |
| tests/sepa/test_sepa_mandate_validation_service.py | 32 | 7 | 8 | 17 | 0 |
| tests/services/test_sepa_mandate_manager.py | 28 | 13 | 5 | 10 | 0 |
| tests/services/test_sepa_mandate_manager_extended.py | 16 | 5 | 1 | 10 | 0 |
| **DOMAIN TOTALS** | **267** | **114** | **36** | **114** | **3** |

## Observations

- **Sequence-type (FRST/RCUR) coverage is thin.** Only `test_sepa_mandate_runner.py::
  test_mandate_with_usage_history` actually asserts the FRST→RCUR transition (first
  usage FRST, second RCUR) via the `SEPAMandateTestMixin.create_test_sepa_mandate_with_usage`
  factory. `mandate_type` (CORE/OOFF/RCUR/FNAL) is exercised in several places
  (`integration.py::test_sepa_mandate_types_real_logic`, runner scenarios), but the
  SEPA *sequence-type* state machine (FRST-then-RCUR on real collections) is essentially
  covered by a single test. This is the largest SEPA-specific gap.

- **Mandate reuse / one-active-per-IBAN is well covered.** The "second active mandate
  needs a different IBAN" duplicate rule is asserted across many files: manager
  `test_validate_mandate_creation_duplicate_iban_blocked/_allowed`, extended
  `test_create_mandate_duplicate_iban_blocked`, integration
  `test_duplicate_mandate_prevention_real_logic`, plus IBAN-change deactivation
  (`test_deactivate_mandates_*`) and the auto-fix vs manual-review discrepancy split
  in `manager_extended`. IBAN normalization/similarity helpers
  (`_normalize_iban`, `_strings_too_similar`, `_should_auto_fix_iban_change`) are
  unit-tested including empty-input edges.

- **Edge-heavy suite (114 EDGE ≈ 43%), reflecting naming/counter + date-boundary focus.**
  The identity and naming/regression files are dominated by counter mechanics
  (digit-length boundaries, malformed last-mandate, high counter 9999→10000 overflow,
  year/leap-year/New-Year boundaries) and date-driven status transitions
  (future sign-date→Pending, past-expiry→Expired, same-day-expiry). Case-insensitive
  collation duplicate detection is explicitly tested.

- **Two parallel test styles for the lifecycle service.** `test_sepa_mandate_lifecycle_service.py`
  drives the service with `Mock` mandates (33 tests, isolates branch logic), while
  `test_sepa_mandate_retry_report_coverage.py::TestSEPAMandateLifecycleServiceRealDB`
  re-drives the same methods against real persisted docs to hit the member-integration
  DB paths the mocks skip. Good complementary coverage; some duplication of intent.

- **Base classes split by intent.** Mock/unit-style service tests use
  `EnhancedTestCase` (enhanced_test_factory); the end-to-end lifecycle, regression, and
  cross-service integration files use `VereningingenTestCase` (tests.utils.base). The
  runner file additionally mixes in `SEPAMandateTestMixin` and calls
  `make_test_records` in setUpClass.

- **The 3 OTHER tests are genuinely weak.** (1)
  `member_integration_service.py::test_create_sepa_audit_log_with_invalid_data` ends in
  `self.assertTrue(mock_log_error.called or True)` — a tautology that can never fail.
  (2) `runner.py::test_field_validation_safety` is a setattr/getattr round-trip
  field-existence smoke test. (3) `runner.py::test_payment_processing_integration` is a
  self-described placeholder with `skipTest` on any Customer/invoice setup failure and
  only trivial asserts.

- **Report tests classified mostly HAPPY.** In `test_sepa_mandate_retry_report_coverage.py`
  the SEPA Mandate Issues diagnostics report *detecting* a bad-data condition is the
  report's nominal success path, so those execute() branch tests are HAPPY; empty-data,
  severity-exclusion, and HAVING-filter exclusion are EDGE. The retry batch/operation
  controllers contribute most of this domain's UNHAPPY count (validation throws on
  bad category, attempts-over-max, missing reference doc).

## Mandate files found via glob (`tests/sepa/test_*mandate*.py`)

1. test_sepa_mandate_identity_service.py
2. test_sepa_mandate_integration.py
3. test_sepa_mandate_lifecycle.py
4. test_sepa_mandate_lifecycle_service.py
5. test_sepa_mandate_member_integration_service.py
6. test_sepa_mandate_naming.py
7. test_sepa_mandate_regression.py
8. test_sepa_mandate_retry_report_coverage.py
9. test_sepa_mandate_runner.py
10. test_sepa_mandate_service_integration.py
11. test_sepa_mandate_validation_service.py

Plus (explicitly named): tests/services/test_sepa_mandate_manager.py,
tests/services/test_sepa_mandate_manager_extended.py.
