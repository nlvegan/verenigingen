"""Drop archived 'Volunteer Expense' and 'Member Volunteer Expenses' DocTypes.

Commit `1a8e5fa2` ("refactor: archive Volunteer Expense DocType") moved the
JSON, controller, and tests for both DocTypes to `archived/volunteer_expense/`,
replacing the flow with native ERPNext `Expense Claim`. Sites that ran the
archive refactor migration may still have:

1. Orphaned `tabDocType` rows pointing to module paths whose Python files
   no longer exist. Any subsequent `frappe.get_doc("DocType", "Volunteer Expense")`
   call (e.g. via `chapter_board_permissions.py:157` after the
   `frappe.db.exists` guard returns True) triggers
   `load_doctype_module` → `import verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense`
   → ModuleNotFoundError.

2. The underlying `tabVolunteer Expense` / `tabMember Volunteer Expenses`
   data tables. Frappe leaves these in place when a DocType is deleted via
   the framework; they have no controller, but their presence can confuse
   migrations and meta-queries.

This patch removes both, idempotently. Safe to re-run.

CI shard 1 (PR #79 run 26363365112): 16 occurrences of
`No module named 'frappe.core.doctype.volunteer_expense'`.
"""

import frappe

_ORPHAN_DOCTYPES = ("Volunteer Expense", "Member Volunteer Expenses")
_ORPHAN_TABLES = ("tabVolunteer Expense", "tabMember Volunteer Expenses")


def execute():
    for doctype_name in _ORPHAN_DOCTYPES:
        if frappe.db.exists("DocType", doctype_name):
            try:
                frappe.delete_doc("DocType", doctype_name, force=True, ignore_missing=True)
                print(f"✅ Dropped orphan DocType: {doctype_name}")
            except Exception as exc:
                frappe.logger().warning(f"Could not drop orphan DocType {doctype_name}: {exc}")

    for table_name in _ORPHAN_TABLES:
        existing = frappe.db.sql("SHOW TABLES LIKE %s", (table_name,))
        if existing:
            try:
                frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `{table_name}`")
                print(f"✅ Dropped orphan data table: {table_name}")
            except Exception as exc:
                frappe.logger().warning(f"Could not drop orphan data table {table_name}: {exc}")

    frappe.db.commit()
