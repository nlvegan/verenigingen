"""Point the seeded sepa_batch_scheduler_alert row at Financial Managers (#2093).

The alert used to go to Verenigingen Financial Manager holders, but the seeded Role-Based row named
"System Manager, Verenigingen Administrator", which the key-first resolver would now honour. Maintainer
ruling on #2093: the seeded row is Financial Manager. A row that still holds EXACTLY the old stock value
(Role-Based, those roles) moves; anything else is an admin's own choice and is left alone.

The old stock value is frozen here, not derived from the registry. Idempotent: after the first run no
row matches.
"""

import frappe

DOCTYPE = "Verenigingen Email Configuration"
KEY = "sepa_batch_scheduler_alert"
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
