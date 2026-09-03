"""Retry the Mollie/Bank Transaction unique-index patches that could get stuck (#746).

`add_mollie_payment_entry_unique_index` and `add_bank_transaction_reference_unique_index`
used to log a warning and return normally when pre-existing duplicates blocked their
index. Frappe's patch handler only records a patch as executed when execute() returns
WITHOUT raising (frappe.modules.patch_handler.execute_patch), so that "declined" run was
indistinguishable from "done": it got recorded in Patch Log, and neither `bench migrate`
nor a fresh run would ever look again. Confirmed on veg11, test_site_1 and test_site_3
(#746): both indexes were absent, both patches were recorded as executed.

Both patches are now idempotent and safe to call again (see their fixed source): skip if
the index already exists, raise loudly (leaving the patch un-recorded) if duplicates still
block creation, create the index otherwise. That fix reaches a FRESH install on its own --
a site that hasn't run the old patch yet just gets the corrected behaviour the first time.
It does NOT reach a site where the buggy version already ran and got marked done; nothing
will ever call execute() again for a patch name Frappe believes finished. This patch
re-invokes both functions under a name that has never been recorded, which is the only way
to actually reach those already-migrated sites.

Attempts both regardless of whether one fails, so a duplicate blocking one table doesn't
hide a report on the other; raises (and so stays un-recorded, retrying on the next
`bench migrate`) if either could not complete.
"""

import frappe

from verenigingen.patches.v2_1.add_bank_transaction_reference_unique_index import (
    execute as ensure_bank_transaction_index,
)
from verenigingen.patches.v2_1.add_mollie_payment_entry_unique_index import (
    execute as ensure_mollie_payment_entry_index,
)


def execute():
    failures = []

    for label, ensure_index in (
        ("Mollie Payment Entry unique index", ensure_mollie_payment_entry_index),
        ("Bank Transaction unique index", ensure_bank_transaction_index),
    ):
        try:
            ensure_index()
        except Exception as e:
            # The duplicates-found path already calls frappe.log_error with a detailed
            # report; an unexpected failure (a real DB error, a lock timeout) has not
            # been logged by anything yet. Log a traceback here unconditionally rather
            # than try to tell the two apart -- a duplicate Error Log entry costs
            # nothing, an unexpected failure with only `str(e)` and no traceback is
            # much harder to diagnose than it needs to be.
            frappe.log_error(
                title=f"Retry Mollie/Bank Transaction Unique Index - {label} failed",
                message=frappe.get_traceback(with_context=True),
            )
            failures.append(f"{label}: {e}")

    if failures:
        frappe.throw("\n\n".join(failures))
