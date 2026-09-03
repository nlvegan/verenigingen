"""
Add unique index on Payment Entry for Mollie payment idempotency.

This patch creates a unique index on the (reference_no, payment_type, party) columns
for Payment Entries with Mollie-style references (tr_*, re_*). This provides
database-level defense against duplicate Payment Entry creation during concurrent
webhook processing.

The index is partial/conditional in intent only - MariaDB has no filtered indexes, so
it actually covers every row and relies on the application only using Mollie-style
references for Mollie payments.

Deliberately raises (via frappe.throw) when pre-existing Mollie-style duplicates block
the index, instead of logging a warning and returning normally. Frappe's patch handler
only records a patch as executed when execute() returns WITHOUT raising (see
frappe.modules.patch_handler.execute_patch: update_patch_log() runs only on the
non-exception path). A version that returns on conflict gets marked done FOREVER even
though it did nothing -- see #746, where exactly that left this index missing on every
site that had leaked Mollie test data at patch time (veg11, test_site_1, test_site_3),
with no way to retry short of manually deleting the Patch Log row. Raising keeps the
patch un-recorded, so a plain `bench migrate` retries it automatically once the
duplicates are actually resolved. Same pattern already used by this app's
v2_2.enforce_unique_user_per_member / enforce_unique_volunteer_per_member.

It does NOT delete or merge the duplicates itself -- choosing which Payment Entry
survives is a data decision, not a migration's call (same reasoning as the patches
above).

KNOWN LIMITATION -- see #809 (filed for this): the duplicate pre-check below only
screens Mollie-style references, matching the scope of #746's own defect (leaked
Mollie test data). It does NOT screen the whole table, because the index itself has no
such filter. A site with a NON-Mollie collision on (reference_no, payment_type, party)
still fails the CREATE UNIQUE INDEX -- confirmed on veg11: 214 such groups / 1070 rows,
from legitimate, intentional reuse of invoice numbers and payroll batch references, not
a data problem to "resolve by hand". That failure is still loud (a real MySQL error, not
swallowed) and the patch still stays un-recorded (still retriable) -- the core #746 fix
-- but it does not, by itself, make the index creatable on such a site.

A generated-column technique to scope the index server-side (VIRTUAL column, NULL for
non-Mollie rows, unique index on the column instead of the raw fields) was built and
verified to work in isolation, then found to be unsafe in THIS app specifically:
Frappe's own schema sync (`MariaDBTable.alter()` in
frappe/database/mariadb/schema.py -- the "logic to drop unique constraint for fields
deleted from a doctype") treats any unique index on a column absent from DocType/Custom
Field metadata as an orphaned leftover and silently DROPS the index (not the column) on
the next customization sync. Verified empirically via a full `bench migrate` on
test_site_3: the index existed immediately after this patch ran, and was gone by the
end of the same migrate, with the generated column still present -- no error, nothing
printed, nothing logged. That is #746's own failure mode recurring in a sneakier form,
so it was reverted rather than shipped. Properly scoping this index needs the
constraint declared through a real Custom Field (populated by a doc hook, backfilled by
a pre_model_sync patch, `unique: 1` -- the same shape as
v2_2.enforce_unique_user_per_member), which is materially larger than #746 asks for.
"""

import frappe

TABLE_NAME = "Payment Entry"
INDEX_NAME = "idx_mollie_payment_ref_unique"

# Single source of truth for "is this a Mollie-style reference" -- the underscore is
# backslash-escaped so 'tr_' means a literal "tr_" prefix, not "tr" + any one character
# + anything (verified empirically: 'trXabc123' LIKE 'tr\_%' is 0, 'tr_abc123' LIKE
# 'tr\_%' is 1).
MOLLIE_STYLE_CONDITION = (
    "(reference_no LIKE 'tr\\_%' OR reference_no LIKE 're\\_%' "
    "OR reference_no LIKE '%\\_refund\\_%' OR reference_no LIKE '%\\_chargeback\\_%')"
)


def execute():
    """Add unique index on Payment Entry for Mollie idempotency, or explain why not."""
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

    print(f"Creating unique index {INDEX_NAME} on tab{TABLE_NAME}")
    print("Purpose: Prevent duplicate Mollie Payment Entries during concurrent processing")

    # sql_ddl(): CREATE INDEX autocommits in MariaDB, so running it through
    # frappe.db.sql() risks ImplicitCommitError if a write is already pending in this
    # migration's transaction. sql_ddl() commits first, then runs the DDL.
    frappe.db.sql_ddl(
        f"""
        CREATE UNIQUE INDEX `{INDEX_NAME}`
        ON `tab{TABLE_NAME}` (reference_no, payment_type, party)
        """
    )

    print(f"Successfully created unique index {INDEX_NAME}")


def _index_exists():
    return bool(
        frappe.db.sql(
            f"SHOW INDEX FROM `tab{TABLE_NAME}` WHERE Key_name = %s",
            [INDEX_NAME],
        )
    )


def _find_duplicates():
    """Duplicate (reference_no, payment_type, party) among Mollie-style references only.

    See module docstring's KNOWN LIMITATION: this deliberately does not screen the
    whole table, only the Mollie-style population #746 was filed about. A non-Mollie
    collision is not caught here -- it surfaces as a raw error from the CREATE UNIQUE
    INDEX itself instead, which is still loud and still leaves the patch un-recorded.

    Does NOT exclude cancelled rows (docstatus == 2): the real CREATE UNIQUE INDEX does
    not exempt them either -- MariaDB's uniqueness enforcement has no concept of
    docstatus, so a cancelled Payment Entry with a matching reference still collides.
    An earlier version of this function excluded docstatus == 2 on the theory that "a
    cancelled entry is not a live conflict" -- true for the application's business
    logic, false for what the DDL actually enforces. Verified empirically: a docstatus=1
    and a docstatus=2 row sharing one (reference_no, payment_type, party) were invisible
    to a docstatus-filtered version of this query, and the resulting CREATE UNIQUE INDEX
    then failed with a raw, unlogged MySQL 1062 instead of this function's actionable
    report -- for what is otherwise this patch's core, documented use case. Also
    reachable in practice: verenigingen/utils/migration/migration_duplicate_detection.py
    cancels a duplicate Payment Entry and only deletes it when it has no GL Entries,
    so a "resolved" duplicate commonly ends up as exactly this shape (one cancelled, one
    active, same reference).
    """
    return frappe.db.sql(
        f"""
        SELECT reference_no, payment_type, party, COUNT(*) as count
        FROM `tab{TABLE_NAME}`
        WHERE {MOLLIE_STYLE_CONDITION}
        GROUP BY reference_no, payment_type, party
        HAVING count > 1
        """,
        as_dict=True,
    )


def _abort_on_duplicates(duplicates):
    """Stop the migration with an actionable list rather than let it look done.

    See module docstring: this patch owns its own index (unlike a `unique: 1`
    DocType field, it has no schema sync to stop), so it CAN decline to create the
    index -- but declining must be loud. #746 is what "quiet decline" costs: the
    guarantee this index exists for is silently absent, indefinitely.
    """
    shown = duplicates[:10]
    lines = [f"  - {d.reference_no} ({d.payment_type}, {d.party}): {d.count} entries" for d in shown]
    if len(duplicates) > len(shown):
        lines.append(f"  ... and {len(duplicates) - len(shown)} more")
    detail = "\n".join(lines)

    message = (
        f"Cannot create unique index {INDEX_NAME}: found {len(duplicates)} duplicate Mollie "
        f"Payment Entry reference(s).\n\n{detail}\n\n"
        "Resolve the duplicates by hand (review and delete the extras -- cancelling alone will "
        "not resolve this, since a cancelled Payment Entry still collides with the unique "
        "index; which one should survive is a data decision this patch will not make for "
        "you), then re-run "
        "`bench migrate`. This patch is not recorded as executed until it succeeds, so it "
        "will retry automatically. Query to find duplicates:\n"
        "  SELECT name, reference_no, payment_type, party, docstatus FROM `tabPayment Entry` "
        "WHERE reference_no LIKE 'tr_%' ORDER BY reference_no, creation"
    )

    frappe.log_error(title="Mollie Payment Entry Unique Index - Duplicates Found", message=message)
    frappe.throw(message)
