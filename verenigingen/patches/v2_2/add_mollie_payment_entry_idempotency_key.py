"""Install the Mollie Payment Entry idempotency key and its unique index (#809).

Sequence matters and is not the obvious one. The unique index is created by Frappe the
moment a Custom Field carrying `unique: 1` is saved, so the field is created WITHOUT
`unique`, the existing rows are backfilled, and only then is `unique` set. Creating it
unique first would work (the column starts all-NULL) but would then surface any collision
one row at a time, as a raw DB error in the middle of the backfill, instead of as one
report naming every offending group.

Raises rather than declining. Frappe records a patch as executed only when `execute()`
returns without raising (`frappe.modules.patch_handler.execute_patch`), so a patch that
logs and returns is indistinguishable from one that did the work -- that is #746 exactly,
and it left the guard silently absent for months. Raising leaves this patch unrecorded, so
the next `bench migrate` tries again.

It does NOT delete or merge duplicates. Choosing which Payment Entry survives is a data
decision with GL consequences, not a migration's call -- the same disposition as
`enforce_unique_user_per_member`.
"""

import frappe

from verenigingen.verenigingen_payments.utils.mollie_idempotency_key import (
    FIELDNAME,
    MOLLIE_REFERENCE_SQL_CONDITION,
    build_idempotency_key,
)

DOCTYPE = "Payment Entry"


def execute():
    if not frappe.db.table_exists(DOCTYPE):
        print(f"tab{DOCTYPE} does not exist - skipping {FIELDNAME}")
        return

    _ensure_field_exists()

    duplicates = _find_duplicates()
    if duplicates:
        _abort_on_duplicates(duplicates)

    updated = _backfill()
    print(f"Backfilled {FIELDNAME} on {updated} Mollie-style Payment Entries")

    _ensure_unique()

    if not _unique_index_exists():
        frappe.throw(
            f"{FIELDNAME} is marked unique but no unique index exists on tab{DOCTYPE}. "
            "The schema sync did not create it; do not treat this guard as active."
        )
    print(f"Unique index on {DOCTYPE}.{FIELDNAME} is in place")


def _custom_field_name():
    return frappe.db.get_value("Custom Field", {"dt": DOCTYPE, "fieldname": FIELDNAME}, "name")


def _ensure_field_exists():
    if _custom_field_name():
        return

    frappe.get_doc(
        {
            "doctype": "Custom Field",
            "dt": DOCTYPE,
            "fieldname": FIELDNAME,
            "label": "Mollie Idempotency Key",
            "fieldtype": "Data",
            "hidden": 1,
            "read_only": 1,
            "no_copy": 1,
            "print_hide": 1,
            # unique is set only after the backfill - see the module docstring.
            "unique": 0,
            "insert_after": "reference_date",
            "description": (
                "Derived key that makes the Mollie booking guard a database constraint "
                "instead of a check-then-act. NULL for non-Mollie payments (see #809)."
            ),
        }
    ).insert(ignore_permissions=True)
    print(f"Created Custom Field {DOCTYPE}.{FIELDNAME}")


def _find_duplicates():
    """Mollie-style rows sharing one (reference_no, payment_type, party).

    Deliberately does NOT exclude cancelled rows: a unique index has no docstatus
    predicate, so a cancelled Payment Entry still occupies the key. That shape is common
    here -- `migration_duplicate_detection.py` cancels a duplicate and only deletes it
    when it has no GL Entries, leaving exactly one cancelled and one submitted row.
    """
    return frappe.db.sql(
        f"""
        SELECT reference_no, payment_type, party, COUNT(*) AS count
        FROM `tab{DOCTYPE}`
        WHERE {MOLLIE_REFERENCE_SQL_CONDITION}
        GROUP BY reference_no, payment_type, party
        HAVING count > 1
        ORDER BY count DESC
        """,
        as_dict=True,
    )


def _abort_on_duplicates(duplicates):
    lines = [
        f"  {d.reference_no!r} / {d.payment_type} / {d.party!r} x{d.count}" for d in duplicates[:20]
    ]
    if len(duplicates) > 20:
        lines.append(f"  ... and {len(duplicates) - 20} more groups")

    total_rows = sum(d.count for d in duplicates)
    message = (
        f"Cannot make {DOCTYPE}.{FIELDNAME} unique: {len(duplicates)} Mollie-style "
        f"reference groups ({total_rows} rows) already share a key.\n\n"
        + "\n".join(lines)
        + "\n\nResolve these rows (they are usually leaked test data or a double booking) "
        "and run `bench migrate` again. This patch stays unrecorded until it succeeds."
    )
    frappe.log_error(title="Mollie idempotency key: duplicates block unique index", message=message)
    frappe.throw(message)


def _backfill():
    rows = frappe.db.sql(
        f"""
        SELECT name, reference_no, payment_type, party
        FROM `tab{DOCTYPE}`
        WHERE {MOLLIE_REFERENCE_SQL_CONDITION}
        """,
        as_dict=True,
    )

    for row in rows:
        key = build_idempotency_key(row.reference_no, row.payment_type, row.party)
        frappe.db.set_value(DOCTYPE, row.name, FIELDNAME, key, update_modified=False)

    # A re-run after the predicate narrowed would otherwise strand a key on a row that is
    # no longer in scope, and that stale key would keep occupying the index.
    frappe.db.sql(
        f"""
        UPDATE `tab{DOCTYPE}`
        SET `{FIELDNAME}` = NULL
        WHERE `{FIELDNAME}` IS NOT NULL AND NOT {MOLLIE_REFERENCE_SQL_CONDITION}
        """
    )
    return len(rows)


def _ensure_unique():
    name = _custom_field_name()
    if frappe.db.get_value("Custom Field", name, "unique"):
        return

    field = frappe.get_doc("Custom Field", name)
    field.unique = 1
    field.save(ignore_permissions=True)
    print(f"Set unique on {DOCTYPE}.{FIELDNAME}")


def _unique_index_exists():
    return bool(
        frappe.db.sql(
            f"SHOW INDEX FROM `tab{DOCTYPE}` WHERE Column_name = %s AND Non_unique = 0",
            FIELDNAME,
        )
    )
