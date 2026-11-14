"""Point the seeded payment_alert_failure row at Financial Managers (#1330).

Maintainer ruling on #1330: a repeated Payment Entry failure alert goes to finance staff. The seeded
Role-Based row named "System Manager, Verenigingen Administrator". As in #2093: a row that still holds
EXACTLY that old stock value (Role-Based, those roles) moves; anything else is an admin's own choice and
is left alone. The old stock value is frozen here, not derived from the registry. Idempotent: after the
first run no row matches.
"""

import frappe

DOCTYPE = "Verenigingen Email Configuration"
KEY = "payment_alert_failure"
OLD_STOCK_ROLES = "System Manager, Verenigingen Administrator"
NEW_ROLES = "Verenigingen Financial Manager"


def execute():
    if not frappe.db.exists("DocType", DOCTYPE):
        return

    # A direct UPDATE on the child row: a Single's save would rewrite every row's `modified`.
    frappe.db.sql(
        """
        UPDATE `tabEmail Notification Type`
        SET recipient_roles = %s
        WHERE parent = %s AND parenttype = %s AND notification_key = %s
            AND recipient_policy = 'Role-Based' AND recipient_roles = %s
        """,
        (NEW_ROLES, DOCTYPE, DOCTYPE, KEY, OLD_STOCK_ROLES),
    )
    frappe.clear_document_cache(DOCTYPE, DOCTYPE)
