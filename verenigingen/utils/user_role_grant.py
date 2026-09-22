"""
User Role Grant Utilities

Shared helper for the class of defects tracked as #1195: a plain
``user.append("roles", {"role": X}) + user.save()`` is silently defeated
whenever the user carries a Role Profile that does not include ``X``.

``User.validate()`` unconditionally calls ``populate_role_profile_roles()``
(``frappe/core/doctype/user/user.py``), which re-derives ``roles`` from
``role_profiles`` on every save the user's ``role_profiles`` table is
non-empty:

    new_roles = set()
    for role_profile in self.role_profiles:
        ...
        new_roles.update(role.role for role in role_profile.roles)
    self.roles = [r for r in self.roles if r.role in new_roles]   # drops X
    self.append_roles(*new_roles)

That filter runs over ``self.roles`` *after* the append, in the very same
``validate()`` call, so the appended role is stripped before the row is
ever written -- the save "succeeds" and grants nothing.

``verenigingen/services/volunteer/expense_approver_service.py::
ensure_user_has_expense_approver_role`` already worked around this by
verifying the grant persisted and, if not, falling back to a direct
``Has Role`` child-table insert (which bypasses ``User.validate()``
entirely, so the re-derivation never runs). This module extracts that tail
step so every affected call site can reuse it instead of re-solving the
same problem ad hoc (#1195 found five independent copies).

IMPORTANT -- this is NOT a permanent guarantee. A direct ``Has Role``
insert survives the operation that granted it, but a LATER, unrelated
``user.save()`` re-runs ``populate_role_profile_roles()`` and will strip
the role again if the user still carries a Role Profile that doesn't
include it (measured empirically on test_site_4, see #1195's PR and the
follow-up issue it files). Making a role durably survive *any* future save
requires the role to be part of an attached Role Profile -- a data/policy
decision this helper does not make. Use this helper to fix the same-save
defeat; do not treat its success as evidence the role is permanent.
"""

import frappe


def ensure_role_survives_profile_resync(user_email: str, role: str) -> bool:
    """Verify ``role`` actually persisted on ``user_email`` and grant it via
    a direct ``Has Role`` insert if a preceding append + save silently
    dropped it (see module docstring).

    Call this AFTER the normal ``user.append("roles", {"role": role}) +
    user.save()`` -- not instead of it. The normal path is cheaper and
    still the one that fires in the common case (no Role Profile attached,
    or the profile already includes ``role``); this only covers the case
    where ``User.populate_role_profile_roles()`` silently stripped it.

    No permission check by design: this function grants `role`
    unconditionally, via ``ignore_permissions=True``. The caller MUST have
    already authorized the grant (e.g. via its own permission check, or
    because it runs as trusted internal system/business logic reacting to
    a validated event) -- this helper only fixes *persistence*, not
    *authorization*.

    Args:
        user_email: The User whose roles should include ``role``.
        role: The Role that should be present (must already exist as a
            ``Role`` document -- this function does not create roles).

    Returns:
        True once ``role`` is confirmed present in ``Has Role`` for this
        user (whether it was already there or this call granted it).
    """
    if frappe.db.exists("Has Role", {"parent": user_email, "role": role, "parenttype": "User"}):
        return True

    # validator-skip: child-table-direct-insert (intentional - role-profile
    # re-sync workaround; mirrors expense_approver_service.py and
    # permissions.py::assign_chapter_board_role). ignore_permissions is safe
    # here: every caller of this helper is internal system/business logic
    # that has already decided the user should have `role`, not user input.
    frappe.get_doc(
        {
            "doctype": "Has Role",
            "parent": user_email,
            "parenttype": "User",
            "parentfield": "roles",
            "role": role,
        }
    ).insert(ignore_permissions=True)
    frappe.clear_cache(user=user_email)
    # Debug line only, not an audit trail: frappe.logger() defaults to level
    # ERROR (WARNING on a dev server) and this is .info(), so it is not
    # written anywhere in CI or production -- see CLAUDE.md's "Known traps"
    # and verenigingen/utils/service_logger.py's docstring ("do not rely on
    # these for audit trails"). If this grant ever needs a real, queryable
    # audit trail, route it through verenigingen.utils.security.
    # audit_logging.log_security_event instead of adding severity here.
    frappe.logger().info(
        f"Granted {role} role to {user_email} via direct Has Role insert "
        f"(role-profile re-sync stripped the standard append+save) - by: {frappe.session.user}"
    )
    return True
