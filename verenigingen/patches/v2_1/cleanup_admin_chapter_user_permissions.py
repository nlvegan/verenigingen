"""Remove redundant Chapter User Permissions for admin/staff users.

Background:
  `_grant_chapter_member_permissions` (events/subscribers/chapter_subscribers.py)
  used to add a `User Permission(allow=Chapter, for_value=<chapter>)` row for every
  member who joined a chapter, including users with admin role profiles. With the
  default `apply_to_all_doctypes=1`, that row cascades through every Link-to-Chapter
  on every doctype, and Frappe hardcodes `create=0` for users scoped by User
  Permissions (frappe/permissions.py:256) — blocking admins from creating new
  chapters or opening settings docs that reference chapters outside their personal
  membership.

  The grant is also redundant for admins: `verenigingen/permissions.py`
  `get_*_permission_query` functions already return "" (no filter) for admin roles.

This patch deletes those rows.
"""

import frappe


def execute():
    from verenigingen.utils.constants import Roles

    rows = frappe.get_all(
        "User Permission",
        filters={"allow": "Chapter"},
        fields=["name", "user"],
    )

    deleted = 0
    for row in rows:
        if not row.user:
            continue
        roles = frappe.get_roles(row.user)
        if any(r in Roles.ADMIN_ROLES for r in roles):
            frappe.delete_doc("User Permission", row.name, ignore_permissions=True)
            deleted += 1

    if deleted:
        frappe.db.commit()
        frappe.logger().info(
            f"cleanup_admin_chapter_user_permissions: removed {deleted} redundant Chapter User Permission rows for admin/staff users"
        )
