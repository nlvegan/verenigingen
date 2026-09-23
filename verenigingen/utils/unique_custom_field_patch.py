"""Shared steps for a patch that turns a Custom Field into a live unique constraint.

Both `patches/v2_2/add_mollie_payment_entry_idempotency_key.py` (#809) and
`patches/v2_2/enforce_unique_bank_transaction_reference.py` (#1267) follow the same
sequence for the same reason: the Custom Field is created WITHOUT `unique`, existing rows
are backfilled with a derived key, and only THEN is `unique` set. Creating it unique first
would work (the column starts all-NULL) but would surface any collision one row at a time,
as a raw DB error in the middle of the backfill, instead of as one report naming every
offending group -- each patch's own `_abort_on_duplicates` is what produces that report.

Extracted here (rather than left as two copies) because `duplicate_helper_validator.py`
flagged the original two as near-identical, and per that validator's own rationale: "a
copy-pasted helper is where a fix goes to die -- the next person fixes one of these and
the others keep the bug, silently."

Each caller keeps its OWN `_find_duplicates` / `_abort_on_duplicates` / `_backfill` and its
own derived-key module: those are NOT shared, because the scope predicate (which rows are
"in scope" for the constraint) genuinely differs between them -- Mollie-style reference
matching vs. blank-reference exemption. Only the doctype-agnostic Custom Field lifecycle
below is common.
"""

import frappe


def get_custom_field_name(dt: str, fieldname: str):
    """The `Custom Field` document name for `dt.fieldname`, or `None` if it does not exist."""
    return frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname}, "name")


def ensure_unique(dt: str, fieldname: str) -> bool:
    """Flip `unique` on an already-backfilled Custom Field. Idempotent.

    Returns True if this call is what set it (for the caller's own print/log), False if it
    was already unique.
    """
    name = get_custom_field_name(dt, fieldname)
    if frappe.db.get_value("Custom Field", name, "unique"):
        return False

    field = frappe.get_doc("Custom Field", name)
    field.unique = 1
    field.save(ignore_permissions=True)
    return True


def unique_index_exists(dt: str, fieldname: str) -> bool:
    """Whether a real UNIQUE index backs `dt.fieldname` right now.

    Checked directly against the schema rather than trusting the Custom Field's `unique`
    flag: the flag is what was *asked for*, this is what the schema sync actually *did*.
    """
    return bool(
        frappe.db.sql(
            f"SHOW INDEX FROM `tab{dt}` WHERE Column_name = %s AND Non_unique = 0",
            fieldname,
        )
    )
