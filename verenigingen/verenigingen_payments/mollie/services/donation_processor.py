"""Donation Payment Processor

Completes ``PaymentTypeRouter``'s routing architecture for ``PaymentType.DONATION``,
which used to unconditionally return ``status: "pending_implementation"``
(issue #872, part B of #345). Every status other than "success" / "error" /
"already_processed" is counted as "skipped" by
``mollie_bulk_payment_discovery.process_bulk_payments``, so the admin backfill
page reported every single donation payment fed to it as skipped rather than
processing it.

A donation payment -- a first payment or a subsequent subscription charge -- is
booked by the SAME pipeline the Mollie webhook uses:
``UnifiedWebhookWrapperService.process_payment_webhook``. It already:

1. calls ``ensure_donation_for_recurring_charge`` unconditionally, before its
   own idempotency check, to materialize a Donation for a recurring charge
   that does not have one yet (#345 part A); then
2. falls through to the existing donation-booking pipeline (STEP 1/2), which
   is exactly the "first payment" case -- ``find_donation_for_payment_by_id``
   resolves the Donation the donation form or portal already created.

So there is no second implementation here: this class exists only so the
router can dispatch to it the same way it dispatches to
``DuesPaymentProcessor`` and ``OrderPaymentProcessor``, and so it can be faked
out in router unit tests the same way.
"""

from typing import Any, Dict, Optional


class DonationProcessor:
    """Books a donation payment via the existing webhook booking pipeline."""

    def process_donation_payment(self, payment_id: str, payment: Optional[Any] = None) -> Dict[str, Any]:
        """Process a donation payment (first payment or recurring charge).

        Args:
            payment_id: Mollie payment ID
            payment: Optional pre-fetched payment object. Accepted for
                interface parity with DuesPaymentProcessor /
                OrderPaymentProcessor but not used: UnifiedWebhookWrapperService
                does its own Mollie fetch internally. Reusing a caller-supplied
                object here would only save that one GET while adding a second
                payment-shape to keep in sync with ``read_payment_field`` --
                the same one-extra-GET tradeoff already accepted at the
                equivalent call site in webhook_wrapper_service_unified.py
                (see its STEP 0.5 comment).

        Returns:
            dict: status/message, matching the shape the router expects from
                every processor branch.
        """
        from .webhook_wrapper_service_unified import UnifiedWebhookWrapperService

        webhook_result = UnifiedWebhookWrapperService().process_payment_webhook(payment_id, {})
        return {
            "status": webhook_result.get("status", "error"),
            "message": webhook_result.get(
                "message", "Donation payment processed via the webhook booking pipeline"
            ),
        }
