# Security Wrappers — RETIRED (2026-07-30)

`verenigingen/utils/security_wrappers.py`, its unit tests, and
`scripts/security/security_audit_script.py` were **deleted on 2026-07-30**. This document
previously described them at length. It is kept, rewritten, so the reasoning survives and the
phantom vulnerability is not re-derived from git history.

## The premise was false

The module's stated purpose was to prevent "the systemic vulnerability where
`frappe.get_roles(None)` returns all system roles." **That behavior does not exist.** From
`frappe/permissions.py`:

```python
def get_roles(user=None, with_standard=True):
    if not user:
        user = frappe.session.user
    if user == "Guest" or not user:
        return [GUEST_ROLE]

    def get():
        if user == "Administrator":
            return frappe.get_all("Role", pluck="name")  # all roles
        ...
```

A falsy user resolves to `["Guest"]`. The all-roles branch is gated on
`user == "Administrator"`, where returning every role is correct rather than an escalation.

Measured behavior for the inputs the wrapper rejected:

| input | `frappe.get_roles` | retired `safe_get_roles` |
|---|---|---|
| `None`, `""` | `["Guest"]` | `[]` |
| `"None"`, `"null"`, junk string | `["All", "Guest"]` | `[]` |
| `"Administrator"` | all roles (correct) | all roles |

The framework already fails closed on every malformed input. The wrapper returned a slightly
stricter empty list and nothing else of security value.

## Why it was retired rather than expanded

- **No security gain**, per the table above.
- **Effectively unadopted**: one importing module (`auth_hooks.py`, three call sites) against
  ~229 direct `frappe.get_roles()` calls elsewhere. Each of those three sites already
  pre-validated its user, so the wrapper's validation was redundant at every real call site.
- **Expanding it would have been costly**: it logged an INFO audit line on every call by a
  user holding System Manager / Administrator / Verenigingen Administrator. Role lookups
  happen on essentially every permission check — Frappe memoises them in
  `frappe.local.role_permissions` precisely because they are hot — so wrapping all 229 sites
  would have meant an audit log line per permission check for every admin user, plus a
  behavior change (`[]` instead of `["All", "Guest"]`) at each one.

The deleted audit script compounded this: it classified `frappe.get_roles(None)` as CRITICAL
and could auto-generate a migration rewriting every call site to the wrapper. Its
`bench execute verenigingen.utils.security_audit_script...` invocations were already broken,
since the script had been moved to `scripts/` and out of the importable package.

## What replaced it

`auth_hooks.py` calls `frappe.get_roles(user)` directly, after the user validation it already
performed. Behavior is unchanged: `has_member_role`, `has_volunteer_role` and
`has_system_access` use the result only to test membership of specific named roles
(`Verenigingen Member`, `Volunteer`, `System Manager`, …), and none of those can appear in
`["All", "Guest"]`.

Coverage lives in `verenigingen/tests/integration/test_security_framework_integration.py`,
which now tests the hooks rather than the wrapper: that they fail closed on malformed users,
that `on_session_creation` never raises, and that a nonexistent user resolves to no
privileged role.

## Still current

The real authorization framework is `verenigingen/utils/security/api_security_framework.py`
(`@critical_api`, `@self_service_api`, SecurityLevel, Critical Operation Rules). It is
unrelated to the retired wrappers and is documented separately. Note that it authorizes on
role **profiles**, not roles.

## Known leftover

`verenigingen/fixtures/critical_operation_rule.json` contains a row whose `business_context`
references `verenigingen.utils.security_audit_script`. It was already orphaned before this
change (the script was not importable at that path) and is harmless; it was left alone rather
than hand-editing a 23k-line fixture.
