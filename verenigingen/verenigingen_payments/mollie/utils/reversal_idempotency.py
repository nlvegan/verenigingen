"""
Has this Mollie reversal already been booked -- as ANY artefact?

A refund or chargeback can reach us by more than one route, and the routes book
different doctypes under the *same* reference key:

    payment-webhook sweep   -> Bank Transaction + Journal Entry  (cheque_no)
    refund webhook          -> Payment Entry                     (reference_no)

Each route only ever checked its own doctype, so a refund already booked as a
Journal Entry was booked again as a Payment Entry (#370). The key was never the
problem -- both routes build the identical string. The lookup was.

Note the ``docstatus != 2`` predicate. This answers "has this reversal been
booked?", which is not the same question as "was the original payment booked?".
A *draft* artefact is work already in flight, so treating it as absent is what
produces the second booking; only a cancelled one frees the key. (The forward
"was this payment booked?" predicate is submitted-only, deliberately -- a draft
forward booking is not a payment.)
"""

from typing import Optional, Tuple

import frappe

#: (doctype, field carrying the reversal key)
_REVERSAL_ARTEFACTS = (
    ("Journal Entry", "cheque_no"),
    ("Payment Entry", "reference_no"),
)


def build_reversal_key(payment_id: str, reversal_type: str, reversal_id: str) -> str:
    """The one reference string every reversal route must agree on."""
    return f"{payment_id}_{reversal_type}_{reversal_id}"


def find_booked_reversal(reversal_key: str) -> Optional[Tuple[str, str]]:
    """Return ``(doctype, name)`` of an existing booking for this key, or None.

    Checks every artefact a reversal can be booked as, not just the caller's own.
    """
    if not reversal_key:
        return None

    for doctype, field in _REVERSAL_ARTEFACTS:
        existing = frappe.db.get_value(doctype, {field: reversal_key, "docstatus": ["!=", 2]}, "name")
        if existing:
            return doctype, existing

    return None
