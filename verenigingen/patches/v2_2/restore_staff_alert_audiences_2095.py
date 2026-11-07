"""Give six seeded staff-alert rows back the audience their sender always had (#2095).

Those senders now resolve recipients through their notification key, and the seeded Role-Based row
for each names "System Manager, Verenigingen Administrator", which the key-first resolver honours.
Maintainer ruling on #2095: keep the old audiences. A row that still holds EXACTLY the stock value
(Role-Based, the admin pair in either order) moves to the key's registry roles; anything else is an
admin's own choice and is left alone.

The mapping is frozen here, not derived from the registry, so a later registry edit cannot re-aim
this patch. Idempotent: after the first run no row matches. The new keys (contact_request_new,
contact_request_urgent, contribution_amendment_sync_failed) have no row yet; the registry seed
creates theirs.
"""

import frappe

DOCTYPE = "Verenigingen Email Configuration"
STOCK_ROLES = ("System Manager, Verenigingen Administrator", "Verenigingen Administrator, System Manager")
NEW_ROLES = {
    "expense_approval_request": "Verenigingen Administrator",
    "business_logic_alert": "System Manager",
    "security_policy_digest": "System Manager",
    "expulsion_report_submitted": "Verenigingen Administrator",
    "system_stuck_schedules": "Verenigingen Staff",
    "contact_request_escalated": "Verenigingen Administrator",
}


def execute():
    if not frappe.db.exists("DocType", DOCTYPE):
        return

    for key, roles in NEW_ROLES.items():
        # A direct UPDATE on the child row: a Single's save would rewrite every row's `modified`.
        frappe.db.sql(
            """
            UPDATE `tabEmail Notification Type`
            SET recipient_roles = %s
            WHERE parent = %s AND parenttype = %s AND notification_key = %s
                AND recipient_policy = 'Role-Based' AND recipient_roles IN (%s, %s)
            """,
            (roles, DOCTYPE, DOCTYPE, key, *STOCK_ROLES),
        )
    frappe.clear_document_cache(DOCTYPE, DOCTYPE)
