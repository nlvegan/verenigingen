"""Drop orphan 'Verenigingen Volunteer' and 'Volunteer Team' DocType rows.

Older sites still have `tabDocType` rows for two renamed DocTypes:

- `Verenigingen Volunteer` was renamed to `Volunteer` (current canonical name).
- `Volunteer Team` was renamed to `Team`.

The doctype directories under
`verenigingen/verenigingen/doctype/{verenigingen_volunteer,volunteer_team}/`
no longer exist on disk. Any subsequent `frappe.get_doc("DocType", ...)`,
`frappe.reload_doctype(...)`, or meta-cache load for either name triggers
`load_doctype_module` -> ModuleNotFoundError.

Idempotent — safe to re-run. Mirrors the
`v2_2.drop_volunteer_expense_archived_doctype` pattern (PR #84).
"""

import frappe

_ORPHAN_DOCTYPES = ("Verenigingen Volunteer", "Volunteer Team")


def execute():
    for doctype_name in _ORPHAN_DOCTYPES:
        if not frappe.db.exists("DocType", doctype_name):
            continue
        try:
            frappe.delete_doc("DocType", doctype_name, force=True, ignore_missing=True)
            print(f"Dropped orphan DocType row: {doctype_name}")
        except Exception as exc:
            frappe.logger().warning(f"Could not drop orphan DocType row {doctype_name}: {exc}")

    frappe.db.commit()
