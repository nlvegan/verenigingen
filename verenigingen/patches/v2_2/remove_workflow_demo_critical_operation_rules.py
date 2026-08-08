# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove Critical Operation Rules for the workflow_demo endpoints deleted in PR #249.

PR #249 removes `templates/pages/workflow_demo.py` along with its two whitelisted
endpoints, and drops their entries from `fixtures/critical_operation_rule.json`.
That fixture edit is not enough on its own: Critical Operation Rule is deliberately
excluded from the `fixtures` hook, so `bench migrate` never re-imports or prunes
these rows. The already-imported records survive the deletion of the code they
guard (verified still `enabled=1` on veg11 after the fixture edit) — this patch
removes them.

Rule names equal the bare function name (autoname `field:operation_name`), and
neither name has any remaining definition anywhere in the app, so the deletion
cannot orphan a live endpoint's rate-limit configuration.

Precedent: `remove_dead_portal_critical_operation_rules.py`.
"""

import frappe

DEAD_RULES = [
    "execute_workflow_action",
    "get_workflow_actions",
]


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    removed = 0
    for name in DEAD_RULES:
        if frappe.db.exists("Critical Operation Rule", name):
            frappe.delete_doc("Critical Operation Rule", name, ignore_permissions=True, force=True)
            removed += 1

    if removed:
        frappe.db.commit()
        print(f"Removed {removed} dead workflow_demo Critical Operation Rule(s)")
