# Test Inventory — Domain S1: Security Framework

READ-ONLY audit of all 38 test files under `verenigingen/tests/security/`. Every `def test_*`
method classified into HAPPY (authorized path succeeds), UNHAPPY (expects denial/throw/rate-limit/
CSRF/auth-fail), EDGE (boundary, spoofed/malformed input, TOCTOU/race, replay, empty/null, IP-parse,
escalation-to-graceful-outcome), or OTHER (smoke/import/setup/tautological, or a test that mocks the
security check into a no-op).

**Domain totals: 38 files, 897 test methods — 316 Happy / 161 Unhappy / 281 Edge / 139 Other.**

Note on counts: nested helper functions (e.g. `test_function_pattern1` defined *inside* a test method
as a decoration target in `test_api_security_decorators.py` / `test_api_security_framework.py`) are NOT
counted as test methods — only class-level `def test_*` are. Totals reflect class-level methods only.

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_admin_tools_security.py | 19 | 4 | 4 | 6 | 5 |
| test_api_security_decorators.py | 15 | 7 | 1 | 1 | 6 |
| test_api_security_framework_coverage.py | 44 | 29 | 3 | 9 | 3 |
| test_api_security_framework.py | 42 | 21 | 6 | 7 | 8 |
| test_audit_emitter_coverage.py | 14 | 10 | 0 | 3 | 1 |
| test_audit_logging_coverage.py | 38 | 28 | 2 | 6 | 2 |
| test_auth_hooks_critical_security.py | 13 | 1 | 0 | 12 | 0 |
| test_auth_hooks_security.py | 19 | 4 | 0 | 13 | 2 |
| test_authorization_coverage.py | 37 | 15 | 11 | 10 | 1 |
| test_authorization_engine_policy_coverage.py | 48 | 23 | 11 | 10 | 4 |
| test_client_ip_coverage.py | 26 | 0 | 0 | 26 | 0 |
| test_cor_rate_limiting.py | 7 | 2 | 3 | 2 | 0 |
| test_csrf_ratelimit_cache_coverage.py | 40 | 15 | 7 | 15 | 3 |
| test_enhanced_validation_coverage.py | 99 | 36 | 23 | 31 | 9 |
| test_input_environment_validators_coverage.py | 43 | 23 | 5 | 12 | 3 |
| test_integrated_security_payment_system.py | 7 | 3 | 0 | 1 | 3 |
| test_link_sanitizer.py | 12 | 3 | 1 | 7 | 1 |
| test_national_chapter_access.py | 2 | 2 | 0 | 0 | 0 |
| test_performance_security_fixes.py | 13 | 1 | 0 | 6 | 6 |
| test_permissions_coverage.py | 45 | 5 | 35 | 4 | 1 |
| test_permissions_doc_checks_coverage.py | 31 | 12 | 11 | 6 | 2 |
| test_project_permissions_coverage.py | 27 | 12 | 10 | 5 | 0 |
| test_project_permissions.py | 15 | 8 | 1 | 4 | 2 |
| test_public_api_coverage_additions.py | 3 | 1 | 0 | 2 | 0 |
| test_role_name_fixes.py | 5 | 3 | 0 | 2 | 0 |
| test_role_profile_integration.py | 12 | 3 | 0 | 0 | 9 |
| test_secure_operations_coverage.py | 30 | 8 | 6 | 13 | 3 |
| test_secure_operations_security_audit.py | 14 | 2 | 2 | 6 | 4 |
| test_security_framework_comprehensive.py | 28 | 1 | 0 | 3 | 24 |
| test_security_modules.py | 21 | 5 | 2 | 4 | 10 |
| test_security_monitoring_coverage.py | 39 | 7 | 1 | 15 | 16 |
| test_security_penetration.py | 12 | 0 | 4 | 7 | 1 |
| test_security_profile_isolation.py | 2 | 0 | 0 | 2 | 0 |
| test_security_setup.py | 33 | 9 | 5 | 16 | 3 |
| test_security_vulnerability_regression.py | 8 | 1 | 1 | 1 | 5 |
| test_self_service_doc_method_regression.py | 6 | 3 | 3 | 0 | 0 |
| test_self_service_operations.py | 18 | 7 | 3 | 6 | 2 |
| test_toctou.py | 10 | 2 | 0 | 8 | 0 |
| **DOMAIN TOTALS** | **897** | **316** | **161** | **281** | **139** |

## Observations

- **Negative-path coverage is overwhelmingly genuine, not mocked-away.** Across 38 files, only a
  handful of tests stub out the very check they claim to exercise. The recurring pattern in the strong
  suites is: real Users + real Role Profiles + `self.as_user(...)` / `set_user_context`, with mocking
  restricted to *collaborators* (role RESOLUTION via `get_user_role_profiles`, audit-logger doubles,
  `frappe.get_single` config) while the authorization DECISION and throw logic run live. Genuine
  denials/throws (`VPermissionError`, `PermissionError`, `RateLimitExceededError`, `BrokenLinkError`,
  `"1=0"` scoping) dominate the 161 Unhappy + 281 Edge = **442 negative/boundary methods (49%)**.

- **Strongest files (highest-value genuine negative coverage):** the permission suites
  `test_permissions_coverage.py` (35 real execution-scoped denials against live DB), `test_project_
  permissions_coverage.py` (docstring notes replacing a body with `pass` would fail), and the
  self-service trio `test_self_service_operations.py` / `test_self_service_doc_method_regression.py`
  (clean owner-allow/intruder-deny pairs with asserted error text, covering Audit #3/#4/#5 field-
  smuggling & JSON-embedded-target bypasses). `test_client_ip_coverage.py` (26/26 EDGE) and
  `test_toctou.py` are genuine anti-spoofing / tampering suites using real Werkzeug requests.

- **Weakest files (nominal security, little real boundary exercise):** `test_security_penetration.py`
  is the biggest disappointment for a "penetration" file — 8 of 12 tests are `@unittest.skip`'d
  (Mollie drift), the remainder swallow assertions in `try/except: pass` or are tautological
  (`test_session_security` calls `frappe.generate_hash()` directly), and two of the *skipped* tests
  literally patch away their own check (`_check_replay`, `frappe.throw`). `test_security_framework_
  comprehensive.py` (24/28 OTHER) and `test_role_profile_integration.py` (9/12 OTHER) are almost
  entirely enum/definition/config-dict assertions. `test_performance_security_fixes.py` has 6 OTHER
  that `print("acceptable")` inside blanket try/except and cannot fail.

- **Specific mocked-away / no-op flags (true OTHER):** `test_secure_operations_security_audit.py::
  test_integrity_verification_called_after_bypass` patches `verify_document_integrity` to `[]` and
  only asserts it was *called* (wiring, not the integrity check). `test_api_security_decorators.py` &
  `test_api_security_framework.py` carry ~5 rate-limit tests that are effectively tautological because
  `in_test` skips enforcement (assert only `successes>0`, or accept BOTH success and CSRF-fail).
  `test_security_setup.py::test_csrf_validation_with_valid_token` self-`skipTest`s. Several `*_runs`
  monitoring detectors in `test_security_monitoring_coverage.py` (16 OTHER) likely iterate empty
  result sets on a clean DB.

- **Base classes:** the suite is not uniform. Majority use `VereningingenTestCase` (audit/authorization/
  csrf/ip/enhanced-validation/monitoring/setup/penetration-isolation) or `EnhancedTestCase`
  (decorators, permissions, secure-operations, self-service, toctou, cor-rate-limiting). A minority use
  Frappe's raw `FrappeTestCase` (`test_link_sanitizer.py`, `test_secure_operations_security_audit.py`,
  `test_security_modules.py`). Self-service files layer `PortalSelfServiceTestMixin`. Rate-limit/CSRF
  files that touch Redis/threads run against real infra.

- **CSRF harness caveat handled correctly:** `test_csrf_ratelimit_cache_coverage.py` mocks
  `CSRFProtection.validate_request`→True in `setUp`, but every real-validation test first calls
  `_disable_harness_csrf_mock()`, so the CSRF reject coverage (missing-token, Audit #9 session-token
  self-compare) is genuine, not defeated by the harness.

## Missing / low-signal files (no zero-method files found; all 38 have ≥2 methods)

- Smallest real suites: `test_national_chapter_access.py` (2, both HAPPY grant-expansion),
  `test_security_profile_isolation.py` (2, both EDGE shared-mutable-state guards),
  `test_public_api_coverage_additions.py` (3), `test_role_name_fixes.py` (5).
- `test_security_penetration.py`: 8/12 methods skipped at runtime — nominal Total 12, effective
  active coverage ≈ 4, of which most assertions are swallowed. Treat its Unhappy=4 as optimistic.
- `test_integrated_security_payment_system.py`: 1 method `@unittest.skip`'d; its rate-limit test never
  asserts a block. `test_toctou.py`: 2/10 skipped (deleted `bank_details_confirm` module).
- No file was entirely empty or import-only; every file contains at least one executable assertion.
