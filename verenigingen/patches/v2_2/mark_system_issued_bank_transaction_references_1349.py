"""Flag the Bank Transactions the prefix rule had constrained (#1349).

`custom_reference_number_key` used to be derived from the SHAPE of `reference_number`
(`tr_`/`stl_`/`baltr_`/`EB-`), so a payer-typed "EB-2024" on an MT940 line was refused as a
duplicate. The key is now derived from `custom_reference_is_system_issued`, a flag the WRITER
sets (see `bank_transaction_reference_key.py`).

Rows written before that change carry no flag, and `validate` recomputes the key on EVERY
save. Without this patch the next save of an old Mollie row (a reconciliation, a Payment
Entry link) would clear its key and drop it out of the unique index, so a genuine duplicate
could then be inserted next to it. So this patch sets the flag on every row the prefix rule
had constrained, which is exactly the set that already holds a key: nothing newly constrained,
nothing newly released.

Residual, stated plainly: a pre-existing MT940 row whose payer reference starts with one of
those prefixes is flagged too, because nothing on the row says who wrote it. It stays
constrained exactly as today. It is not corrected here, because guessing the writer from the
row is the prefix guess #1349 removes. A row staff delete or re-import is classified by its
real writer.

Order: runs after `enforce_unique_bank_transaction_reference`, which keyed those rows. It
creates the Custom Field itself because fixtures sync AFTER post_model_sync patches, so the
column does not exist yet on an upgrading site (`in_scope_sql_condition`'s docstring).
Idempotent: a re-run flags nothing new. Unrecorded and retried if it raises.
"""

import frappe

from verenigingen.utils.unique_custom_field_patch import get_custom_field_name
from verenigingen.verenigingen_payments.utils.bank_transaction_reference_key import (
    SYSTEM_ISSUED_FIELDNAME,
    legacy_prefix_sql_condition,
)

DOCTYPE = "Bank Transaction"


def execute():
    if not frappe.db.table_exists(DOCTYPE):
        print(f"tab{DOCTYPE} does not exist - skipping {SYSTEM_ISSUED_FIELDNAME}")
        return

    _ensure_field_exists()
    print(f"Flagged {flag_prefix_constrained_rows()} Bank Transactions as system-issued ({SYSTEM_ISSUED_FIELDNAME})")


def _ensure_field_exists():
    if get_custom_field_name(DOCTYPE, SYSTEM_ISSUED_FIELDNAME):
        return

    frappe.get_doc(
        {
            "doctype": "Custom Field",
            "dt": DOCTYPE,
            "fieldname": SYSTEM_ISSUED_FIELDNAME,
            "label": "Reference Is System-Issued",
            "fieldtype": "Check",
            "default": "0",
            "hidden": 1,
            "read_only": 1,
            "print_hide": 1,
            "insert_after": "custom_reference_number_key",
            "description": (
                "Set by the WRITER of a Bank Transaction whose reference_number was issued by a "
                "system that guarantees it unique (Mollie ids, e-Boekhouden EB-<mutation id>). "
                "Only such rows get a custom_reference_number_key (see #1349, #1267)."
            ),
        }
    ).insert(ignore_permissions=True)
    print(f"Created Custom Field {DOCTYPE}.{SYSTEM_ISSUED_FIELDNAME}")


def flag_prefix_constrained_rows() -> int:
    """Set the flag on every row the prefix rule constrained. Returns how many changed."""
    frappe.db.sql(
        f"""
        UPDATE `tab{DOCTYPE}`
        SET `{SYSTEM_ISSUED_FIELDNAME}` = 1
        WHERE {legacy_prefix_sql_condition()}
          AND IFNULL(`{SYSTEM_ISSUED_FIELDNAME}`, 0) = 0
        """
    )
    return frappe.db.sql("SELECT ROW_COUNT()")[0][0]
