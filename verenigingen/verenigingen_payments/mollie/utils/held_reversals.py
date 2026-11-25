"""Hold a refund/chargeback whose forward payment matched no invoice (#2542).

A dues payment that matched no open invoice is booked as a Bank Transaction only
(#1803). A reversal needs a forward Payment Entry to reverse, so none can be booked
for it, and answering 500 just makes Mollie retry for ~26h with the same outcome.
Maintainer ruling (2026-11-25): hold it and alert staff. Nothing is auto-booked;
staff reconcile the Bank Transaction and book the reversal by hand.
"""

import frappe
from frappe import _

from verenigingen.utils.constants import Roles

from .reversal_idempotency import build_reversal_key


def unmatched_payment_bank_transaction(payment_id: str):
    """The Bank Transaction holding a payment that was never matched to an invoice, or None.

    A payment with a Donation is excluded: its reversal belongs to the donation path.
    """
    if not payment_id or frappe.db.exists("Donation", {"payment_id": payment_id}):
        return None
    return frappe.db.get_value(
        "Bank Transaction", {"reference_number": payment_id, "docstatus": ["!=", 2]}, "name"
    )


def hold_unmatched_reversal(
    payment_id: str, reversal_type: str, reversal_id: str, amount: float, bank_transaction: str
) -> str:
    """Record the held reversal as ONE open ToDo for the treasurer; return its name.

    Idempotent on the reversal key, which is written into the description: Mollie
    redelivers, and staff must be alerted once, not once per retry. Any ToDo for the key
    counts, closed ones included, so a handled item is not re-raised by a late redelivery.
    """
    key = build_reversal_key(payment_id, reversal_type, reversal_id)
    existing = frappe.db.get_value("ToDo", {"description": ["like", f"%{key}%"]}, "name")
    if existing:
        return existing

    todo = frappe.get_doc(
        {
            "doctype": "ToDo",
            "description": _(
                "Mollie {0} {1} of EUR {2} on payment {3} could not be booked: the payment was never "
                "matched to an invoice, so there is no Payment Entry to reverse. Reconcile Bank "
                "Transaction {4} first, then book the reversal by hand. Reference: {5}"
            ).format(reversal_type, reversal_id, f"{float(amount):.2f}", payment_id, bank_transaction, key),
            "priority": "High",
            "status": "Open",
            "role": Roles.TREASURER,
            "reference_type": "Bank Transaction",
            "reference_name": bank_transaction,
        }
    )
    todo.insert(ignore_permissions=True)
    return todo.name
