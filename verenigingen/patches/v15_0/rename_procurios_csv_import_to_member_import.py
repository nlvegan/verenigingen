# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.rename_doc import rename_doc


def execute():
    """Rename DocType Procurios CSV Import -> Member Import (table + links).

    MUST run in [pre_model_sync] (see patches.txt), not [post_model_sync].
    `frappe.model.sync.sync_all()` runs between the two patch phases and
    creates a fresh, empty "Member Import" DocType from the renamed JSON
    the first time it sees it. If this patch ran after that (post_model_sync),
    `not frappe.db.exists("DocType", "Member Import")` would already be False,
    the rename would silently no-op, and the framework's own
    `remove_orphan_doctypes()` step would later delete the old "Procurios CSV
    Import" DocType metadata — dropping the link to any existing data without
    migrating it (the underlying table is left behind, orphaned and
    inaccessible). Running pre_model_sync lets `rename_doc` execute while the
    old DocType record is still the only one in the database, so schema sync
    then treats "Member Import" as an existing DocType to update in place.
    """
    if frappe.db.exists("DocType", "Procurios CSV Import") and not frappe.db.exists(
        "DocType", "Member Import"
    ):
        rename_doc("DocType", "Procurios CSV Import", "Member Import", force=True)
        frappe.clear_cache(doctype="Member Import")
