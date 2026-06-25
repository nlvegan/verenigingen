"""Shared helper for resolving notification recipient emails by Frappe role."""

import frappe


def get_recipients_by_roles(role_names: list[str]) -> list[str]:
    """Return deduplicated, enabled User emails holding any of role_names.

    Queries ``Has Role`` joined to ``tabUser`` for all enabled users whose
    role column matches any of the supplied role names and whose email is
    non-empty.  Returns a sorted list of unique email addresses.

    Args:
        role_names: One or more Frappe role names to match against.

    Returns:
        Sorted list of unique email strings.  Empty list when no matching
        enabled users are found or when *role_names* is empty.
    """
    if not role_names:
        return []

    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.email
        FROM `tabHas Role` hr
        INNER JOIN `tabUser` u ON u.name = hr.parent
        WHERE hr.role IN %(roles)s
          AND u.enabled = 1
          AND u.email != ''
        """,
        {"roles": role_names},
        as_dict=True,
    )

    return sorted({row["email"] for row in rows})
