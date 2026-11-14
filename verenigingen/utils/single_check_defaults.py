"""Seed a Single's missing Check row with its declared default (#2509).

Frappe applies a Single's JSON defaults only while the doctype has no ``tabSingles`` rows at all.
A site that saved the Single before a field existed has rows for every other field, so the Document
reads the new Check as 0 whatever its default says. A blank or NULL row reads 0 too. For a safety
flag whose default is 1 (sandbox / test mode), 0 means LIVE. Writing the row makes the stored value
say what the default says.

Trade-off (maintainer ruling on #2509): the flag is seeded ONLY when no live credential is configured
for the gateway. A site that is genuinely live (live credentials present) with a missing or blank row
is left untouched, because seeding would switch it to test mode and silently break real payments;
an Error Log row names the doctype and field so an operator decides. A row holding an explicit 0 is
the operator's choice and is never touched.
"""

from typing import Callable, Optional

import frappe


def seed_missing_check_default(
    doctype: str,
    fieldname: str,
    default: str = "1",
    has_live_credentials: Optional[Callable[[], bool]] = None,
) -> bool:
    """Write ``fieldname``'s row as ``default`` when the doctype has other rows but this one is
    missing, blank or NULL.

    Returns True when a row was written. A doctype with no rows at all is left to the declared
    default, which Frappe applies there. With live credentials the row is left as it is and an Error
    Log row is written instead.
    """
    if not frappe.db.exists("DocType", doctype):
        return False

    if not frappe.db.sql("SELECT 1 FROM tabSingles WHERE doctype = %s LIMIT 1", doctype):
        return False

    rows = frappe.db.sql(
        "SELECT value FROM tabSingles WHERE doctype = %s AND field = %s", (doctype, fieldname)
    )
    if rows and rows[0][0] not in (None, ""):
        return False

    if has_live_credentials and has_live_credentials():
        _alert_live_site_left_alone(doctype, fieldname)
        return False

    if rows:
        frappe.db.sql(
            "UPDATE tabSingles SET value = %s WHERE doctype = %s AND field = %s",
            (default, doctype, fieldname),
        )
    else:
        frappe.db.sql(
            "INSERT INTO tabSingles (doctype, field, value) VALUES (%s, %s, %s)",
            (doctype, fieldname, default),
        )
    frappe.clear_document_cache(doctype, doctype)
    return True


def _alert_live_site_left_alone(doctype: str, fieldname: str) -> None:
    frappe.log_error(
        title=f"{doctype}.{fieldname} has no stored value but live credentials are configured",
        message=(
            f"{doctype}.{fieldname} has no stored value, so the form reads it as 0 (live). Live "
            "credentials are configured, so the row was NOT seeded with the default of 1 (test mode), "
            "which would stop real calls. Open the settings, choose the mode you intend and save."
        ),
    )
