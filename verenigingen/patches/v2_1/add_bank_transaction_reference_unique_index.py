"""
Add unique index on Bank Transaction reference_number field.

This ensures that Mollie payment processors cannot create duplicate Bank Transactions
when processing the same payment via different APIs (DuesPaymentProcessor,
BalanceTransactionProcessor, etc.).

Deliberately raises (via frappe.throw) when pre-existing duplicates block the index,
instead of logging a warning and returning normally. Frappe's patch handler only
records a patch as executed when execute() returns WITHOUT raising (see
frappe.modules.patch_handler.execute_patch: update_patch_log() runs only on the
non-exception path). A version that returns on conflict gets marked done FOREVER even
though it did nothing -- same defect class as #746 (add_mollie_payment_entry_unique_index),
and confirmed to have actually happened here too: on test_site_3 this patch was already
recorded as executed, the index did not exist, and no duplicates remained to explain the
bail-out -- calling execute() directly created the index immediately with no changes to
the data. Raising keeps the patch un-recorded, so a plain `bench migrate` retries it
automatically once any duplicates are resolved.

Does NOT delete or merge duplicates itself -- choosing which Bank Transaction survives
is a data decision, not a migration's call.
"""

import frappe

TABLE_NAME = "Bank Transaction"
INDEX_NAME = "idx_reference_number_unique"


def execute():
    if not frappe.db.table_exists(TABLE_NAME):
        print(f"Table tab{TABLE_NAME} doesn't exist - skipping unique index creation")
        return

    if _index_exists():
        print(f"Unique index {INDEX_NAME} already exists on tab{TABLE_NAME}")
        return

    duplicates = _find_duplicates()
    if duplicates:
        _abort_on_duplicates(duplicates)
        return  # pragma: no cover - _abort_on_duplicates always raises

    print(f"Adding unique index {INDEX_NAME} on tab{TABLE_NAME}(reference_number)")
    print("Purpose: Prevent duplicate Bank Transactions across Mollie payment APIs")

    # sql_ddl(): ALTER TABLE autocommits in MariaDB; frappe.db.sql() would raise
    # ImplicitCommitError mid-migration if a write is already pending in this
    # migration's transaction.
    frappe.db.sql_ddl(f"ALTER TABLE `tab{TABLE_NAME}` ADD UNIQUE INDEX `{INDEX_NAME}` (`reference_number`)")

    print(f"Successfully added unique index {INDEX_NAME}")


def _index_exists():
    return bool(
        frappe.db.sql(
            f"SHOW INDEX FROM `tab{TABLE_NAME}` WHERE Key_name = %s",
            [INDEX_NAME],
        )
    )


def _find_duplicates():
    """Duplicate reference_number values the unique index would reject.

    Only excludes NULL, not blank string. MariaDB/InnoDB exempts NULL entries from a
    unique index, but '' is a real value: two rows with reference_number='' collide
    under the actual index exactly like any other matching pair. Excluding '' here
    would let that case slip past this check and fail with a raw, unhelpful MySQL 1062
    instead of this function's actionable report (same defect class as #746's Mollie
    sibling, where an earlier version of this same mistake was caught before merge).
    """
    return frappe.db.sql(
        f"""
        SELECT reference_number, COUNT(*) as count
        FROM `tab{TABLE_NAME}`
        WHERE reference_number IS NOT NULL
        GROUP BY reference_number
        HAVING count > 1
        """,
        as_dict=True,
    )


def _abort_on_duplicates(duplicates):
    """Stop the migration with an actionable list rather than let it look done.

    See module docstring: this patch owns its own index (no DocType-level `unique: 1`
    forcing a schema sync it can't stop), so it CAN decline to create the index -- but
    declining must be loud, not indistinguishable from success. See #746.
    """
    shown = duplicates[:10]
    lines = [f"  - {d.reference_number}: {d.count} occurrences" for d in shown]
    if len(duplicates) > len(shown):
        lines.append(f"  ... and {len(duplicates) - len(shown)} more")
    detail = "\n".join(lines)

    message = (
        f"Cannot create unique index {INDEX_NAME}: found {len(duplicates)} duplicate "
        f"reference_number value(s) in Bank Transaction.\n\n{detail}\n\n"
        "Resolve the duplicates by hand (review and merge/delete the extras -- which one "
        "should survive is a data decision this patch will not make for you), then re-run "
        "`bench migrate`. This patch is not recorded as executed until it succeeds, so it "
        "will retry automatically."
    )

    frappe.log_error(title="Bank Transaction Unique Index Migration - Duplicates Found", message=message)
    frappe.throw(message)
