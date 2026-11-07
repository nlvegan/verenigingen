# Copyright (c) 2026, Verenigingen
# License: MIT

"""
Shared ownership-verification helpers for guest-reachable payment reference
resolution.

Two guest-reachable (``@frappe.whitelist(allow_guest=True)``) endpoints
resolve a caller-supplied ``(reference_doctype, reference_name)`` pair and
must verify the caller owns that document before doing anything further
(most importantly, before reaching a real payment gateway call):

- verenigingen_payments.templates.pages.mollie_checkout.make_payment
  (#1032, PR #1047)
- verenigingen_payments.hooks.api.initiate_payment (#1048)

Both resolve the reference through ``load_owned_reference`` (#2045): an unknown
reference and an existing one the caller does not own are refused IDENTICALLY, on
every channel a Guest can read (see that function).

The logic was first written in mollie_checkout.py and copy-pasted into
hooks/api.py for #1048, which tripped
scripts/validation/duplicate_helper_validator.py's ratchet (two
identically-named private helpers). Extracted here instead of baselining
the duplication -- import these rather than re-copying a third time.
"""

import frappe
from frappe import _

# DocTypes eligible for a guest-initiated payment against a specific
# document, mapped (in _owner_email_on_file) to the field that
# holds the email address on file for that document. This is a NARROWER,
# independently-verified list than
# verenigingen.templates.pages.payment_success.ALLOWED_PAYMENT_DOCTYPES --
# that set includes "Member Application", which is not an installed DocType
# in this app (confirmed via frappe.db.exists("DocType", "Member
# Application") == False), so it was dropped here rather than imported and
# left permanently unreachable. Grepped app-wide for
# reference_doctype="..." call sites (#1032): these three are the only
# payment-bearing doctypes with a resolvable owner email.
ALLOWED_REFERENCE_DOCTYPES = {"Donation", "Sales Invoice", "Payment Plan Payment"}


class PaymentReferenceRefused(frappe.ValidationError):
    """The one refusal for every way a guest-supplied payment reference can be unusable."""


# Columns holding the owner's email, read by name without loading the document.
_OWNER_EMAIL_COLUMN = {"Donation": "donor_email", "Sales Invoice": "contact_email"}


def load_owned_reference(reference_doctype: str, reference_name: str, payer_email: str):
    """Return the reference document, but only if payer_email matches its on-file email.

    Guest-reachable by design (a payer has no session before their payment
    succeeds), so the on-file email is the only ownership signal available --
    mirrors donate.py's PublicDonationService._verify_donor_email_matches (#969).

    An unknown name, an existing document the caller does not own, a doctype
    outside ALLOWED_REFERENCE_DOCTYPES and a missing/blank email all raise the
    SAME PaymentReferenceRefused, and do the same work first (#2045): ownership is
    decided from ONE lightweight read by name, never from ``frappe.get_doc``. The
    old get_doc-then-compare shape told a Guest an unknown name apart from a real
    one through ``_server_messages`` (get_doc's own "X not found" is queued by
    ``frappe.throw`` before it raises), through the Error Log text and through the
    query count (a real document costs its child-table reads). The refusal is a
    plain ``raise``, so nothing is queued in ``frappe.local.message_log``.

    The full document is loaded only after the owner is proven, so the one
    remaining timing signal is the owner's own request reaching the gateway -- see
    the Critical Operation Rules on both endpoints, which bound the sample count.
    """
    owner_email = _owner_email_on_file(reference_doctype, reference_name)
    supplied = (payer_email or "").strip().lower()
    if not owner_email or not supplied or supplied != owner_email:
        raise PaymentReferenceRefused(_("Payment reference not found"))
    return frappe.get_doc(reference_doctype, reference_name)


def _owner_email_on_file(reference_doctype: str, reference_name: str) -> str:
    """Owner email for a reference, "" for anything unresolvable (callers fail closed).

    Issues the same number of queries for an unknown and an existing name of an
    allowed doctype: one for Donation/Sales Invoice, two for Payment Plan Payment
    (the Member lookup runs even when the payment row or its member is missing).
    A non-string name is refused before any query: ``get_value`` would read a dict
    as filters.
    """
    if reference_doctype not in ALLOWED_REFERENCE_DOCTYPES:
        return ""
    if not isinstance(reference_name, str) or not reference_name:
        return ""
    if reference_doctype == "Payment Plan Payment":
        member = frappe.db.get_value(reference_doctype, reference_name, "member")
        # A filter dict on purpose: an empty name must match nothing, where
        # get_value("Member", "", ...) would read the first row.
        email = frappe.db.get_value("Member", {"name": member or ""}, "email")
        return (email or "").strip().lower()
    column = _OWNER_EMAIL_COLUMN[reference_doctype]
    return (frappe.db.get_value(reference_doctype, reference_name, column) or "").strip().lower()


def trim_message_log(length: int) -> None:
    """Drop messages queued since ``length`` (``len(frappe.local.message_log)`` taken earlier).

    Both endpoints answer every failure with one generic dict, but anything
    ``frappe.throw`` queued on the way (``_server_messages``) still reaches the
    client. Restoring the pre-call length removes it; ``clear_last_message`` would
    drop only the last entry.
    """
    del frappe.local.message_log[length:]
