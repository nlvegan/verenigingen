"""Member email change → User login rename.

When a Member's email changes and a User is linked, rename the User so
the login email stays aligned with the Member record. Uses
``frappe.rename_doc("User", ...)`` so every Link field pointing at the
User (Has Role, User Permission, Contact, Volunteer, Employee, Chapter
Board Member, ToDo, …) is cascaded atomically inside the current
transaction.

Entry point ``sync_user_email_on_member_update`` is registered in
``hooks/doc_events.py`` under Member ``on_update``. It runs after the
generic field_sync_service, which deliberately excludes email from the
Member→User field mapping (User.name IS the email — you can't just write
to it, you have to rename).

Note: Direct DB writes to ``Member.email`` via ``frappe.db.set_value``
bypass doc hooks and therefore bypass this sync. That's a general
footgun in the codebase, not specific to this handler.
"""

import frappe
from frappe import _

_SYNC_FLAG = "syncing_member_user_email"


def sync_user_email_on_member_update(doc, method=None):
    """Rename the linked User when Member.email changes.

    Aborts the Member save (raises ValidationError) when the target email
    already belongs to a different User — silently merging Users would
    corrupt role and permission assignments.
    """
    if frappe.flags.get(_SYNC_FLAG):
        return
    if not doc.has_value_changed("email"):
        return
    if not doc.user:
        return

    new_email = (doc.email or "").strip().lower()
    old_user = (doc.user or "").strip()

    if not new_email:
        frappe.logger().debug(
            f"Member {doc.name}: email cleared, skipping User rename (user={old_user})"
        )
        return

    if old_user.lower() == new_email:
        return

    if not frappe.db.exists("User", old_user):
        frappe.logger().warning(
            f"Member {doc.name}: linked User {old_user} no longer exists, "
            f"clearing stale link before email change to {new_email}"
        )
        doc.db_set("user", None, update_modified=False)
        return

    if frappe.db.exists("User", new_email):
        frappe.throw(
            _(
                "Cannot change Member email to {0}: a different User account already uses "
                "that email. Resolve the conflicting User first (delete or re-link), then retry."
            ).format(new_email),
            title=_("Email Conflict with Existing User"),
        )

    try:
        frappe.flags[_SYNC_FLAG] = True
        from frappe.model.rename_doc import rename_doc

        rename_doc("User", old_user, new_email, merge=False, ignore_permissions=True)
        # Keep Member.user aligned with the renamed User; also normalize
        # Member.email so both fields agree on casing with User.name.
        doc.db_set("user", new_email, update_modified=False)
        if doc.email != new_email:
            doc.db_set("email", new_email, update_modified=False)
        frappe.logger().info(
            f"SECURITY AUDIT: Renamed User {old_user} -> {new_email} "
            f"triggered by Member {doc.name} email change (session user: {frappe.session.user})"
        )
    finally:
        frappe.flags[_SYNC_FLAG] = False
