# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Test helper: assign role profiles to scratch users for security-gated endpoints.

After the audit #2 Rule-5 cap, HIGH/CRITICAL API access is granted only through an
assigned role PROFILE (Rule 4 in authorization_policy); a bare role -- even System
Manager -- caps at MEDIUM. Tests that create a user with roles but no profile are
therefore denied HIGH/CRITICAL endpoints. Assigning the profile whose name matches
the role restores the tier the role name implies, while low-tier roles (e.g.
"Verenigingen Member") map to a LOW/MEDIUM profile and stay correctly denied -- so
permission-tier and denial assertions are preserved.
"""

import frappe


def grant_matching_role_profiles(email, roles):
    """Assign the Role Profile(s) whose name matches the given role name(s).

    Args:
        email: User to assign profiles to.
        roles: A role name (str) or iterable of role names. Names without a
            same-named Role Profile are ignored.

    Caveat: saving a User with role_profiles triggers Frappe's
    populate_role_profile_roles, which RESYNCS user.roles to the union of the
    assigned profiles' roles. Any bare role the caller set that has no matching
    Role Profile (e.g. "HR Manager", "Accounts Manager") is dropped unless it is
    already contained in one of the matched profiles. Grant profiles whose roles
    cover everything the test needs.
    """
    names = [roles] if isinstance(roles, str) else list(roles)
    profiles = [r for r in names if frappe.db.exists("Role Profile", r)]
    if not profiles:
        return

    original_user = frappe.session.user
    frappe.set_user("Administrator")
    try:
        user = frappe.get_doc("User", email)
        user.set("role_profiles", [{"role_profile": p} for p in profiles])
        user.role_profile_name = profiles[0]
        user.save(ignore_permissions=True)
    finally:
        frappe.set_user(original_user)

    try:
        from verenigingen.utils.security.api_security_framework import get_security_framework

        get_security_framework().auth_engine.invalidate_user_cache(email)
    except Exception:
        # Cache invalidation is best-effort; the 5-minute TTL bounds staleness.
        pass
