# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove the Critical Operation Rule for ``process_member_post_creation`` (#2232).

The function is no longer whitelisted: its only caller is the background enqueue in
``MemberPerformanceOptimizer.create_member_optimized``. COR is deliberately excluded from
the ``fixtures`` hook, so ``bench migrate`` never prunes an already-imported row; this
patch does. The rule's name equals the bare function name (autoname is
``field:operation_name``), and no whitelisted / @critical_api endpoint with that name
remains, so no live endpoint's rate-limit configuration is orphaned.
"""

import frappe

DEAD_RULES = ["process_member_post_creation"]


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
        print(f"Removed {removed} dead process_member_post_creation Critical Operation Rule(s)")
