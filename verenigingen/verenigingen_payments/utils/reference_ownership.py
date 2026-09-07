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

The logic was first written in mollie_checkout.py and copy-pasted into
hooks/api.py for #1048, which tripped
scripts/validation/duplicate_helper_validator.py's ratchet (two
identically-named private helpers). Extracted here instead of baselining
the duplication -- import these rather than re-copying a third time.
"""

import frappe
from frappe import _

# DocTypes eligible for a guest-initiated payment against a specific
# document, mapped (in resolve_reference_owner_email) to the field that
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


def resolve_reference_owner_email(reference_doctype: str, doc) -> str:
    """Resolve the email address on file for a payment reference document.

    Both callers are guest-reachable by design (a payer has no session
    before their payment succeeds), so this is the only ownership signal
    available -- mirrors donate.py's
    PublicDonationService._verify_donor_email_matches (#969, PR #1028).
    Returns "" (never None) for any doctype/document this cannot resolve an
    email for, so callers fail closed instead of skipping the comparison.
    """
    if reference_doctype == "Donation":
        return (getattr(doc, "donor_email", None) or "").strip().lower()
    if reference_doctype == "Sales Invoice":
        return (getattr(doc, "contact_email", None) or "").strip().lower()
    if reference_doctype == "Payment Plan Payment":
        member = getattr(doc, "member", None)
        member_email = frappe.db.get_value("Member", member, "email") if member else None
        return (member_email or "").strip().lower()
    return ""


def verify_payer_owns_reference(reference_doctype: str, doc, payer_email: str) -> None:
    """Refuse unless payer_email matches the reference document's on-file email.

    Raises frappe.ValidationError. Both callers wrap this in a broad except
    that converts every failure into the same generic response used for
    every other failure, so the response TEXT does not distinguish
    "wrong/missing email" or "disallowed doctype" from any other failure.
    That uniformity does NOT close a timing side-channel: a refusal here is
    a string compare, while a matching email proceeds into a real,
    network-bound gateway call before it can fail for an unrelated reason
    (see PR #1028's measured ~30-400x gap for the identical shape in
    donate.py::retry_payment). This is not mitigated here; a dedicated
    per_ip Critical Operation Rule (as added for retry_payment and for
    initiate_payment, #1048) is the recommended mitigation, bounding how
    many timing samples one attacker can collect rather than equalizing
    latency.
    """
    owner_email = resolve_reference_owner_email(reference_doctype, doc)
    supplied = (payer_email or "").strip().lower()
    if not owner_email or not supplied or supplied != owner_email:
        frappe.throw(_("Payment reference not found"))
