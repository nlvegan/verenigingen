"""Install the Bank Transaction per-account reference uniqueness key (#1267).

Replaces `patches/v2_1/add_bank_transaction_reference_unique_index.py`, which is retired
(see the comment in `patches.txt`). That patch had three problems, all fixed here:

1. It was one-shot: recorded in `Patch Log` the moment `execute()` returned, whether or not
   it actually created the index. A duplicate present for the duration of a single `migrate`
   -- including one left behind by a test fixture -- permanently disabled the index on that
   site, and cleaning the duplicate up afterwards never brought it back. This patch checks
   for its own effect (`_unique_index_exists()`) every run instead of trusting `Patch Log`.
2. On a duplicate, it printed a warning and returned normally -- indistinguishable from a
   successful run, and `bench migrate` continued as if the guarantee were in place. This
   patch raises (see `_abort_on_duplicates`), so it stays unrecorded and retries.
3. Its uniqueness scope was global (`reference_number` alone), which the maintainer decision
   on #1267 rejects: `reference_number` is legitimately reused across bank accounts (measured
   on veg11 by account: `EB-<mutation_id>`, Mollie `tr_`/`stl_`/`baltr_`, Ponto ids, MT940
   bank references -- none of them coordinated across accounts), and
   `bank_transaction_creator.py`'s own idempotency lookup is scoped to `(bank_account,
   reference_number)` for the same reason (#383). This patch installs that narrower scope
   via `bank_transaction_reference_key.py`'s derived key instead.

Sequence matters and is not the obvious one, exactly as in #809 (the sibling Mollie Payment
Entry guard this patch is modelled on): the Custom Field is created WITHOUT `unique`, existing
rows are backfilled, and only then is `unique` set. Creating it unique first would work (the
column starts all-NULL) but would then surface any collision one row at a time, as a raw DB
error in the middle of the backfill, instead of as one report naming every offending group.

Raises rather than declining, for the reason given in point 2 above: a patch that logs and
returns is indistinguishable from one that did the work (#746, #1267's exact repeat of it).
Raising leaves this patch unrecorded, so the next `bench migrate` tries again.

Also drops the legacy `idx_reference_number_unique` global index, if a previous run of the
retired v2_1 patch created it. Left in place, it is a STRICTER constraint than the one this
patch installs and would keep rejecting the exact cross-account reference reuse #1267 decided
must be allowed -- so simply not creating it going forward is not enough on a site where it
already exists.

It does NOT delete or merge duplicates. Choosing which Bank Transaction survives is a data
decision with reconciliation consequences, not a migration's call -- same disposition as
`add_mollie_payment_entry_idempotency_key`.

The Custom Field lifecycle (create unmarked -> backfill -> flip unique -> verify the index)
is shared with `add_mollie_payment_entry_idempotency_key.py` (#809) via
`verenigingen.utils.unique_custom_field_patch` -- see that module's docstring for why it was
extracted rather than left as two copies.
"""

import frappe

from verenigingen.utils.unique_custom_field_patch import (
    ensure_unique,
    get_custom_field_name,
    unique_index_exists,
)
from verenigingen.verenigingen_payments.utils.bank_transaction_reference_key import (
    FIELDNAME,
    IN_SCOPE_SQL_CONDITION,
    build_reference_key,
)

DOCTYPE = "Bank Transaction"
LEGACY_GLOBAL_INDEX = "idx_reference_number_unique"


def execute():
    if not frappe.db.table_exists(DOCTYPE):
        print(f"tab{DOCTYPE} does not exist - skipping {FIELDNAME}")
        return

    _drop_legacy_global_index()
    _ensure_field_exists()

    duplicates = _find_duplicates()
    if duplicates:
        _abort_on_duplicates(duplicates)

    updated = _backfill()
    print(f"Backfilled {FIELDNAME} on {updated} Bank Transactions with a bank account and reference")

    if ensure_unique(DOCTYPE, FIELDNAME):
        print(f"Set unique on {DOCTYPE}.{FIELDNAME}")

    if not unique_index_exists(DOCTYPE, FIELDNAME):
        frappe.throw(
            f"{FIELDNAME} is marked unique but no unique index exists on tab{DOCTYPE}. "
            "The schema sync did not create it; do not treat this guard as active."
        )
    print(f"Unique index on {DOCTYPE}.{FIELDNAME} is in place")


def _drop_legacy_global_index():
    existing = frappe.db.sql(f"SHOW INDEX FROM `tab{DOCTYPE}` WHERE Key_name = %s", LEGACY_GLOBAL_INDEX)
    if not existing:
        return

    # sql_ddl(): ALTER autocommits in MariaDB; frappe.db.sql() would raise
    # ImplicitCommitError mid-migration.
    frappe.db.sql_ddl(f"ALTER TABLE `tab{DOCTYPE}` DROP INDEX `{LEGACY_GLOBAL_INDEX}`")
    print(
        f"Dropped legacy global unique index {LEGACY_GLOBAL_INDEX} on {DOCTYPE} "
        f"(superseded by the per-account {FIELDNAME}; see #1267)"
    )


def _ensure_field_exists():
    if get_custom_field_name(DOCTYPE, FIELDNAME):
        return

    frappe.get_doc(
        {
            "doctype": "Custom Field",
            "dt": DOCTYPE,
            "fieldname": FIELDNAME,
            "label": "Reference Number Key",
            "fieldtype": "Data",
            "hidden": 1,
            "read_only": 1,
            "no_copy": 1,
            "print_hide": 1,
            # unique is set only after the backfill - see the module docstring.
            "unique": 0,
            "insert_after": "reference_number",
            "description": (
                "Derived key that turns reference_number unique PER bank_account into a "
                "database constraint instead of a check-then-act. NULL when reference_number "
                "or bank_account is blank (see #1267)."
            ),
        }
    ).insert(ignore_permissions=True)
    print(f"Created Custom Field {DOCTYPE}.{FIELDNAME}")


def _find_duplicates():
    """Rows sharing one (bank_account, reference_number).

    Deliberately does NOT exclude cancelled rows: a unique index has no docstatus predicate,
    so a cancelled Bank Transaction still occupies the key.
    """
    return frappe.db.sql(
        f"""
        SELECT bank_account, reference_number, COUNT(*) AS count
        FROM `tab{DOCTYPE}`
        WHERE {IN_SCOPE_SQL_CONDITION}
        GROUP BY bank_account, reference_number
        HAVING count > 1
        ORDER BY count DESC
        """,
        as_dict=True,
    )


def _abort_on_duplicates(duplicates):
    lines = [f"  {d.bank_account!r} / {d.reference_number!r} x{d.count}" for d in duplicates[:20]]
    if len(duplicates) > 20:
        lines.append(f"  ... and {len(duplicates) - 20} more groups")

    total_rows = sum(d.count for d in duplicates)
    message = (
        f"Cannot make {DOCTYPE}.{FIELDNAME} unique: {len(duplicates)} (bank_account, "
        f"reference_number) groups ({total_rows} rows) already collide.\n\n"
        + "\n".join(lines)
        + "\n\nResolve these rows (they are usually leaked test data or a genuine double "
        "booking) and run `bench migrate` again. This patch stays unrecorded until it "
        "succeeds."
    )
    frappe.log_error(title="Bank Transaction reference key: duplicates block unique index", message=message)
    frappe.throw(message)


def _backfill():
    rows = frappe.db.sql(
        f"""
        SELECT name, bank_account, reference_number
        FROM `tab{DOCTYPE}`
        WHERE {IN_SCOPE_SQL_CONDITION}
        """,
        as_dict=True,
    )

    for row in rows:
        key = build_reference_key(row.bank_account, row.reference_number)
        frappe.db.set_value(DOCTYPE, row.name, FIELDNAME, key, update_modified=False)

    # A re-run after the predicate narrowed would otherwise strand a key on a row that is no
    # longer in scope, and that stale key would keep occupying the index.
    frappe.db.sql(
        f"""
        UPDATE `tab{DOCTYPE}`
        SET `{FIELDNAME}` = NULL
        WHERE `{FIELDNAME}` IS NOT NULL AND NOT {IN_SCOPE_SQL_CONDITION}
        """
    )
    return len(rows)
