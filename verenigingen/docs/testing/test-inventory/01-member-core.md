# Test Inventory — Domain A1: Member Core Services

One-line summary: 305 test methods across 16 member-core service test files, dominated by happy-path (135) and edge-case (115) coverage; unhappy/error-path coverage (44) is concentrated in the role-profile-manager and member-id services, while the pure calculators and email-sync are almost entirely happy/edge with no unhappy tests.

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|------:|------:|--------:|-----:|------:|
| test_member_age_service.py | 17 | 4 | 0 | 13 | 0 |
| test_member_lookup_service.py | 21 | 8 | 0 | 12 | 1 |
| test_member_status_service.py | 15 | 8 | 3 | 4 | 0 |
| test_member_validation_service.py | 11 | 4 | 0 | 6 | 1 |
| test_member_duplicate_detection_service.py | 19 | 10 | 1 | 8 | 0 |
| test_member_address_service.py | 13 | 6 | 0 | 7 | 0 |
| test_core_member_id_service.py | 14 | 8 | 2 | 4 | 0 |
| test_identification_member_id_service.py | 10 | 5 | 5 | 0 | 0 |
| test_member_role_service_sweep.py | 10 | 4 | 3 | 2 | 1 |
| test_base_role_profile_manager.py | 53 | 18 | 19 | 14 | 2 |
| test_base_role_profile_manager_sweep.py | 26 | 9 | 9 | 7 | 1 |
| test_user_role_profile_calculator.py | 40 | 20 | 2 | 18 | 0 |
| test_user_role_profile_calculator_sweep.py | 26 | 16 | 0 | 10 | 0 |
| test_member_user_email_sync_sweep.py | 5 | 2 | 0 | 3 | 0 |
| test_membership_duration_service.py | 11 | 5 | 0 | 6 | 0 |
| test_member_cleanup_service.py | 14 | 8 | 0 | 1 | 5 |
| **DOMAIN TOTALS** | **305** | **135** | **44** | **115** | **11** |

## Observations

- **Coverage is happy + edge heavy (250 of 305 = 82%); unhappy is thin and lopsided.** 43 of the 44 unhappy tests live in just four files (base_role_profile_manager 19, base_role_profile_manager_sweep 9, identification_member_id 5, member_status 3, core_member_id 2, member_role_sweep 3, calculator 2). The pure calculators/formatters treat negative inputs as graceful `None`/`0`/`[]` returns (classified EDGE), so they carry almost no genuine throw/reject assertions.

- **Whole services with ZERO unhappy tests:** member_age, member_lookup, member_validation, member_address, membership_duration, member_user_email_sync_sweep, user_role_profile_calculator_sweep, and member_cleanup. Several of these (lookup, address, calculator_sweep) are heavily edge-tested, so the gap is specifically *error/throw/permission-denied* assertions rather than boundary coverage. member_cleanup notably has no test that a deletion actually raises/rolls back — its one "error handling" test induces no error.

- **The two strongest files for error-path rigor** are `test_base_role_profile_manager.py` (19 unhappy: validation errors, NOT_FOUND, config errors, disabled-user rejection, exception-swallow) and `test_identification_member_id_service.py` (5/10 unhappy — empty name, nonexistent member, already-has-id). These are the model for what the rest of the domain lacks.

- **Weak / OTHER tests worth flagging (11 total):**
  - `test_member_cleanup_service.py` carries 5 OTHER: three `skipTest` stubs (dues_schedule, sales_invoice_reference_clearing, customer_preserved — all skipped citing ERPNext fixture complexity), plus `test_audit_log_does_not_raise` (pure "must not raise" smoke, no behavioral assertion) and `test_error_handling_in_deletion_loops` (titled error-handling but induces no error → effectively a duplicate happy-path smoke).
  - Three singleton-identity tests (`test_singleton_accessor` in lookup, validation, member_role_sweep) assert only `assertIs`/instance — structural, not behavioral.
  - `test_log_role_assignment_smoke` and `test_chapter_config_constants` (base_role_profile_manager), `test_chapter_config_role_specific_field` (sweep) are constant/smoke checks.
  - `test_create_verenigingen_member_role_when_absent` (member_role_sweep) degrades to a near-tautological `assertTrue(exists)` early-return on any seeded site (its real create-and-assert branch only runs on a bare site) — counted EDGE but borderline OTHER.

- **Base classes are mixed:** `EnhancedTestCase` (age, status, validation, duplicate, address, core_member_id, identification_member_id, email_sync_sweep, membership_duration, cleanup — 10 files), `VereningingenTestCase` (member_role_sweep, base_role_profile_manager x2, user_role_profile_calculator x2 — 5 files, the role/permission-heavy ones), and one **plain `FrappeTestCase`** (`test_member_lookup_service.py`), which hand-rolls Member creation with `flags.ignore_validate`/`ignore_mandatory` and manual `tearDown` cleanup instead of the factory.

- **Edge coverage is genuinely rich** in the calculators and role-profile managers: idempotency, config-cache hits, orphaned/deleted parent rows (ghost chapter/team), missing-profile fall-through, priority-ladder precedence, and dry-run modes are all exercised — so the domain's boundary testing is a strength even where explicit error assertions are absent.

- No listed file was missing; all 16 exist and were read in full.
