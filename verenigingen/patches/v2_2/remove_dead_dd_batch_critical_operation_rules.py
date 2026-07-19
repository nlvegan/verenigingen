# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove Critical Operation Rules for the dead direct-debit-batch endpoints deleted
in the dues_schedule_manager / direct_debit_batch cleanup.

Four whitelisted @critical_api endpoints were removed as dead code: they formed a
self-referential island with no JS, Python, hooks, scheduler or Server Script
callers, and each was broken against the current schema (a bank-details helper
that only ever returned {}, and selectors that read a `mandate_reference` field
that does not exist on Member). The live direct-debit path is the SEPA Batch UI
(verenigingen.verenigingen_payments.api.sepa_batch_ui).

Because COR is deliberately excluded from the `fixtures` hook, `bench migrate`
never prunes rows already imported into existing sites; removing them from the
fixture file alone does not delete the imported records — this patch does. Rule
names equal the bare function name (autoname `field:operation_name`), and none of
these names has any remaining live definition, so the deletion cannot orphan a
live endpoint's rate-limit configuration.
"""

import frappe

DEAD_RULES = [
    "create_direct_debit_batch_for_unpaid_memberships",
    "generate_direct_debit_batch",
    "add_to_direct_debit_batch",
    "get_unpaid_membership_invoices",
]


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    removed = 0
    for name in DEAD_RULES:
        if frappe.db.exists("Critical Operation Rule", name):
            frappe.delete_doc("Critical Operation Rule", name, ignore_permissions=True, force=True)
            removed += 1

    if removed:
        frappe.db.commit()
        print(f"Removed {removed} dead direct-debit-batch Critical Operation Rule(s)")
