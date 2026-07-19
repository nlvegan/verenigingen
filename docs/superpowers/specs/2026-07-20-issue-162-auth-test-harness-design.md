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

### Part 1 — Factory support for Role-Profile assignment (fixes B + C)

Add a shared helper in `verenigingen/tests/fixtures/enhanced_test_factory.py`
that, given a created user and their roles, assigns every Frappe **Role
Profile** whose name matches one of the user's roles *and* appears in
`ROLE_PROFILE_SECURITY_MAPPING`. It writes **both** the v16 `role_profiles`
child table and the legacy `role_profile_name` link (the engine reads both) and
invalidates the auth cache for the user
(`get_authorization_engine().invalidate_user_cache(email)`).

Wire it into both `create_test_user` and `create_user_with_roles` behind an
**opt-in flag** `with_role_profiles=False` (default off). **Decision: opt-in,
not default-on** — the helpers have hundreds of callers; opt-in contains risk to
exactly the 6 files we intend to change and keeps each test explicit about the
privilege it grants. The 6 affected files pass `with_role_profiles=True`.

Cache note: users are created fresh in `setUp` before any auth call, so the
versioned profile cache is cold; explicit invalidation is belt-and-suspenders
for tests that create a user and immediately assert.

### Part 2 — Convert the 8 HTTP suspension tests to in-process (Class A)

**Decision: split into a new file.** Create
`verenigingen/tests/integration/test_suspension_api_integration.py` holding the
8 converted tests as in-process calls:

```python
with self.as_user(self.admin_user.email):
    result = suspension_api.suspend_member(member_name=..., suspension_reason=...)
self.assertTrue(result.success)   # OperationResult
```

Admin/limited users created via the Part 1 factory (`with_role_profiles=True`).
RBAC assertions (`test_suspension_permissions_http_real_rbac`) use an
admin-profile user (allowed) and a low-tier user (denied), which the 1:1
role→profile derivation makes correct.

Leave the 3 HTTP-only tests in the existing
`test_suspension_api_http_integration.py` under their current skip guard —
honest "HTTP/CSRF layer not covered in CI" rather than faking it in-process.
Both files can share a small setUp mixin if the scaffolding overlap is
meaningful; otherwise duplicate the minimal member/user setup.

Once the 8 methods are removed from the HTTP file, its `_authenticate_session`
default-credential helper is used only by whatever of the 3 remaining HTTP tests
still call it — out of scope to remove (credentials are dead deleted-site
artifacts, see session notes), but note it in the plan.

### Part 3 — Re-arm the gate

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
