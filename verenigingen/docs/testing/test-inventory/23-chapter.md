# Test Inventory — Domain CHAP (tests/chapter)

> **COMPLETE** — read-only classification of every class-level `def test_*` method into HAPPY / UNHAPPY / EDGE / OTHER. 38 files, 701 methods. No test was modified or run.

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_base_manager.py | 18 | 9 | 5 | 4 | 0 |
| test_board_manager.py | 52 | 26 | 9 | 17 | 0 |
| test_board_member_validator.py | 18 | 2 | 8 | 7 | 1 |
| test_board_role_profile_sync.py | 8 | 2 | 2 | 4 | 0 |
| test_chapter_board_document.py | 10 | 6 | 3 | 1 | 0 |
| test_chapter_board_lifecycle_notifications.py | 8 | 3 | 1 | 4 | 0 |
| test_chapter_board_member.py | 12 | 3 | 1 | 8 | 0 |
| test_chapter_board_permissions_comprehensive.py | 12 | 2 | 1 | 1 | 8 |
| test_chapter_board_permissions_fixed.py | 6 | 1 | 0 | 0 | 5 |
| test_chapter_board_permissions.py | 15 | 11 | 1 | 0 | 3 |
| test_chapter_board_permissions_service.py | 5 | 1 | 0 | 4 | 0 |
| test_chapter_controller.py | 52 | 28 | 13 | 11 | 0 |
| test_chapter_join_request.py | 12 | 6 | 1 | 2 | 3 |
| test_chapter_members_enhanced.py | 8 | 4 | 0 | 2 | 2 |
| test_chapter_members_integration.py | 7 | 5 | 0 | 1 | 1 |
| test_chapter_members_phase_5_2_mock_elimination.py | 5 | 3 | 0 | 2 | 0 |
| test_chapter_permissions.py | 8 | 5 | 3 | 0 | 0 |
| test_chapter_service_coverage.py | 68 | 34 | 12 | 20 | 2 |
| test_chapter_utils.py | 40 | 21 | 1 | 18 | 0 |
| test_chapter_validator_coverage.py | 10 | 5 | 0 | 5 | 0 |
| test_chapter_validator.py | 15 | 6 | 2 | 7 | 0 |
| test_communication_manager_coverage.py | 13 | 6 | 0 | 7 | 0 |
| test_communication_manager.py | 37 | 22 | 0 | 15 | 0 |
| test_member_manager_coverage.py | 14 | 2 | 3 | 9 | 0 |
| test_member_manager.py | 40 | 18 | 12 | 10 | 0 |
| test_postal_code_validator_coverage.py | 11 | 2 | 3 | 6 | 0 |
| test_postal_code_validator.py | 36 | 15 | 9 | 12 | 0 |
| test_regression_chapter_join_member_lookup.py | 6 | 2 | 0 | 4 | 0 |
| test_role_profile_integration.py | 10 | 1 | 2 | 2 | 5 |
| test_role_profile_managers.py | 22 | 11 | 5 | 4 | 2 |
| test_team_role_basic.py | 7 | 1 | 0 | 2 | 4 |
| test_team_role_integration.py | 17 | 4 | 0 | 11 | 2 |
| test_team_role_migration.py | 11 | 0 | 0 | 9 | 2 |
| test_team_role_profile_sync.py | 16 | 6 | 2 | 8 | 0 |
| test_team_role_validation.py | 14 | 3 | 3 | 6 | 2 |
| test_team_service_integration.py | 35 | 12 | 7 | 16 | 0 |
| test_volunteer_integration_manager_coverage.py | 10 | 3 | 0 | 7 | 0 |
| test_volunteer_integration_manager.py | 13 | 8 | 0 | 5 | 0 |
| **DOMAIN TOTALS** | **701** | **299** | **109** | **251** | **42** |

## Observations

- **Edge-heavy domain (251 / 701 ≈ 36%).** The chapter domain is dominated by boundary/negative behaviour: empty lists, missing/null links (volunteer without member, member without user), inactive/disabled rows being skipped, idempotency/no-op re-runs, and duplicate-role handling. Manager/service files (`board_manager`, `chapter_utils`, `chapter_service_coverage`, `team_service_integration`) drive most of this — they systematically exercise the "no board / no member / already present / inactive" branches. Happy paths (299 ≈ 43%) still lead, and genuine error/throw/denial cases (UNHAPPY 109 ≈ 16%) cluster in the validators (`board_member_validator`, `postal_code_validator`, `member_manager`, `team_service_integration` role-profile throws) and the permission-denial tests.

- **OTHER (42 ≈ 6%) is concentrated and explains itself.** The largest single contributor is `test_chapter_board_permissions_comprehensive.py`, where **8 of 12 methods are `@unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)`** (the Volunteer Expense DocType was archived). Similar archived-feature skips appear in `test_chapter_board_permissions.py` (3) and `test_team_role_integration.py` (1). The rest of OTHER is smoke/structural: `test_chapter_board_permissions_fixed.py` (5/6 are factory-creation / perf-timing / raw-SQL smoke with prints and weak asserts), and the `validate_system_configuration` / `validate_all_role_profiles` / `entity_config_completeness` shape-checks in the role-profile files (assert dict keys + `>= 0`, which is tautological).

- **Weak-assertion "returns_X" tests border on OTHER but were counted HAPPY.** A recurring pattern (`get_summary_shape`, `..._returns_list`, `..._returns_dict`, `..._returns_bool`, `load_email_settings_returns_dict`) asserts only the return type after a real call. They exercise the real code path (so not tautological mocks), but their regression-catching power is thin. If the intent is meaningful-coverage triage, these ~12-15 methods (across `communication_manager`, `chapter_service_coverage`, `chapter_controller`, `volunteer_integration_manager`) are the first candidates to strengthen.

- **Mock usage is mostly disciplined.** `test_chapter_board_member.py`, `test_board_role_profile_sync.py`, and both `test_team_role_profile_sync.py` / `test_chapter_board_permissions*` use `mock_frappe` patching, but they assert real branch outcomes (role kept/removed, correct filter shapes, exception logged-not-raised) rather than tautologies. `test_chapter_members_integration.py` explicitly annotates its one `@patch("frappe.sendmail")` as a justified external-service mock. Only `test_count_filters_use_correct_doctype_and_operator` is a pure call-args assertion, and it guards two named regressions (correct DocType + `not set` operator), so it was kept as EDGE, not OTHER.

- **Duplicate/parallel coverage files.** Several concerns are tested twice: a focused file plus a `*_coverage.py` sibling (`chapter_validator`, `communication_manager`, `member_manager`, `postal_code_validator`, `volunteer_integration_manager`, `role_profile_managers` vs `role_profile_integration`). There is also naming overlap (`test_chapter_board_permissions.py`, `..._comprehensive.py`, `..._fixed.py`, `..._service.py` all cover chapter-board permissions from different angles). This is not necessarily redundant, but the permissions cluster is where archived-skip dead weight and smoke tests concentrate.

- **No missing or zero-method files.** All 38 files found by `find verenigingen/tests/chapter -name "test_*.py"` contain at least one class-level test method; every file is represented in the table. `test_team_role_migration.py` is the only file with **zero HAPPY** methods — by design, it is entirely migration data-consistency / integrity / repair / rollback scenarios (classified EDGE) plus fixture-integrity and perf smoke (OTHER).

## Notes on zero-method / missing files

- None. All 38 discovered files have ≥1 test method and are classified above. No empty test classes or import-only stubs were found in this domain.
