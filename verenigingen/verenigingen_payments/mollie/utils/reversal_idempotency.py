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
from frappe.utils import flt

#: (doctype, field carrying the reversal key)
_REVERSAL_ARTEFACTS = (
    ("Journal Entry", "cheque_no"),
    ("Payment Entry", "reference_no"),
)


def build_reversal_key(payment_id: str, reversal_type: str, reversal_id: str) -> str:
    """The one reference string every reversal route must agree on."""
    return f"{payment_id}_{reversal_type}_{reversal_id}"


def total_reversed(payment_id: str) -> float:
    r"""How much of this payment has ALREADY been reversed, as any artefact.

    Every reversal key is ``{payment_id}_{reversal_type}_{reversal_id}``, so this
    is a prefix scan over the same two fields :func:`find_booked_reversal` reads.

    The prefix is escaped because ``_`` and ``%`` are LIKE wildcards and a Mollie
    payment id *contains* an underscore: unescaped, ``tr_abc\_%`` would also
    match reversals of ``trXabc``. MariaDB's default LIKE escape is ``\``.

    Drafts count, cancelled do not -- the same predicate as
    :func:`find_booked_reversal`, and for the same reason: a draft is a booking
    already in flight.

    Why this exists: the per-delivery "not more than the payment" check is not
    the property anyone means. A refund and a chargeback are different
    ``reversal_type``s, so they get different keys and both book; two reversals
    that each pass a per-delivery check can still sum above the payment. And
    ERPNext will not catch it -- ``journal_entry.validate_reference_doc`` totals
    a Sales Invoice reference by its **credit** column, so a reversal's
    debit-side reference rows total 0.0 and ``validate_invoices``' over-allocation
    guard is skipped entirely (``if total and ...``). Nothing downstream stands
    between a second reversal and a receivable restored above the invoice.
    """
    if not payment_id:
        return 0.0

    escaped = payment_id.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%")
    prefix = f"{escaped}\\_%"

    total = 0.0
    for doctype, key_field, amount_field in (
        ("Journal Entry", "cheque_no", "total_debit"),
        ("Payment Entry", "reference_no", "paid_amount"),
    ):
        for row in frappe.get_all(
            doctype,
            filters={key_field: ["like", prefix], "docstatus": ["!=", 2]},
            fields=[amount_field],
        ):
            total += flt(row.get(amount_field))

    return flt(total, 2)


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


# --------------------------------------------------------------------------
# What did the FORWARD payment book?
# --------------------------------------------------------------------------
#
# The reversal path used to ask "is there a Payment Entry for this payment?" and
# treat "no" as "the payment does not exist". Donations book a Journal Entry, so
# that question answered "no" for every donation and the endpoint reported
# "original payment not found" (#370).
#
# It also used to decide the payment's TYPE by re-running PaymentClassifier over
# the Mollie payment object. That is not stable over time: the donation forward
# path overwrites Donor.mollie_subscription_id / mollie_customer_id on every
# webhook, Member.mollie_subscription_id is cleared on cancellation and
# overwritten on re-subscription, and the keyword rule reads editable settings.
# Chargeback windows run months, so a reversal could classify differently from
# the booking it is meant to reverse. What was booked is already a recorded fact;
# read that instead of re-deriving it.

#: More than one type appears to have booked this payment.
AMBIGUOUS = "ambiguous"


def find_booked_payment(payment_id: str) -> Optional[Tuple[str, str, str]]:
    """What did the forward payment book? ``(payment_type, doctype, name)`` or None.

    ``payment_type`` is ``"donation"``, ``"dues"``, or :data:`AMBIGUOUS`.
    ``doctype``/``name`` identify the artefact that booked it.

    Submitted only, deliberately: a draft forward booking is not a payment. This
    is the opposite of :func:`find_booked_reversal`, which counts drafts because
    it is answering "is a booking already in flight?".

    **The Donation record decides donation-ness, not the artefact shape.** Today a
    donation books a Journal Entry and dues book a Payment Entry, so it is
    tempting to read the type straight off the doctype -- but donations booked as
    Payment Entries exist (that was the older donation flow, and the refund /
    chargeback integration fixtures still build one). Reading the artefact alone
    misfiles such a donation as dues and reverses it against a membership
    invoice that money never paid. So: ask whether a Donation claims this
    payment, then ask what booked it.
    """
    if not payment_id:
        return None

    donation = frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")
    journal_entry = frappe.db.get_value("Journal Entry", {"cheque_no": payment_id, "docstatus": 1}, "name")
    payment_entry = frappe.db.get_value(
        "Payment Entry",
        {"reference_no": payment_id, "payment_type": "Receive", "docstatus": 1},
        "name",
    )

    # Booked as BOTH is genuinely ambiguous: we cannot tell which one carries the
    # money without guessing, and guessing is how this bug class started. This is
    # checked BEFORE asking whether a Donation exists -- ambiguity is a property of
    # the bookings, not of the Donation. Behind the `if donation:` split it let the
    # no-Donation case fall through to "prefer the Payment Entry, call it dues",
    # which is precisely the behaviour this branch exists to prevent.
    if journal_entry and payment_entry:
        return (AMBIGUOUS, "Journal Entry", journal_entry)

    if donation:
        if journal_entry:
            return ("donation", "Journal Entry", journal_entry)
        if payment_entry:
            return ("donation", "Payment Entry", payment_entry)
        return None

    if payment_entry:
        return ("dues", "Payment Entry", payment_entry)
    if journal_entry:
        # A donation-shaped booking with no Donation behind it. Report it as a
        # donation so the caller hits its orphaned-booking branch and says so,
        # rather than silently treating it as dues.
        return ("donation", "Journal Entry", journal_entry)

    return None
