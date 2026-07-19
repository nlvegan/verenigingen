# Issue #162 — Re-arm the auth/RBAC test surface in CI

**Date:** 2026-07-20
**Issue:** #162 — "Test harness: HTTP/auth integration tests can't authenticate in CI (~30 tests silently failing)"
**Status:** Design approved, pending spec review

## Problem

30 integration/security tests across 6 files fail in CI and are absorbed by the
`known_test_failures.txt` baseline, leaving the authentication/permission/RBAC
surface effectively uncovered in CI — the layer where a regression is most
dangerous.

The issue framed this as "tests can't authenticate in CI." **That framing is
mostly wrong.** Reproducing the failures on `test_site_1` shows the tests *do*
authenticate (e.g. as `admin.api@test.verenigingen.invalid` with `System
Manager` + `Verenigingen Administrator`). They fail because of the real root
cause below.

## Root cause (confirmed)

The app's `APISecurityFramework`
(`verenigingen/utils/security/api_security_framework.py`) authorizes on Frappe
**Role Profiles**, not roles, via `ROLE_PROFILE_SECURITY_MAPPING`
(`verenigingen/utils/security/authorization_policy.py:60`). A user's granted
security levels come from `get_user_role_profiles()`
(`authorization_engine.py:100`), which reads the User's `role_profile_name`
link and `role_profiles` child table.

The test factory (`enhanced_test_factory.py`) assigns **roles but never a Role
Profile**. So every test user resolves to `profiles=[]` and is denied at
HIGH/CRITICAL:

```
user_profiles = []
AuthResult(granted=False, rule_matched='rule_7_deny',
           reason='No authorization rule grants critical access')
PermissionError: Access denied. Required: critical. Your profiles: none, roles: ...
```

**Spike verification** (throwaway, no committed change):

```
BEFORE (roles only):         profiles=[]                              grants_CRITICAL=False
AFTER  (Role Profile added): profiles=['Verenigingen Administrator']  grants_CRITICAL=True
```

Two supporting facts:
- All 11 Role Profile records referenced by the mapping **already exist** in the
  test DB — the fix only needs to *assign* them, not create them.
- Verenigingen **role names map 1:1 to Role-Profile names** (`Verenigingen
  Administrator`, `Verenigingen Staff`, `Verenigingen Member`, `Verenigingen
  Volunteer`, …). Deriving a user's profile from their roles is therefore
  automatically RBAC-correct: a low-tier user gets only a low-tier profile and
  is still correctly denied CRITICAL. This preserves the deny-path assertions
  the RBAC tests rely on.

## Test classification (30 failing tests)

| Group | Count | Files | Cause |
|---|---|---|---|
| **B — in-process `set_user`** | 11 | `test_sepa_mandate_authentication_security` (5), `test_authentication_flows` (3), `test_api_authentication_decorators_integration` (3) | No Role Profile |
| **C — in-process, other** | 11 | `test_member_doctype_phase3_security` (5), `test_integrated_security_payment_system` (6) | No Role Profile |
| **A — real HTTP (`requests`)** | 8 | `test_suspension_api_http_integration` (8 of its 11 methods) | No web server in CI + no Role Profile |

CI runs `bench run-parallel-tests` only — **no web server** is started
(`.github/workflows/_base-server-tests.yml` deliberately avoids a backgrounded
`bench start`, see the redis-teardown comment at lines 77–82). Class A tests
skip locally (their `_http_endpoint_reachable` guard) but the guard does not
fire in CI (the site URL is reachable there), so they error on a dead login and
land in the baseline.

Two distinct user-creation helpers are in play across these files:
`create_user_with_roles` (Class B, `member_doctype_phase3`) and
`create_test_user` (`integrated_security`). Both drive users through an
`as_user()` context. The fix must reach both helpers.

The 8 failing Class A methods:
`test_bulk_suspension_http_real_batch_processing`,
`test_suspend_member_http_real_integration`,
`test_suspension_error_handling_real_validation`,
`test_suspension_permissions_http_real_rbac`,
`test_suspension_preview_http_real_analysis`,
`test_suspension_status_http_real_queries`,
`test_unsuspend_member_http_real_workflow`,
`test_user_suspension_integration_real_workflow`.

The 3 **non-failing**, genuinely HTTP-only methods to preserve:
`test_csrf_protection_real_validation`,
`test_authentication_required_real_validation`,
`test_api_security_decorators_real_validation`.

## Design

> **Revised after SWE review (2026-07-20).** The review found an existing,
> already-merged helper that does exactly the proposed Part-1 work, corrected
> the `OperationResult` return-type assumption, distinguished the two denial
> mechanisms, and flagged the stale branch/baseline. Changes folded in below;
> this supersedes the earlier "opt-in factory flag" decision (the mechanism
> already exists, so no factory change is needed).

### Part 1 — Assign Role Profiles via the existing helper (fixes B + C)

Reuse the existing, precedented helper
`verenigingen/tests/fixtures/role_profile_helper.py::grant_matching_role_profiles(email, roles)`
(merged `3b8569e0`, already used in 9 files). It assigns every Frappe Role
Profile whose name matches one of the user's roles, writing **both** the v16
`role_profiles` child table and the legacy `role_profile_name` link, then
invalidates the auth cache. Its docstring documents the exact RBAC-preservation
property we rely on (low-tier roles map to low-tier profiles and stay correctly
denied).

Call it in each affected file's `setUp`, immediately after each user is
created, passing that user's `roles` — mirroring
`verenigingen/tests/sepa/test_sepa_security_comprehensive.py:288-290`. This
touches only the 5 in-process files (+ the new suspension file), never the
factory, so the ~hundreds of other factory callers are untouched by
construction.

Files creating users via `create_test_user_with_roles` (thin wrapper →
`create_user_with_roles`): `test_sepa_mandate_authentication_security`,
`test_authentication_flows`, `test_api_authentication_decorators_integration`,
`test_member_doctype_phase3_security`. `test_integrated_security_payment_system`
uses `create_test_user`. No file creates users by any other path — the helper
call reaches every failing user context.

### Part 2 — Convert the 8 HTTP suspension tests to in-process (Class A)

**Decision: split into a new file.** Create
`verenigingen/tests/integration/test_suspension_api_integration.py` holding the
8 converted tests as in-process calls. Users created via the factory + Part 1
helper.

**Return-type (corrected by review):** every suspension endpoint is wrapped by
`api_security_framework` (`critical_api`/`high_security_api`/…), whose success
path returns `result.to_dict(scrub_sensitive=True)` — a **plain dict**, even
in-process. So assert on the dict, not an object:

```python
with self.as_user(self.admin_user.email):
    result = suspension_api.suspend_member(member_name=m, suspension_reason="…")
self.assertTrue(result["success"])          # dict, NOT result.success
```

**Two distinct denial mechanisms (corrected by review):**
- **Security-level denial** (wrong Role Profile tier) — the wrapper's
  `validate_authentication` **raises** `frappe.PermissionError`/`VPermissionError`
  before the function body runs. Test with `assertRaises`:
  ```python
  low_user = self.create_test_user_with_roles(roles=["Verenigingen Member"])  # real low tier, not "Guest"
  grant_matching_role_profiles(low_user.email, ["Verenigingen Member"])
  with self.as_user(low_user.email), self.assertRaises(frappe.PermissionError):
      suspension_api.suspend_member(member_name=m, suspension_reason="…")
  ```
- **In-body business denial** (`can_terminate_member`, `suspension_api.py:64-71`)
  — returns `OperationResult.fail(..., error_code="PERMISSION_DENIED")`, i.e. a
  dict with `success=False`. Assert on `result["success"] is False` /
  `result["error"]`.

**Real assertions (review finding):** the current 8 HTTP methods are
near-tautological (`print("✅ …")` with no `else`/`self.fail`;
`test_suspension_permissions_http_real_rbac` has no failure path at all). The
converted tests MUST assert real outcomes (`assertTrue(result["success"])`,
`assertRaises`, state checks like member `status`/`docstatus`), not carry over
print-and-pass.

**Recalibrate `assertQueryCount`:** the HTTP baselines (400–500) assume network
round-trips; in-process calls issue far fewer queries. Re-measure and set tight
realistic caps, or drop the wrapper where it adds nothing.

**Delete the emptied class:** the 8 tests live in class
`TestSuspensionAPIHTTPIntegration`; the 3 HTTP-only tests live in a *separate*
class `TestSuspensionAPISecurityHTTPIntegration` (own `setUp`, doesn't call
`_authenticate_session`). After moving the 8, `TestSuspensionAPIHTTPIntegration`
has zero `test_*` methods → **delete the class** (and its now-unused
`setUp`/`_authenticate_session`/`_get_csrf_token`). Keep
`TestSuspensionAPISecurityHTTPIntegration` (the 3 HTTP-only tests) under its skip
guard — honest "HTTP/CSRF layer not covered in CI." Removing that class also
removes the dead hardcoded-credential `_authenticate_session` in this file (the
other copy in `test_payment_processing_http_integration.py` is untouched / out
of scope).

### Part 3 — Re-arm the gate

**Prerequisite (review finding): branch must be current with `origin/develop`
before editing the baseline** — the branch originally forked pre-#163 and
carried the stale 2208-line file. Done: rebased onto `origin/develop`
(`0ea6141f`), baseline now the fresh 62-line file.

Remove the 30 now-passing entries from
`verenigingen/tests/known_test_failures.txt`. The Class A entries are keyed to
the OLD file/class
(`...test_suspension_api_http_integration.TestSuspensionAPIHTTPIntegration...`);
because the 8 move to a new file/class, their old baseline ids simply disappear
(the methods no longer exist there) and the new in-process ids must **not** be
added to the baseline (they pass). Prune the 22 Class B/C ids explicitly.

## Verification

1. Run all 6 (now 7) modules on `test_site_1`; confirm 30 targeted tests green.
2. Regression spot-check: run a sample of neighboring integration/security tests
   that use `create_test_user` / `create_user_with_roles` **without** the flag,
   confirming default behavior is unchanged (opt-in flag proves inert).
3. Confirm `check_new_test_failures.py` reports 0 new failures against the pruned
   baseline for the touched shards.
4. Branch + push; CI green across all 12 shards.

## Out of scope

- Removing the dead hardcoded credentials (`fjdh+1@disroot.org`, the
  `5089a44ef7c0239`/`30acace8e1851f1` API key/secret) — the backing site is
  deleted; no live exposure. Left as-is per session decision.
- Running a real web server in CI (rejected by existing infra decision).
- HTTP/CSRF-layer coverage in CI (the 3 preserved HTTP-only tests remain
  skip-guarded).

## Files touched (anticipated)

- `verenigingen/tests/fixtures/enhanced_test_factory.py` — new helper + flag on
  `create_test_user`, `create_user_with_roles`.
- `verenigingen/tests/integration/test_suspension_api_integration.py` — **new**,
  8 in-process tests.
- `verenigingen/tests/integration/test_suspension_api_http_integration.py` —
  remove 8 methods, keep 3 HTTP-only.
- `verenigingen/tests/integration/test_sepa_mandate_authentication_security.py`,
  `test_authentication_flows.py`,
  `test_api_authentication_decorators_integration.py`,
  `test_member_doctype_phase3_security.py`,
  `verenigingen/tests/security/test_integrated_security_payment_system.py` —
  pass `with_role_profiles=True` at user creation.
- `verenigingen/tests/known_test_failures.txt` — prune 30 entries.
