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
from verenigingen.utils.sql_like import escape_sql_like_wildcards

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


def treasurer_users() -> list:
    """Enabled users holding the Treasurer role. A ToDo's ``role`` field gates nothing: Frappe
    shows a non-System-Manager only the ToDos allocated to, assigned by or owned by them."""
    users = frappe.get_all(
        "Has Role", filters={"role": Roles.TREASURER, "parenttype": "User"}, pluck="parent"
    )
    if not users:
        return []
    return frappe.get_all(
        "User",
        filters={"name": ["in", users], "enabled": 1, "user_type": "System User"},
        pluck="name",
    )


def _existing_alert(key: str):
    # The key follows a fixed label and ends the description: either the very end (as written
    # here), or just before a `<` once a desk edit of the Text Editor field wrapped it in HTML
    # (`...Reference: key</p></div>`, #3248). Ids contain no `<`, so both anchors are exact:
    # holding re_12 must not suppress re_1, and `_` in an id is not a wildcard.
    pattern = f"%{_LABEL}{escape_sql_like_wildcards(key)}"
    return frappe.db.get_value("ToDo", {"description": ["like", pattern]}, "name") or frappe.db.get_value(
        "ToDo", {"description": ["like", f"{pattern}<%"]}, "name"
    )


_LABEL = "Reference: "


def hold_unmatched_reversal(
    payment_id: str, reversal_type: str, reversal_id: str, amount: float, bank_transaction: str
) -> str:
    """Record the held reversal as ONE ToDo per Treasurer user; return the first name.

    Idempotent on the reversal key: Mollie redelivers, and staff must be alerted once, not once
    per retry. Any ToDo for the key counts, closed ones included, so a handled item is not
    re-raised by a late redelivery. With no Treasurer user the alert would reach nobody, so that
    is logged to the Error Log instead of passing silently.
    """
    key = build_reversal_key(payment_id, reversal_type, reversal_id)
    existing = _existing_alert(key)
    if existing:
        return existing

    description = _(
        "Mollie {0} {1} of EUR {2} on payment {3} could not be booked: the payment was never "
        "matched to an invoice, so there is no Payment Entry to reverse. Reconcile Bank "
        "Transaction {4} first. Once the payment is matched, the scheduled rediscovery sweep books "
        "the reversal itself, but only within 7 days of the reversal; after that, book it by hand."
    ).format(reversal_type, reversal_id, f"{float(amount):.2f}", payment_id, bank_transaction)
    description = f"{description}\n{_LABEL}{key}"

    recipients = treasurer_users()
    if not recipients:
        frappe.log_error(
            title="Mollie held reversal has no Treasurer to alert",
            message=f"{description}\nNo enabled user holds the {Roles.TREASURER} role.",
        )
        return None

    names = []
    for user in recipients:
        todo = frappe.get_doc(
            {
                "doctype": "ToDo",
                "description": description,
                "priority": "High",
                "status": "Open",
                "allocated_to": user,
                "reference_type": "Bank Transaction",
                "reference_name": bank_transaction,
            }
        )
        todo.insert(ignore_permissions=True)
        names.append(todo.name)
    return names[0]
