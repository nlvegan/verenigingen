"""Rename "Email Configuration" DocType to "Verenigingen Email Configuration".

The DocType was renamed for findability so it sits alongside other
"Verenigingen *" Single DocTypes in the global search.

Two cases to handle:

1. Old DocType exists, new doesn't — straight ``frappe.rename_doc`` handles
   both the meta record and the tabSingles rows.

2. Both exist — schema sync from the renamed JSON has already created an
   empty "Verenigingen Email Configuration" DocType before this patch runs.
   We migrate the existing field values and child-table rows from the old
   Single to the new one, then delete the old DocType.
"""

import frappe


def execute():
    old_name = "Email Configuration"
    new_name = "Verenigingen Email Configuration"

    if not frappe.db.exists("DocType", old_name):
        # Already migrated, or fresh install with the new name.
        return

    if not frappe.db.exists("DocType", new_name):
        # Simple rename — covers the case where schema sync runs after this patch.
        frappe.rename_doc("DocType", old_name, new_name, force=True, merge=False)
        frappe.db.commit()
        return

    # Both exist: schema sync created an empty new Single before this patch ran.
    # Move data over, then drop the old DocType.

    # 1. Copy field values from old Single to new (overwriting the empty defaults
    #    that schema sync inserted).
    frappe.db.delete("Singles", {"doctype": new_name})
    frappe.db.sql(
        """
        UPDATE `tabSingles`
        SET doctype = %s
        WHERE doctype = %s
        """,
        (new_name, old_name),
    )

    # The Singles row may carry a stale `name` value that got persisted at some
    # point. For Singles the name is derived from the DocType, so any stored
    # value must match — otherwise frappe.get_single() returns a doc whose
    # `name` is the old DocType, breaking child-table reparenting and links.
    frappe.db.sql(
        """
        UPDATE `tabSingles`
        SET value = %s
        WHERE doctype = %s AND field = 'name'
        """,
        (new_name, new_name),
    )

    # 2. Reparent child-table rows (Email Notification Type) from the old Single
    #    to the new one. Single docs use the DocType name as the parent name.
    frappe.db.sql(
        """
        UPDATE `tabEmail Notification Type`
        SET parent = %s, parenttype = %s
        WHERE parent = %s AND parenttype = %s
        """,
        (new_name, new_name, old_name, old_name),
    )

    # 3. Delete the old DocType meta. The custom fields, property setters, and
    #    permissions are tied to the meta and will go with it.
    frappe.delete_doc("DocType", old_name, force=True, ignore_missing=True)
    frappe.db.commit()
