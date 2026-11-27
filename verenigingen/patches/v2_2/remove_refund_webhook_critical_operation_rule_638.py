# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove the Critical Operation Rule for the deleted `handle_refund_webhook` endpoint (#638).

Mollie announces refunds on the payment's own webhookUrl, so the separate refund endpoint
was never called; the maintainer ruled it deleted (2026-11-27).

Because COR is deliberately excluded from the `fixtures` hook, `bench migrate`
never prunes rows already imported into existing sites; removing the rule from
the fixture file alone does not delete the imported record, so this patch does.
The rule name equals the bare function name (autoname `field:operation_name`).

No explicit commit: the patch runner commits, and a commit here would escape the
test transaction that exercises this module.
"""

import frappe

DEAD_RULES = [
    "handle_refund_webhook",
]


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    for name in DEAD_RULES:
        if frappe.db.exists("Critical Operation Rule", name):
            frappe.delete_doc("Critical Operation Rule", name, ignore_permissions=True, force=True)
