"""Stop throttling the new-contact-request staff alerts (#2174).

contact_request_new / contact_request_urgent were registered (#2095) without a cooldown, so their rows
were seeded with the default 60. Once the mail really fires, that mailed staff about only the first
request each hour. They are per-event alerts: a row still holding the seeded 60 moves to 0, any other
value is an admin's own choice and is left alone. Idempotent.
"""

import frappe

DOCTYPE = "Verenigingen Email Configuration"
KEYS = ("contact_request_new", "contact_request_urgent")
SEEDED_DEFAULT = 60


def execute():
    if not frappe.db.exists("DocType", DOCTYPE):
        return

    # A direct UPDATE on the child rows: a Single's save would rewrite every row's `modified`.
    for key in KEYS:
        frappe.db.sql(
            """
            UPDATE `tabEmail Notification Type`
            SET cooldown_minutes = 0
            WHERE parent = %s AND parenttype = %s AND notification_key = %s AND cooldown_minutes = %s
            """,
            (DOCTYPE, DOCTYPE, key, SEEDED_DEFAULT),
        )
    frappe.clear_document_cache(DOCTYPE, DOCTYPE)
