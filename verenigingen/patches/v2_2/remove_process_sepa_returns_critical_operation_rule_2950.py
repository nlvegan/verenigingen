# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove the Critical Operation Rule for the deleted `process_sepa_returns` endpoint (#2950).

The endpoint took a server filesystem path and had no first-party caller; the maintainer
ruled it removed (2026-11-20).

Because COR is deliberately excluded from the `fixtures` hook, `bench migrate`
never prunes rows already imported into existing sites; removing the rule from
the fixture file alone does not delete the imported record, so this patch does.
The rule name equals the bare function name (autoname `field:operation_name`).

No explicit commit: the patch runner commits, and a commit here would escape the
test transaction that exercises this module.
"""

import frappe

DEAD_RULES = [
    "process_sepa_returns",
]


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    for name in DEAD_RULES:
        if frappe.db.exists("Critical Operation Rule", name):
            frappe.delete_doc("Critical Operation Rule", name, ignore_permissions=True, force=True)
