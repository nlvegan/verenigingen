# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove the Critical Operation Rule for `get_member_home_page` (#2253).

The endpoint is a plain `@frappe.whitelist()` (#2207) with no security-tier decorator,
so nothing ever looked this rule up. Its fixture row is deleted; COR is excluded from the
`fixtures` hook, so `bench migrate` never prunes rows already imported into existing
sites and this patch does. The rule name equals the bare function name (autoname
`field:operation_name`); the endpoint itself is untouched.

No explicit commit: the patch runner commits, and a commit here would escape the
test transaction that exercises this module.
"""

import frappe

DEAD_RULES = [
    "get_member_home_page",
]


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    for name in DEAD_RULES:
        if frappe.db.exists("Critical Operation Rule", name):
            frappe.delete_doc("Critical Operation Rule", name, ignore_permissions=True, force=True)
