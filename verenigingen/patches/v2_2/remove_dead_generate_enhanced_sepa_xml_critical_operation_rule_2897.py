# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove the Critical Operation Rule for `generate_enhanced_sepa_xml` (#2897).

The function is an in-process helper, not an endpoint (the maintainer ruled it is not
to be whitelisted), so nothing ever looked this rule up. Its fixture row is deleted;
COR is excluded from the `fixtures` hook, so `bench migrate` never prunes rows already
imported into existing sites and this patch does. Without it, a later `critical_api`
decoration of the function would silently inherit the row on old sites only. The rule
name equals the bare function name (autoname `field:operation_name`).

No explicit commit: the patch runner commits, and a commit here would escape the
test transaction that exercises this module.
"""

import frappe

DEAD_RULES = [
    "generate_enhanced_sepa_xml",
]


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    for name in DEAD_RULES:
        if frappe.db.exists("Critical Operation Rule", name):
            frappe.delete_doc("Critical Operation Rule", name, ignore_permissions=True, force=True)
