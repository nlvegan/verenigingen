# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove the stock Email Templates `payment_failure_first`, `payment_failure_second` and
`payment_failure_generic` (#3103).

No sender renders any of them (maintainer ruling 2026-11-25: members get the per-failure
"Payment Retry Scheduled" mail and the retry-exhaustion mail, `payment_failure_final`, which
is kept). Fixture sync inserts and updates but never deletes, so dropping the rows from
`fixtures/email_template.json` leaves them on existing sites; this patch deletes them.

An Email Notification Type row may still link one of them (the v15 seed patches wrote
`email_template`), and a dangling Link fails the next save of that row, so the link is
cleared first. Deletes unconditionally for the reasons given in
`remove_overdue_applications_email_template_2234`.

No explicit commit: the patch runner commits, and a commit here would escape the
test transaction that exercises this module.
"""

import frappe

DEAD_TEMPLATES = ("payment_failure_first", "payment_failure_second", "payment_failure_generic")


def execute():
    frappe.db.set_value(
        "Email Notification Type",
        {"email_template": ["in", DEAD_TEMPLATES]},
        "email_template",
        None,
        update_modified=False,
    )
    for name in DEAD_TEMPLATES:
        if frappe.db.exists("Email Template", name):
            frappe.delete_doc("Email Template", name, ignore_permissions=True, force=True)
