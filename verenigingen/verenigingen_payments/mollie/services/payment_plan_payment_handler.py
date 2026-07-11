# Copyright (c) 2026, Verenigingen
"""Finalize a payment-plan installment payment from a confirmed Mollie webhook.

Invoked from the unified webhook dispatch when a Mollie payment's metadata
reference_doctype is "Payment Plan Payment". Thin adapter: reads the Mollie
payment's status/metadata, then delegates to the gateway-agnostic finalizer.
"""


def _payment_status(payment) -> str:
    if isinstance(payment, dict):
        return payment.get("status") or ""
    return getattr(payment, "status", "") or ""


def _metadata(payment) -> dict:
    if isinstance(payment, dict):
        md = payment.get("metadata")
    else:
        md = getattr(payment, "metadata", None)
    return md if isinstance(md, dict) else {}


def handle_payment_plan_payment(payment_id: str, payment) -> dict:
    """Finalize a payment-plan installment from a confirmed Mollie webhook.

    Thin adapter: read the Mollie payment's status/metadata, then delegate to the
    gateway-agnostic finalizer.
    """
    from verenigingen.verenigingen_payments.services.payment_plan_finalization import (
        finalize_payment_plan_installment,
    )

    intent_name = _metadata(payment).get("reference_docname")
    if not intent_name:
        return {"status": "error", "message": "no reference_docname in metadata"}
    mollie_status = _payment_status(payment)  # "paid" / "failed" / "expired" / ...
    return finalize_payment_plan_installment(intent_name, payment_reference=payment_id, status=mollie_status)
