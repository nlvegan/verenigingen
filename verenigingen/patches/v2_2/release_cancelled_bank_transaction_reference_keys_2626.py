"""Release the #1267 reference key held by already-cancelled Bank Transactions (#2626).

A cancelled Bank Transaction now frees its `custom_reference_number_key` when it is cancelled
(`release_bank_transaction_reference_key`). Rows cancelled before that change still hold it, so
rebooking their Mollie reference would still die on IntegrityError 1062. Only docstatus 2 rows
are touched; their `reference_number` stays as the audit trail. Idempotent.

The column is installed by a fixture, which syncs AFTER post_model_sync patches, so it can be
absent on a site's first migrate; there is nothing to release then.
"""

import frappe

from verenigingen.verenigingen_payments.utils.bank_transaction_reference_key import FIELDNAME

DOCTYPE = "Bank Transaction"


def execute():
    if not frappe.db.table_exists(DOCTYPE) or not frappe.db.has_column(DOCTYPE, FIELDNAME):
        return

    frappe.db.sql(
        f"UPDATE `tab{DOCTYPE}` SET `{FIELDNAME}` = NULL WHERE docstatus = 2 AND `{FIELDNAME}` IS NOT NULL"
    )
