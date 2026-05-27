"""Drop orphan 'Verenigingen Volunteer' and 'Volunteer Team' DocType rows + data tables.

Defensive cleanup for sites that may have orphan `tabDocType` rows pointing
to modules that no longer exist on disk. Triggers a `ModuleNotFoundError`
on any subsequent `frappe.get_doc("DocType", ...)` / `frappe.reload_doctype(...)`
/ meta-cache load.

This patch is BEST-EFFORT defense-in-depth, not driven by a verified failure
on a specific CI shard — the rows may not exist on any current site. The
canonical doctype names today are `Volunteer` and `Team`. On sites where
the orphan rows DO exist, this patch:

1. Drops the `tabDocType` row (and the side-effects `frappe.delete_doc`
   handles — custom fields, global search, etc.).
2. Drops the underlying data table independently — `delete_doc` does NOT
   drop the data table (`frappe/model/delete_doc.py:246-266` only removes
   the metadata). PR #84 (`v2_2.drop_volunteer_expense_archived_doctype`)
   handles both pieces in separate loops for the same reason.

Idempotent — safe to re-run. Mirrors the
`v2_2.drop_volunteer_expense_archived_doctype` pattern (PR #84).
"""

import frappe

_ORPHAN_DOCTYPES = ("Verenigingen Volunteer", "Volunteer Team")
_ORPHAN_TABLES = ("tabVerenigingen Volunteer", "tabVolunteer Team")


def execute():
    # Step 1: drop DocType rows. If the controller module is missing,
    # `frappe.get_doc("DocType", ...)` (called inside `delete_doc`) raises
    # ModuleNotFoundError. We catch and log so step 2 can still proceed.
    for doctype_name in _ORPHAN_DOCTYPES:
        if not frappe.db.exists("DocType", doctype_name):
            continue
        try:
            frappe.delete_doc("DocType", doctype_name, force=True, ignore_missing=True)
            print(f"Dropped orphan DocType row: {doctype_name}")
        except Exception as exc:
            frappe.logger().warning(f"Could not drop orphan DocType row {doctype_name}: {exc}")

    # Step 2: drop data tables independently. Frappe's `delete_doc` does not
    # drop these (delete_from_table only removes metadata rows), and on
    # corrupt-meta sites step 1 may have silently failed via the except
    # branch above. This is the parallel piece that mirrors PR #84.
    for table_name in _ORPHAN_TABLES:
        existing = frappe.db.sql("SHOW TABLES LIKE %s", (table_name,))
        if not existing:
            continue
        try:
            frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `{table_name}`")
            print(f"Dropped orphan data table: {table_name}")
        except Exception as exc:
            frappe.logger().warning(f"Could not drop orphan data table {table_name}: {exc}")

    frappe.db.commit()
