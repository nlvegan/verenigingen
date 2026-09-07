# Copyright (c) 2025, Verenigingen
# License: MIT

"""
Payment API endpoints.

Provides whitelisted methods for frontend payment integration.
"""

import frappe
from frappe import _
from frappe.utils import flt

from verenigingen.utils.security.api_security_framework import OperationType, public_api
from verenigingen.verenigingen_payments.hooks.payment_hook import PaymentHook

# Reference doctypes a guest may pay through this endpoint. Deliberately
# narrower than templates.pages.payment_success.ALLOWED_PAYMENT_DOCTYPES and
# matching verenigingen_payments.templates.pages.mollie_checkout's
# independently-verified ALLOWED_REFERENCE_DOCTYPES (#1032/PR #1047) --
# "Member Application" is dropped there because it is not an installed
# DocType. Kept as a separate copy here rather than imported from that
# template-page module to avoid a hooks-module -> templates-module
# dependency; see #1048's PR body for the cross-copy duplication this
# creates and the follow-up filed for it.
ALLOWED_REFERENCE_DOCTYPES = {"Donation", "Sales Invoice", "Payment Plan Payment"}


def _resolve_reference_owner_email(reference_doctype: str, doc) -> str:
    """Resolve the email address on file for a payment reference document.

    initiate_payment is guest-reachable by design (a payer has no session
    before their payment succeeds), so this is the only ownership signal
    available -- mirrors mollie_checkout._resolve_reference_owner_email
    (#1032/PR #1047) and donate.py's _verify_donor_email_matches (#969/PR
    #1028). Returns "" (never None) for any doctype/document this cannot
    resolve an email for, so callers fail closed instead of skipping the
    comparison.
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


def _resolve_reference_amount(reference_doctype: str, doc) -> float:
    """Server-derived payment amount for a reference document.

    A guest caller's own `amount` argument is never trusted for the actual
    gateway call (#1048): it would let an unauthenticated caller name an
    arbitrary sum, independent of what is actually owed on the resolved
    document -- e.g. paying EUR 0.01 against a reference the webhook
    completion logic later treats as fully settled just because a
    successful payment_id was logged against it. Returns 0 for anything
    unresolved, so callers fail closed (PaymentHook.initiate_payment's own
    amount validation rejects <= 0 with a generic message).
    """
    if reference_doctype == "Donation":
        return flt(getattr(doc, "amount", 0))
    if reference_doctype == "Sales Invoice":
        outstanding = flt(getattr(doc, "outstanding_amount", 0))
        return outstanding if outstanding > 0 else flt(getattr(doc, "grand_total", 0))
    if reference_doctype == "Payment Plan Payment":
        return flt(getattr(doc, "amount", 0))
    return 0.0


def _verify_payer_owns_reference(reference_doctype: str, doc, payer_email: str) -> None:
    """Refuse unless payer_email matches the reference document's on-file email.

    Raises frappe.ValidationError. The caller wraps this in a broad except
    that converts every failure here into the same generic "Payment
    reference not found" response, so the response TEXT does not
    distinguish "wrong/missing email" or "disallowed doctype" from any
    other failure -- mirrors mollie_checkout._verify_payer_owns_reference
    (#1032/PR #1047). That uniformity does NOT close a timing side-channel
    by itself: a refusal here is a string compare, while a matching email
    proceeds into a real, network-bound gateway call before it can fail for
    an unrelated reason. Not mitigated here; the intended mitigation is the
    dedicated per_ip Critical Operation Rule added alongside this fix
    (fixtures/critical_operation_rule.json's "initiate_payment" entry),
    which bounds how many timing samples one attacker can collect per
    minute rather than trying to equalize latency.
    """
    owner_email = _resolve_reference_owner_email(reference_doctype, doc)
    supplied = (payer_email or "").strip().lower()
    if not owner_email or not supplied or supplied != owner_email:
        frappe.throw(_("Payment reference not found"))


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def get_payment_methods(context: str | None = None) -> dict:
    """
    Get available payment methods for the given context.

    Args:
        context: JSON string with context options:
            - recurring: bool - Only return methods supporting recurring
            - form_type: str - Form type (donation, membership, event)

    Returns:
        {
            "success": True,
            "methods": [
                {
                    "id": "mollie",
                    "label": "Online Payment",
                    "description": "...",
                    "supports_recurring": True,
                    "type": "redirect"
                },
                ...
            ]
        }
    """
    ctx = frappe.parse_json(context) if context else {}
    methods = PaymentHook.get_available_methods(ctx)

    return {"success": True, "methods": methods}


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.FINANCIAL)
def initiate_payment(
    method: str,
    amount: float,
    reference_doctype: str,
    reference_name: str,
    payer_email: str,
    payer_name: str,
    payer_iban: str | None = None,
    account_holder: str | None = None,
    success_url: str | None = None,
    cancel_url: str | None = None,
    recurring: bool = False,
    interval: str | None = None,
) -> dict:
    """
    Initiate a payment.

    Guest-reachable by design (#1048): reference_doctype is restricted to
    ALLOWED_REFERENCE_DOCTYPES, and the resolved document's on-file email
    must match payer_email before anything else runs -- see
    _verify_payer_owns_reference for what this does and does not close off.
    The amount actually forwarded to the gateway is derived from that
    document via _resolve_reference_amount, NOT from the caller-supplied
    `amount` argument below (kept in the signature for API stability; its
    value is ignored). `recurring`/`interval` are force-disabled here: every
    real caller found for this endpoint (grepped app-wide) -- the public
    donation form, payment-plan installments -- calls
    PaymentHook.initiate_payment directly, under its own session/ownership
    checks, and neither goes through this wrapper. No known legitimate use
    of a guest-initiated recurring mandate through THIS endpoint exists, so
    the ability is removed rather than merely guarded.

    Args:
        method: Payment method ID (mollie, sepa, bank_transfer, cash)
        amount: Ignored -- see docstring above.
        reference_doctype: DocType being paid for, must be in
            ALLOWED_REFERENCE_DOCTYPES
        reference_name: Document name
        payer_email: Payer's email address, must match the resolved
            document's on-file email
        payer_name: Payer's name
        payer_iban: IBAN (required for SEPA)
        account_holder: Account holder name (for SEPA, defaults to payer_name)
        success_url: Redirect URL on success
        cancel_url: Redirect URL on cancel
        recurring: Ignored -- forced to False. See docstring above.
        interval: Ignored -- forced to None. See docstring above.

    Returns:
        {
            "success": True/False,
            "action": "redirect" | "mandate_form" | "show_instructions",
            "data": {...},
            "payment_id": "...",
            "message": "..."
        }
    """
    try:
        if reference_doctype not in ALLOWED_REFERENCE_DOCTYPES:
            frappe.throw(_("Payment reference not found"))

        ref_doc = frappe.get_doc(reference_doctype, reference_name)
        _verify_payer_owns_reference(reference_doctype, ref_doc, payer_email)
        resolved_amount = _resolve_reference_amount(reference_doctype, ref_doc)
    except Exception as e:
        frappe.log_error(
            title="Initiate Payment Ownership Check Failed",
            message=(f"initiate_payment refused for {reference_doctype}/{reference_name}: {e}"),
        )
        return {
            "success": False,
            "action": None,
            "data": {},
            "message": _("Payment reference not found"),
        }

    payer_info = {
        "email": payer_email,
        "name": payer_name,
        "iban": payer_iban,
        "account_holder": account_holder or payer_name,
    }

    redirect_urls = None
    if success_url or cancel_url:
        redirect_urls = {"success": success_url, "cancel": cancel_url}

    return PaymentHook.initiate_payment(
        method=method,
        amount=resolved_amount,
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        payer_info=payer_info,
        redirect_urls=redirect_urls,
        recurring=False,
        interval=None,
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def get_payment_status(method: str, payment_id: str) -> dict:
    """
    Check payment status.

    Args:
        method: Payment method ID
        payment_id: Payment identifier from gateway

    Returns:
        {
            "status": "pending" | "paid" | "failed" | "expired",
            "data": {...}
        }
    """
    return PaymentHook.get_payment_status(method, payment_id)
