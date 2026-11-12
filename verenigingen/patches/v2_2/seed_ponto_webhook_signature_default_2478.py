"""Write the missing ``require_webhook_signature`` row of Ponto Settings as 1 (#2478).

Frappe applies a Single's declared defaults only while the doctype has no ``tabSingles`` rows at
all. A site that saved Ponto Settings before the field existed has rows for everything else, so the
form showed the box unticked while the webhook (now fail-closed) required the signature. Seeding the
row makes the form say what the webhook does. A real row, 0 included, is the operator's choice and
is never touched. Idempotent.
"""

import frappe

DOCTYPE = "Ponto Settings"
FIELD = "require_webhook_signature"


def execute():
    if not frappe.db.exists("DocType", DOCTYPE):
        return

    has_rows = frappe.db.sql("SELECT 1 FROM tabSingles WHERE doctype = %s LIMIT 1", DOCTYPE)
    has_field_row = frappe.db.sql(
        "SELECT 1 FROM tabSingles WHERE doctype = %s AND field = %s LIMIT 1", (DOCTYPE, FIELD)
    )
    if has_rows and not has_field_row:
        frappe.db.sql(
            "INSERT INTO tabSingles (doctype, field, value) VALUES (%s, %s, %s)", (DOCTYPE, FIELD, "1")
        )
        frappe.clear_document_cache(DOCTYPE, DOCTYPE)
