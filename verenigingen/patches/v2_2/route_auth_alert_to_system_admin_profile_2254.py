"""Move the seeded `auth_monitoring_alert` row to Custom so the profile default applies (#2254).

The critical authentication alert now resolves recipients through its key and, by default, goes to the
holders of the Verenigingen System Administrator role profile. The seeded Role-Based row names the
admin roles, which the key-first resolver honours before anything else, so it would shadow that default.
A row that still holds EXACTLY the stock value (Role-Based, the admin pair in either order) becomes
Custom with no roles; anything an admin edited is left alone. Idempotent: afterwards no row matches.
"""

import frappe

DOCTYPE = "Verenigingen Email Configuration"
KEY = "auth_monitoring_alert"
STOCK_ROLES = ("System Manager, Verenigingen Administrator", "Verenigingen Administrator, System Manager")


def execute():
    if not frappe.db.exists("DocType", DOCTYPE):
        return

    # A direct UPDATE on the child row: a Single's save would rewrite every row's `modified`.
    frappe.db.sql(
        """
        UPDATE `tabEmail Notification Type`
        SET recipient_policy = 'Custom', recipient_roles = NULL
        WHERE parent = %s AND parenttype = %s AND notification_key = %s
            AND recipient_policy = 'Role-Based' AND recipient_roles IN (%s, %s)
        """,
        (DOCTYPE, DOCTYPE, KEY, *STOCK_ROLES),
    )
    frappe.clear_document_cache(DOCTYPE, DOCTYPE)
