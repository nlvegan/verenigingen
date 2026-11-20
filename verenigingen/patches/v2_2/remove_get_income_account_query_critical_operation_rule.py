# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove the Critical Operation Rule for `get_income_account_query` (deleted in #831/#2288).

Critical Operation Rule is excluded from the `fixtures` hook, so dropping the entry from
`fixtures/critical_operation_rule.json` does not prune the row on installed sites. The name
equals the bare function name (autoname `field:operation_name`) and the function no longer
exists anywhere in the app, so removing the row cannot orphan a live endpoint's configuration.

No explicit commit: the patch runner commits after each patch.

Precedent: `remove_workflow_demo_critical_operation_rules.py`.
"""

import frappe

DEAD_RULE = "get_income_account_query"


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    if frappe.db.exists("Critical Operation Rule", DEAD_RULE):
        frappe.delete_doc("Critical Operation Rule", DEAD_RULE, ignore_permissions=True, force=True)
