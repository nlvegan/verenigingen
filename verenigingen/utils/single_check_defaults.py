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
from frappe.utils.password import get_decrypted_password

NO_ROWS, SET, MISSING, BLANK = "no_rows", "set", "missing", "blank"


def check_row_state(doctype: str, fieldname: str) -> str:
    """Classify ``fieldname``'s ``tabSingles`` row: NO_ROWS (the doctype was never saved, Frappe applies
    the declared default), SET (a real value, an explicit "0" included), MISSING or BLANK (NULL or "")."""
    if not frappe.db.sql("SELECT 1 FROM tabSingles WHERE doctype = %s LIMIT 1", doctype):
        return NO_ROWS
    rows = frappe.db.sql(
        "SELECT value FROM tabSingles WHERE doctype = %s AND field = %s", (doctype, fieldname)
    )
    if not rows:
        return MISSING
    return BLANK if rows[0][0] in (None, "") else SET


def is_check_unset(doctype: str, fieldname: str) -> bool:
    """True when the doctype has other rows but this field's row is missing, blank or NULL: the
    Document then reads the Check as 0 whatever its declared default says (#2565)."""
    return check_row_state(doctype, fieldname) in (MISSING, BLANK)


def apply_safe_default(
    doc,
    fieldname: str,
    default: int = 1,
    has_live_credentials: Optional[Callable[[], bool]] = None,
) -> bool:
    """Read-time guard for a SAFETY flag (#2565): when the row is unset, set ``doc.<fieldname>`` in
    memory to the safe ``default``. Nothing is written; a later save stores it.

    ``frappe.db.set_single_value`` on a row-less Single creates rows only for the field it was given,
    so the seed patches (#2478, #2509) do not keep the state from recurring. With live credentials
    the value is left at 0 (maintainer ruling on #2509: a live site is not silently switched to test
    mode). A real row, 0 included, is never overridden. ``frappe.db.get_single_value`` reads
    ``tabSingles`` directly and bypasses this guard (no current reader of these flags uses it). Returns True when the value was applied.
    """
    if not is_check_unset(doc.doctype, fieldname):
        return False
    if has_live_credentials and has_live_credentials():
        return False
    doc.set(fieldname, default)
    return True


def _password_set(doctype: str, fieldname: str) -> bool:
    return bool(get_decrypted_password(doctype, doctype, fieldname, raise_exception=False))


def mollie_has_live_credentials() -> bool:
    return _password_set("Mollie Settings", "live_secret_key")


def ing_has_live_credentials() -> bool:
    """ING Checkout has ONE credential set (the sandbox is a flag on the same keys), so an enabled
    integration with an API token configured counts as operating, i.e. possibly live."""
    return bool(
        frappe.db.get_single_value("ING Checkout Settings", "enabled")
        and _password_set("ING Checkout Settings", "api_token")
    )


def ponto_has_live_credentials() -> bool:
    return bool(
        frappe.db.get_single_value("Ponto Settings", "production_client_id")
        or _password_set("Ponto Settings", "production_client_secret")
    )


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

    state = check_row_state(doctype, fieldname)
    if state not in (MISSING, BLANK):
        return False

    if has_live_credentials and has_live_credentials():
        _alert_live_site_left_alone(doctype, fieldname)
        return False

    if state == BLANK:
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
