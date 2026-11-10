"""Stop throttling the Ponto hand-booking staff alerts (#2248).

ponto_executed_on_cancelled_row / ponto_executed_unbookable were registered without a cooldown, so their rows
were seeded with the default 60. The registry now carries 0 (every unbookable executed payment must reach
staff). A row still holding the seeded 60 follows; any other value is an admin's own choice and is left
alone. Idempotent.

Today this changes nothing in practice: both alerts go through Notification Log, which applies no cooldown
(measured on #2248). It keeps the rows consistent with the registry should either alert ever move onto
EmailService.
"""

import frappe

DOCTYPE = "Verenigingen Email Configuration"
KEYS = ("ponto_executed_on_cancelled_row", "ponto_executed_unbookable")
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
