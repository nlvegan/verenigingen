# Test Inventory — Domain A7: backend/unit/services (part 1)

Read-only classification of every `def test_*` method across the 18 assigned files under
`verenigingen/tests/backend/unit/services/`. Each method assigned ONE primary type
(HAPPY / UNHAPPY / EDGE / OTHER). Dominant intent wins.

This tree mixes two styles: **real-DB integration-ish** service tests
(EnhancedTestCase / VereningingenTestCase, real Member/Address/Chapter docs) and
**pure mock unit tests** (plain `unittest.TestCase`, MagicMock members + `@patch`ed frappe).
Two files are almost entirely non-behavioral (import/existence + fixture-existence smoke).

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_approval_notifications.py | 12 | 3 | 1 | 0 | 8 |
| test_approval_unification.py | 17 | 0 | 0 | 0 | 17 |
| test_chapter_management_service.py | 31 | 10 | 5 | 15 | 1 |
| test_donation_reporting_api.py | 10 | 8 | 0 | 1 | 1 |
| test_donor_management_service_coverage.py | 3 | 3 | 0 | 0 | 0 |
| test_donor_management_service.py | 15 | 5 | 3 | 6 | 1 |
| test_email_compatibility.py | 5 | 3 | 1 | 0 | 1 |
| test_email_configuration_service.py | 45 | 22 | 5 | 16 | 2 |
| test_fee_override_hook_service.py | 15 | 4 | 1 | 10 | 0 |
| test_field_sync_service.py | 5 | 2 | 2 | 0 | 1 |
| test_member_address_display_service.py | 12 | 5 | 1 | 5 | 1 |
| test_member_address_service_consolidated.py | 8 | 3 | 4 | 1 | 0 |
| test_member_approval_service_coverage.py | 13 | 5 | 4 | 4 | 0 |
| test_member_before_save_service.py | 15 | 8 | 3 | 4 | 0 |
| test_member_chapter_display_service.py | 14 | 7 | 3 | 4 | 0 |
| test_member_debug_service.py | 13 | 8 | 2 | 1 | 2 |
| test_member_debug_tools_api.py | 9 | 5 | 3 | 0 | 1 |
| test_member_duration_service.py | 12 | 5 | 4 | 2 | 1 |
| **DOMAIN TOTALS** | **254** | **106** | **42** | **69** | **37** |

## Base classes used
- `EnhancedTestCase` (real-DB factory): chapter_management, donation_reporting_api,
  donor_management_service(+coverage), email_compatibility, field_sync_service,
  member_address_display_service, member_debug_service, member_debug_tools_api.
- `VereningingenTestCase` (real-DB): member_approval_service_coverage.
- `FrappeTestCase` (mock-heavy w/ some real cache): approval_notifications,
  approval_unification, email_configuration_service.
- Plain `unittest.TestCase` (pure MagicMock, `@patch` frappe): fee_override_hook_service,
  member_address_service_consolidated, member_before_save_service,
  member_chapter_display_service, member_duration_service.

## Observations
- **Coverage skew is HAPPY/EDGE-dominant** (106 happy, 69 edge, 42 unhappy). EDGE is heavily
  represented because the service layer is guard-rich: empty/None member names, disabled
  feature flags, no-chapter/no-address empty states, duplicate/dedup, and skip-flag branches.
- **Two files are almost purely OTHER (non-behavioral).** `test_approval_unification.py`
  (17/17) is entirely `getattr`/`importlib`/AST source-string assertions verifying a refactor
  deleted/preserved symbols — no DB, no logic exercised (the file's own docstring says so).
  `test_approval_notifications.py` is 8/12 OTHER: 5 `db.exists("Email Template", ...)` fixture
  smokes + 3 `inspect.getsource(...)` assertions checking that production code literally
  contains `result.error_message` / lacks `frappe.db.begin()`. These are brittle text/existence
  guards, not behavior tests.
- **"never throws" robustness loops are weak/tautological** — flagged OTHER where the only
  assertion is `assertIsNotNone(result)` / `assertIsNotNone(result.success)`
  (`test_*_never_throws_exceptions` in donation_reporting_api, field_sync_service,
  member_debug_service, member_debug_tools_api; `test_phone_formatting_never_throws`;
  `test_email_wrappers_never_throw_exceptions`). Note `result.success` is always a bool, so
  `assertIsNotNone(result.success)` can never fail — pure tautology.
- **Weak conditional assertions inflate the HAPPY count.** Many EnhancedTestCase API tests
  (donation_reporting_api, email_compatibility, member_debug_tools_api) assert only that a
  `"success"` key / `.success` attr is present, then gate real assertions behind
  `if result["success"]:` — so on a failing path they assert nothing. Counted HAPPY by intent
  but their regression-catching power is low.
- **Mock-tautology watch (flagged but not reclassified):** the plain-`unittest` mock files
  patch the *collaborators* of the service under test, not the service itself, so they mostly
  avoid mocking-the-SUT-into-a-tautology. Closest offenders:
  `email_configuration_service.test_is_email_enabled_with_corrupted_config` (try/except that
  passes whether or not the call raises → OTHER) and `test_is_email_enabled_delegates_to_config`
  (mock returns True, asserts True — survives only because it also asserts the delegation call).
  `fee_override`/`before_save`/`duration`/`chapter_display` tests do assert real side-effects
  (delattr of pending flags, `log_error` called, flag-cleared-in-finally), so they carry weight.
- **The real-DB service tests are the strongest** — `chapter_management_service` (31 tests, full
  happy/edge/unhappy spread over real Chapter/Board rows) and
  `member_approval_service_coverage` (real IBAN-history dedup regression guard) exercise actual
  business logic and would catch genuine regressions.

## Missing files
None — all 18 assigned files were present and classified.
