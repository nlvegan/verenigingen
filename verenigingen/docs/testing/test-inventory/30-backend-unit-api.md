# Test Inventory — DOMAIN BUAPI (tests/backend/unit/api)

> **COMPLETE** — all 15 files audited. Read-only classification of every class-level `def test_*` method.
> Categories: HAPPY (nominal success) | UNHAPPY (expects error/throw/denial/guard-block) | EDGE (boundary/empty/null/dup/idempotency/malformed/guest/ordering) | OTHER (smoke/shape-only/tautology/skip-dominated).

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_chapter_api.py | 17 | 1 | 2 | 1 | 13 |
| test_chapter_dashboard_api_coverage.py | 24 | 8 | 5 | 9 | 2 |
| test_member_api_extracted.py | 17 | 4 | 3 | 6 | 4 |
| test_member_api.py | 17 | 13 | 1 | 2 | 1 |
| test_member_api_shims.py | 8 | 0 | 3 | 1 | 4 |
| test_member_management_api_coverage.py | 37 | 16 | 5 | 16 | 0 |
| test_member_management_api.py | 4 | 1 | 0 | 0 | 3 |
| test_member_management_mt940_and_emails.py | 26 | 10 | 8 | 8 | 0 |
| test_membership_application_api.py | 8 | 4 | 2 | 2 | 0 |
| test_membership_application_coverage.py | 35 | 18 | 7 | 10 | 0 |
| test_membership_application_review_coverage.py | 16 | 5 | 5 | 6 | 0 |
| test_payment_dashboard_api.py | 27 | 10 | 6 | 11 | 0 |
| test_suspension_api_extended.py | 17 | 6 | 3 | 7 | 1 |
| test_validation_endpoint_wrappers.py | 32 | 11 | 7 | 12 | 2 |
| test_volunteer_api.py | 13 | 8 | 3 | 0 | 2 |
| **DOMAIN TOTALS** | **298** | **115** | **60** | **91** | **32** |

Distribution: Happy 38.6% · Unhappy 20.1% · Edge 30.5% · Other 10.7%.

## Observations

- **Coverage is well-balanced overall** (39% happy / 20% unhappy / 31% edge). The `*_coverage.py` and `*_extended.py` files (added in the 2026 coverage sweeps) are the strongest: they systematically pair a happy path with error, permission-denial, empty/zero, idempotency, and not-found branches. `test_member_management_api_coverage.py` (37), `test_membership_application_coverage.py` (35), `test_payment_dashboard_api.py` (27), and `test_validation_endpoint_wrappers.py` (32) carry the bulk of the unhappy+edge weight and have **zero Other** (except 2 guard-tautologies in the wrappers file).
- **`test_chapter_api.py` is the single weakest file: 13/17 = 76% Other.** Ten tests assert only `assertIsNotNone(result)` or `assertIsInstance(result, list/dict)` and five wrap the call in `try/except (AttributeError, TypeError): pass`, so they silently pass when the endpoint under test doesn't even exist. Only 3 tests (add-board-member persistence, `test_error_handling`, `test_data_integrity`) actually pin behavior — those 3 carry inline comments noting they were tightened from earlier assertion-free versions. This file is the prime candidate for hardening.
- **Mock-tautology / delegation flags:** `test_member_api_extracted.py` is entirely `unittest.TestCase` + `MagicMock` (no real DB). Its 3 "delegates_to_service" tests (`create_member_user_account`, `check_donor_exists`, `create_donor_from_member`) only assert `mock.assert_called_once_with(...)` — they verify wiring, not behavior. `test_derive_bic_valid_dutch_iban` asserts only `callable(fn)` (pure tautology). These 4 are the Other count for that file.
- **The `if result["success"]:`-guarded weak pattern flagged in the brief appears exactly twice**, both in `test_validation_endpoint_wrappers.py`: `test_eligible_applicant_returns_success_with_eligible_key` and `test_with_real_membership_type_returns_success_or_fail` branch their assertions on `success`, so they pass on the failure branch too. Classified Other. The rest of that (characterization) file is solid despite leaning on `_assert_success_shape`/`_assert_failure_shape` helpers, because each test also asserts specific `data`/`error` content.
- **Skip-dominated:** `test_member_management_api.py` has 3 of 4 methods under `@unittest.skip("Flagged: ... not implemented (ambiguous API)")` — real, honestly-flagged gaps (`get_member_chapters`, `update_member_status`) where the referenced API never existed. `test_member_api_shims.py` is registration/serialisation smoke (0 happy, 4 Other) by design — it pins that dotted-path shims resolve, are whitelisted, and are orjson-serialisable, not business behavior.
- **Base classes vary by vintage:** newer coverage files use `EnhancedTestCase` (+ `PortalSelfServiceTestMixin`) with real fixtures and session-user switching for permission-tier tests; older whitelist files (`test_chapter_api`, `test_member_api`, `test_volunteer_api`) use `VereningingenTestCase` with `TestDataBuilder`; two files use raw `unittest.TestCase`/`FrappeTestCase`. Security-tier denial testing (`@critical_api`/`@high_security_api` → `VPermissionError`) is a recurring, well-exercised UNHAPPY theme in the dashboard/management/suspension files.

## Notes on completeness

- All 15 files contain test methods; **no zero-method or missing files**. Method counts match `grep -cE "^\s+def test_"` per file.
- Two files hand-roll fixtures without exercising a real API surface: `test_volunteer_api.py::test_create_volunteer_from_member_whitelist` and `::test_sync_chapter_board_members_whitelist` only create volunteers via the factory and assert linkage/status (the named "sync"/"from_member" APIs are not called) — classified Other.
