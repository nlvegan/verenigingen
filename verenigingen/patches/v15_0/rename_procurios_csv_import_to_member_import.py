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

    _drop_stale_naming_series_property_setters()


def _drop_stale_naming_series_property_setters():
    """Remove the old PROC-IMP- naming_series Property Setters, if present.

    The original "Procurios CSV Import" DocType carried auto-created Property
    Setters overriding the naming_series `options`/`default` with
    `PROC-IMP-.YYYY.-.####.`. `rename_doc` re-points these at "Member Import"
    but keeps the stale value, so the merged meta keeps serving PROC-IMP- and
    the JSON's new `MEM-IMP-.YYYY.-.####.` never takes effect (new records
    would keep getting PROC-IMP- names). Deleting the stale Property Setters
    lets the synced DocField options/default apply. Idempotent: runs whether or
    not the rename happened this pass, and only removes PROC-IMP- values so any
    other naming customization is left untouched.
    """
    stale = frappe.get_all(
        "Property Setter",
        filters={
            "doc_type": "Member Import",
            "field_name": "naming_series",
            "property": ["in", ["options", "default"]],
            "value": ["like", "PROC-IMP-%"],
        },
        pluck="name",
    )
    if not stale:
        return
    # Direct row delete rather than frappe.delete_doc: a Property Setter has no
    # dynamic links to clean up, and delete_doc enqueues a background job
    # (delete_dynamic_links) that throws QueueOverloaded on a busy site and
    # would make this patch fail mid-migrate. A row delete is sufficient.
    frappe.db.delete("Property Setter", {"name": ["in", stale]})
    frappe.clear_cache(doctype="Member Import")
