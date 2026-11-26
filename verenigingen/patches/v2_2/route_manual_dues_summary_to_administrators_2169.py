"""Give the seeded `dues_schedule_manual_creation` row the audience its only sender always had (#2169).

The key was seeded Document-Field, which names no recipient for a staff summary. Its sender
(`dues_schedule_auto_creator._send_summary_email`) now resolves recipients through the key, and went to
Verenigingen Administrators only. A row that still holds exactly the seeded state (Document-Field, no
field, no roles) becomes Role-Based with that role; anything an admin edited is left alone. The new key
`termination_weekly_report` has no row yet: the registry seed creates it.

Idempotent: after the first run no row matches.
"""

import frappe

DOCTYPE = "Verenigingen Email Configuration"
KEY = "dues_schedule_manual_creation"
ROLES = "Verenigingen Administrator"


def execute():
    if not frappe.db.exists("DocType", DOCTYPE):
        return

    # A direct UPDATE on the child row: a Single's save would rewrite every row's `modified`.
    frappe.db.sql(
        """
        UPDATE `tabEmail Notification Type`
        SET recipient_policy = 'Role-Based', recipient_roles = %s
        WHERE parent = %s AND parenttype = %s AND notification_key = %s
            AND recipient_policy = 'Document-Field'
            AND IFNULL(recipient_field, '') = '' AND IFNULL(recipient_roles, '') = ''
        """,
        (ROLES, DOCTYPE, DOCTYPE, KEY),
    )
    frappe.clear_document_cache(DOCTYPE, DOCTYPE)
