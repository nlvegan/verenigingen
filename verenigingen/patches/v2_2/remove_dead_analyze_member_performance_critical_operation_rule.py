# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove the Critical Operation Rule `analyze_member_performance` (#2637).

It matched the bare name of the whitelisted endpoint in
`scripts/member_performance_analyzer.py`, which always crashed (frappe has no
`query_log_context`) and which #2637 deleted; no endpoint of that name remains.

Because COR is deliberately excluded from the `fixtures` hook, `bench migrate`
never prunes rows already imported into existing sites; removing the rule from
the fixture file alone does not delete the imported record, so this patch does.
The rule name equals the bare function name (autoname `field:operation_name`).

No explicit commit: the patch runner commits, and a commit here would escape the
test transaction that exercises this module.
"""

import frappe

DEAD_RULES = [
    "analyze_member_performance",
]


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    for name in DEAD_RULES:
        if frappe.db.exists("Critical Operation Rule", name):
            frappe.delete_doc("Critical Operation Rule", name, ignore_permissions=True, force=True)
