# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove the Critical Operation Rules for the deleted chapter-board permission
endpoints (#1588).

`setup_chapter_board_permissions` and `reset_chapter_board_permissions` were
deleted as dead code (they always failed with developer_mode=0, and the DocType
JSON already ships the Chapter Board Member permission rows).

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
    "setup_chapter_board_permissions",
    "reset_chapter_board_permissions",
]


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    for name in DEAD_RULES:
        if frappe.db.exists("Critical Operation Rule", name):
            frappe.delete_doc("Critical Operation Rule", name, ignore_permissions=True, force=True)
