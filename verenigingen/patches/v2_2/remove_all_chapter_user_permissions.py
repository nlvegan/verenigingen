"""Remove all Chapter User Permission rows.

Background:
  Chapter-scoped row-level security is enforced by per-doctype
  permission_query_conditions (verenigingen/permissions.py
  get_volunteer_permission_query, get_member_permission_query, etc., and
  chapter_permission_service.get_permission_query_conditions). Those query
  functions join Chapter Member / Chapter Board Member directly to filter
  rows for non-admin users — they don't consult User Permission rows.

  The legacy `_grant_chapter_member_permissions` event handler used to add
  `User Permission(allow=Chapter, for_value=<chapter>)` rows for non-admin
  members on chapter join. With Frappe's default `apply_to_all_doctypes=1`,
  those rows cascaded through every Link-to-Chapter on every doctype —
  including admin-managed doctypes (Organization Document, Membership Goal,
  Verenigingen Settings, etc.) where chapter-based scoping isn't desired —
  and they're redundant with the per-doctype hooks for the cases that DO
  need scoping. They also tripped Frappe's hardcoded create=0 for users
  scoped by any User Permission (frappe/permissions.py:256).

  The v2_1 cleanup_admin_chapter_user_permissions patch removed these rows
  for users with admin/staff roles. This patch removes them for all users.
  The chapter_subscribers handlers no longer create them, and a defensive
  cleanup runs on every User save to catch any that get reintroduced.
"""

import frappe


def execute():
    rows = frappe.get_all("User Permission", filters={"allow": "Chapter"}, pluck="name")

    for name in rows:
        frappe.delete_doc("User Permission", name, ignore_permissions=True)

    if rows:
        frappe.db.commit()
        frappe.logger().info(
            f"remove_all_chapter_user_permissions: removed {len(rows)} Chapter User Permission rows"
        )
