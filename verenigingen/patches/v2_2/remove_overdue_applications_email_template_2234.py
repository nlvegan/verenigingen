# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove the stock Email Template `membership_applications_overdue` (#2234).

Its only intended sender, `send_overdue_notifications`, never sent anything and was
deleted under #1869; nothing else names the template.

Fixture sync inserts and updates but never deletes, so dropping the row from
`fixtures/email_template.json` leaves it on existing sites; this patch deletes it.
It deletes unconditionally, without comparing against the stock content (ruling #1984,
"never update an existing template", is about setup overwriting edits, not about
removing a template nobody can send): fixture sync re-imported the row on every migrate,
so any hand edit was already being overwritten (measured on test_site_8: a custom
response came back as the stock one, `modified` reset, after `sync_fixtures`), and
nothing references it by name.

No explicit commit: the patch runner commits, and a commit here would escape the
test transaction that exercises this module.
"""

import frappe

DEAD_TEMPLATE = "membership_applications_overdue"


def execute():
    if frappe.db.exists("Email Template", DEAD_TEMPLATE):
        frappe.delete_doc("Email Template", DEAD_TEMPLATE, ignore_permissions=True, force=True)
