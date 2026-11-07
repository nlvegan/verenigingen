# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove the Critical Operation Rule for the deleted `send_overdue_notifications`
function (#1869).

The function queried Pending Members and ended at a comment: it sent nothing.
It was deleted together with its scheduler entry and the report button.

Because COR is deliberately excluded from the `fixtures` hook, `bench migrate`
never prunes rows already imported into existing sites; removing the rule from
the fixture file alone does not delete the imported record, so this patch does.
The rule name equals the bare function name (autoname `field:operation_name`).

No explicit commit: the patch runner commits, and a commit here would escape the
test transaction that exercises this module.
"""

import frappe

DEAD_RULES = [
    "send_overdue_notifications",
]


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    for name in DEAD_RULES:
        if frappe.db.exists("Critical Operation Rule", name):
            frappe.delete_doc("Critical Operation Rule", name, ignore_permissions=True, force=True)
