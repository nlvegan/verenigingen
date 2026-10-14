# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove the Critical Operation Rules for the deleted role-profile assignment
endpoints (#1659).

`assign_chapter_board_role_profile` and `assign_team_role_profile` were deleted: they
gave a chapter's or team's mapped profile to any user without a seat, and nothing
called them.

Because COR is deliberately excluded from the `fixtures` hook, `bench migrate`
never prunes rows already imported into existing sites; removing them from the
fixture file alone does not delete the imported records, so this patch does.
Rule names equal the bare function name (autoname `field:operation_name`), and
neither name has any remaining live definition, so the deletion cannot orphan a
live endpoint's rate-limit configuration.

No explicit commit: the patch runner commits, and a commit here would escape the
test transaction that exercises this module.
"""

import frappe

DEAD_RULES = [
    "assign_chapter_board_role_profile",
    "assign_team_role_profile",
]


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    for name in DEAD_RULES:
        if frappe.db.exists("Critical Operation Rule", name):
            frappe.delete_doc("Critical Operation Rule", name, ignore_permissions=True, force=True)
