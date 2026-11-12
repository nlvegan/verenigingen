"""Seed a Single's missing Check row with its declared default (#2509).

Frappe applies a Single's JSON defaults only while the doctype has no ``tabSingles`` rows at all.
A site that saved the Single before a field existed has rows for every other field, so the Document
reads the new Check as 0 whatever its default says. For a safety flag whose default is 1 (sandbox /
test mode), 0 means LIVE. Writing the missing row makes the stored value say what the default says.
A row that exists, 0 included, is the operator's choice and is never touched.
"""

import frappe


def seed_missing_check_default(doctype: str, fieldname: str, default: str = "1") -> bool:
    """Insert ``fieldname``'s row as ``default`` when the doctype has other rows but not this one.

    Returns True when a row was written. A doctype with no rows at all is left to the declared
    default, which Frappe applies there.
    """
    if not frappe.db.exists("DocType", doctype):
        return False

    has_rows = frappe.db.sql("SELECT 1 FROM tabSingles WHERE doctype = %s LIMIT 1", doctype)
    has_field_row = frappe.db.sql(
        "SELECT 1 FROM tabSingles WHERE doctype = %s AND field = %s LIMIT 1", (doctype, fieldname)
    )
    if not has_rows or has_field_row:
        return False

    frappe.db.sql(
        "INSERT INTO tabSingles (doctype, field, value) VALUES (%s, %s, %s)", (doctype, fieldname, default)
    )
    frappe.clear_document_cache(doctype, doctype)
    return True
