# Copyright (c) 2026, Verenigingen
# License: MIT

"""Language-independent detection of "this invoice can no longer absorb this payment".

ERPNext signals a lost allocation race with a ``frappe.ValidationError`` carrying one
of two messages:

* ``_("{0} {1} has already been fully paid.")`` - raised by
  ``validate_allocated_amount_with_latest_data`` when the latest outstanding is <= 0
* ``_("Row #{0}: Allocated Amount cannot be greater than outstanding amount.")`` -
  raised when the allocation exceeds what is left

Both are wrapped in ``_()``. Every caller in this app matched them with English
substring tests (``"already been fully paid" in str(e)``), which works only while the
site language is English. On a Dutch installation - which is the entire point of this
app - the match fails, the exception propagates, and a payment that has ALREADY BEEN
TAKEN by the PSP is recorded nowhere.

Matching the translated string instead would be no better: it makes the money path
depend on a translation file staying byte-identical to a string in ERPNext.

So do not parse the message at all. Both errors mean exactly one thing - the invoice's
current outstanding amount cannot absorb the amount being allocated - and that is a
question the database answers directly, in any language.
"""

import frappe
from frappe.utils import flt


def any_reference_cannot_absorb(payment_entry) -> bool:
    """Return True when ANY invoice referenced by ``payment_entry`` is over-allocated.

    For callers that allocate across several invoices at once and cannot say which one
    lost the race. Covers Purchase Invoice as well, since the same two ERPNext messages
    are raised for both directions.
    """
    for reference in payment_entry.get("references") or []:
        if reference.reference_doctype not in ("Sales Invoice", "Purchase Invoice"):
            continue
        if invoice_cannot_absorb(
            reference.reference_name,
            reference.allocated_amount,
            doctype=reference.reference_doctype,
        ):
            return True

    return False


def invoice_cannot_absorb(invoice_name: str, amount, doctype: str = "Sales Invoice") -> bool:
    """Return True when ``invoice_name`` can no longer absorb an allocation of ``amount``.

    Reads the invoice's CURRENT outstanding amount, which is the state the concurrent
    writer left behind. Callers use this in an ``except frappe.ValidationError`` handler
    to decide whether the failure was a lost race (recover by recording the payment
    unallocated) or something else (re-raise).

    A missing invoice counts as "cannot absorb": it cannot take the allocation either,
    and the caller's recovery path is the correct destination.

    This must be read AFTER the failed attempt has been rolled back to a savepoint,
    otherwise the query runs on a transaction the failure already poisoned. Every
    caller here goes through PaymentEntryCreationService, which does exactly that.
    """
    outstanding = frappe.db.get_value(doctype, invoice_name, "outstanding_amount")
    if outstanding is None:
        return True

    return flt(outstanding) < flt(amount)
