# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove Critical Operation Rules for the dead performance-optimization endpoints
deleted in the payment-history double-write reconciliation.

The synchronous ``performance_event_handlers.on_member_payment_update`` hook
(which called ``OptimizedMemberQueries.bulk_update_payment_history`` to rebuild
the whole Member Payment History child table inside the Payment Entry / Sales
Invoice submit transaction) was redundant with the async batch/drain path and a
source of row-lock contention. It was unwired, and the stranded dead code was
pruned: the entire ``OptimizedMemberQueries`` class, the member-payment functions
in ``performance_event_handlers``, and the ``performance_integration`` scaffold
module (whose only non-test importer referenced a symbol that never existed).

That removed eight whitelisted endpoints, each of which had a Critical Operation
Rule (COR autoname is ``field:operation_name``, so the rule name equals the bare
function name). Because COR is deliberately excluded from the ``fixtures`` hook,
``bench migrate`` never prunes rows already imported into existing sites; removing
them from the fixture file alone does not delete the imported records — this patch
does. None of these names has any remaining whitelisted / @critical_api endpoint
definition, so the deletion cannot orphan a live endpoint's rate-limit
configuration. (An unrelated, undecorated ``BulkInvoiceGenerationService`` instance
method also happens to be named ``bulk_update_payment_history``; having no security
decorator it is never matched to a Critical Operation Rule, so it is unaffected.)
"""

import frappe

DEAD_RULES = [
    "bulk_update_payment_history",
    "get_member_financial_summary",
    "optimize_member_payment_history_update",
    "trigger_member_optimization",
    "get_performance_system_status",
    "install_safe_performance_optimizations",
    "trigger_member_bulk_optimization",
    "uninstall_performance_optimizations",
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
        print(f"Removed {removed} dead performance-optimization Critical Operation Rule(s)")
