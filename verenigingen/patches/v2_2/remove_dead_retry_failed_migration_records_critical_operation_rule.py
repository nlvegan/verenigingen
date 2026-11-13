# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove the Critical Operation Rule for the deleted `retry_failed_migration_records`
endpoint (#660).

The endpoint was deleted: it imported the nonexistent `eboekhouden_soap_migration`
and so always raised ImportError; nothing could call it successfully.

Because COR is deliberately excluded from the `fixtures` hook, `bench migrate`
never prunes rows already imported into existing sites; removing the rule from
the fixture file alone does not delete the imported record, so this patch does.
The rule name equals the bare function name (autoname `field:operation_name`).

No explicit commit: the patch runner commits, and a commit here would escape the
test transaction that exercises this module.
"""

import frappe

DEAD_RULES = [
    "retry_failed_migration_records",
]


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    for name in DEAD_RULES:
        if frappe.db.exists("Critical Operation Rule", name):
            frappe.delete_doc("Critical Operation Rule", name, ignore_permissions=True, force=True)
