"""Flag the Bank Transactions the prefix rule had constrained (#1349).

`custom_reference_number_key` used to be derived from the SHAPE of `reference_number`
(`tr_`/`stl_`/`baltr_`/`EB-`), so a payer-typed "EB-2024" on an MT940 line was refused as a
duplicate. The key is now derived from `custom_reference_is_system_issued`, a flag the WRITER
sets (see `bank_transaction_reference_key.py`).

Rows written before that change carry no flag, and `validate` recomputes the key on EVERY
save. Without this patch the next save of an old Mollie row (a reconciliation, a Payment
Entry link) would clear its key and drop it out of the unique index, so a genuine duplicate
could then be inserted next to it. So this patch sets the flag on every row the prefix rule
had constrained, which is exactly the set that already holds a key: nothing newly constrained
by it, nothing released by it.

Deploy window: between the code going live and this patch running, the column is absent, so
`validate` computes the key from a flag it cannot read and an old row saved in that window
loses its key. Flagging such a row alone would leave its key NULL, outside the unique index,
so the patch also re-keys every flagged row whose key is NULL, with `build_reference_key`
(the one definition of the key). A row whose recomputed key now collides with another row's
(a duplicate inserted in that same window) is skipped and reported through an Error Log row
rather than aborting the patch: it needs a human to pick the survivor.

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

from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS, rollback_to_savepoint
from verenigingen.utils.unique_custom_field_patch import ensure_custom_field
from verenigingen.verenigingen_payments.utils.bank_transaction_reference_key import (
    FIELDNAME,
    PONTO_TRANSACTION_ID_FIELDNAME,
    SYSTEM_ISSUED_FIELDNAME,
    build_reference_key,
    legacy_prefix_sql_condition,
)

DOCTYPE = "Bank Transaction"
COLLISION_LOG_TITLE = "Bank Transaction re-key collision (#1349)"


def execute():
    if not frappe.db.table_exists(DOCTYPE):
        print(f"tab{DOCTYPE} does not exist - skipping {SYSTEM_ISSUED_FIELDNAME}")
        return

    _ensure_system_issued_field()
    print(f"Flagged {flag_prefix_constrained_rows()} Bank Transactions as system-issued ({SYSTEM_ISSUED_FIELDNAME})")
    print(f"Re-keyed {rekey_flagged_rows_missing_key()} flagged Bank Transactions ({FIELDNAME})")


def _ensure_system_issued_field():
    ensure_custom_field(
        DOCTYPE,
        SYSTEM_ISSUED_FIELDNAME,
        label="Reference Is System-Issued",
        fieldtype="Check",
        default="0",
        hidden=1,
        read_only=1,
        print_hide=1,
        insert_after="custom_reference_number_key",
        description=(
            "Set by the WRITER of a Bank Transaction whose reference_number was issued by a "
            "system that guarantees it unique (Mollie ids, e-Boekhouden EB-<mutation id>). "
            "Only such rows get a custom_reference_number_key (see #1349, #1267)."
        ),
    )


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


def rekey_flagged_rows_missing_key() -> int:
    """Give every flagged row that has no key the key `validate` would give it. Returns how
    many were keyed. A row whose key collides with another row's is skipped and logged."""
    # The Ponto column is a fixture too, so it may not exist yet on an upgrading site.
    ponto = PONTO_TRANSACTION_ID_FIELDNAME
    has_ponto = frappe.db.has_column(DOCTYPE, ponto)
    rows = frappe.get_all(
        DOCTYPE,
        filters={SYSTEM_ISSUED_FIELDNAME: 1, FIELDNAME: ("is", "not set")},
        fields=["name", "bank_account", "reference_number"] + ([ponto] if has_ponto else []),
        order_by="creation asc",
    )
    keyed = 0
    for row in rows:
        key = build_reference_key(
            row.bank_account, row.reference_number, row.get(ponto), system_issued=1
        )
        if key and _set_key(row.name, key):
            keyed += 1
    return keyed


def _set_key(name, key) -> bool:
    save_point = f"rekey_{frappe.generate_hash(length=8)}"
    frappe.db.savepoint(save_point)
    try:
        frappe.db.set_value(DOCTYPE, name, FIELDNAME, key, update_modified=False)
    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as exc:
        if not frappe.db.is_duplicate_entry(exc):
            raise
        rollback_to_savepoint(save_point)
        _log_collision(name, key)
        return False
    return True


def _log_collision(name, key):
    """Report a skipped row, naming the row that holds its key so staff can resolve the real
    duplicate. A re-run reports the same (row, holder) pair once: the Error Log is a
    non-transactional table, so the earlier row survives the rollback above. A different
    holder changes the message and is logged."""
    holder = frappe.db.get_value(DOCTYPE, {FIELDNAME: key}, "name")
    message = (
        f"{name} duplicates {holder or 'another Bank Transaction'}'s system-issued reference; "
        f"left unkeyed (flag set, key NULL), so every later save of it raises a unique-key error. "
        f"Delete or re-import one of the two."
    )
    if frappe.db.exists("Error Log", {"method": COLLISION_LOG_TITLE, "error": message}):
        return
    frappe.log_error(title=COLLISION_LOG_TITLE, message=message)
