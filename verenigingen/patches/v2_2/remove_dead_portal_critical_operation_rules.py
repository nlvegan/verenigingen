# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove Critical Operation Rules for the portal endpoints deleted in PR #152.

PR #152 (portal dead-wiring cleanup) removed ten whitelisted endpoints from the
portal page controllers, but their Critical Operation Rule records had already
been imported into existing sites. Because COR is deliberately excluded from the
`fixtures` hook, `bench migrate` never re-imports (or prunes) these rows, so the
dead rules linger in the DB. Removing them from the fixture file alone does not
delete the already-imported records — this patch does.

Rule names equal the bare function name (autoname `field:operation_name`), and
none of these names has any remaining live definition in the codebase, so the
deletion cannot orphan a live endpoint's rate-limit configuration.
"""

import frappe

DEAD_RULES = [
    "calculate_suggested_contribution",
    "create_volunteer_for_member",
    "get_compliance_audit_report",
    "get_detailed_analytics_report",
    "get_performance_optimization_report",
    "search_skills",
    "setup_member_portal_menu",
    "reset_portal_menu_to_member_only",
    "get_clean_member_portal_menu",
    "analyze_current_portal_usage",
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
        print(f"Removed {removed} dead portal Critical Operation Rule(s)")
