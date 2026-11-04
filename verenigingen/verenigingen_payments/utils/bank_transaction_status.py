"""Record this app's reconciliation outcome on a Bank Transaction that is still a draft.

ERPNext owns ``Bank Transaction.status``: from version-16 7526af9b2 ``validate()`` resets a
DRAFT to "Pending" on every save, and a SUBMITTED row's status is derived from
``unallocated_amount`` on submit and on every update-after-submit. Assigning
``bt.status = "Reconciled"`` and saving is therefore overwritten in both cases (#2080).

For a submitted row that is correct and we leave it alone. A draft is different: it exists
when the acting user lacked submit permission, and this app uses its status as a work queue
(``reconcile_bank_transactions`` picks up only "Pending"; a reconciled or failed draft must
leave that pool, or the next run books it again). So persist the outcome with a direct
write AFTER the last ``save()``. It holds only until the next ordinary save of that draft.
"""

import frappe


def persist_draft_status(bank_transaction, status):
    """Write ``status`` onto ``bank_transaction`` if it is a draft; no-op once submitted.

    Call after the final ``save()``: the next save of a draft resets the status to "Pending".
    """
    if bank_transaction.docstatus != 0:
        return
    frappe.db.set_value("Bank Transaction", bank_transaction.name, "status", status, update_modified=False)
    bank_transaction.status = status
