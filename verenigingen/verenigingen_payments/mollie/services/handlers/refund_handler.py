"""
Refund Handler for Mollie Payment Processing

Extracts refund processing logic from payment_webhook.py into a dedicated handler
for better separation of concerns and maintainability.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.verenigingen_payments.mollie.core import MollieClient
from verenigingen.verenigingen_payments.mollie.utils.amount_helpers import (
    extract_amount_float,
    extract_amount_value,
)


class RefundHandler:
    """
    Handler for processing Mollie payment refunds.

    This handler encapsulates the logic for:
    - Fetching refunds from Mollie API
    - Checking for already-processed refunds (idempotency)
    - Creating Payment Entries for completed refunds
    - Tracking processing results

    DORMANT: this handler currently has NO live caller (the live refund path is
    webhook_wrapper_service_unified._process_pending_refunds). It was extracted
    from the disabled payment_webhook.py.

    Logging: happy-path breadcrumbs use frappe.logger().info/debug, so wiring this
    handler in does NOT pollute the Error Log doctype. Only genuine failures (the
    except branches) write to Error Log via frappe.log_error.
    """

    def __init__(self, mollie_client: Optional[Any] = None):
        """
        Initialize the refund handler.

        Args:
            mollie_client: Optional Mollie client instance. If not provided,
                          will be fetched from Mollie Settings when needed.
        """
        self._mollie_client = mollie_client

    def _get_mollie_client(self) -> Any:
        """Get or initialize the Mollie client via canonical MollieClient."""
        if self._mollie_client is None:
            client = MollieClient()
            self._mollie_client = client.sdk_client
        return self._mollie_client

    def process_refunds(self, payment_id: str, payment: Optional[Any] = None) -> Dict[str, Any]:
        """
        Process any refunds associated with a payment.

        This method is called when a webhook is received for a payment that might
        contain refund events. It fetches all refunds for the payment and processes
        any that haven't been handled yet.

        Args:
            payment_id: Mollie payment ID
            payment: Optional Mollie payment object (not currently used but kept
                    for interface compatibility)

        Returns:
            dict: Processing results including:
                - refunds_processed: List of processed refund details
                - payment_id: The original payment ID
                - total_refunds: Total number of refunds found
                - processed_count: Number successfully processed
                - error: Error message if processing failed
        """
        try:
            frappe.logger().info(f"Checking for refunds on payment {payment_id}")
            frappe.logger().debug(f"Starting refund processing for payment {payment_id}")

            # Fetch all refunds for this payment
            refunds = self._fetch_refunds(payment_id)
            if refunds is None:
                return {"refunds_processed": []}

            if not refunds:
                frappe.logger().info(f"No refunds found for payment {payment_id}")
                return {"refunds_processed": []}

            frappe.logger().info(f"Found {len(refunds)} refunds for payment {payment_id}")

            # Log details of each refund
            self._log_refund_details(refunds)

            # Process each refund
            processed_refunds = self._process_refund_list(payment_id, refunds)

            return {
                "refunds_processed": processed_refunds,
                "payment_id": payment_id,
                "total_refunds": len(refunds),
                "processed_count": len([r for r in processed_refunds if r["status"] == "processed"]),
            }

        except Exception as e:
            frappe.logger().error(f"Error processing refunds for payment {payment_id}: {e}")
            frappe.log_error(
                f"Refund processing error for payment {payment_id}: {e}",
                "Refund Processing",
            )
            return {"refunds_processed": [], "error": str(e)}

    def _fetch_refunds(self, payment_id: str) -> Optional[List[Any]]:
        """
        Fetch refunds from Mollie API for a payment.

        Args:
            payment_id: The Mollie payment ID

        Returns:
            List of refund objects, or None if fetch failed
        """
        try:
            mollie = self._get_mollie_client()
            refunds = mollie.payment_refunds.with_parent_id(payment_id).list()
            frappe.logger().debug(
                f"Successfully fetched refunds for {payment_id}: found {len(refunds)} refunds"
            )
            return list(refunds)
        except Exception as e:
            frappe.logger().warning(f"Could not fetch refunds for payment {payment_id}: {e}")
            frappe.log_error(
                f"Could not fetch refunds for payment {payment_id}: {e}",
                "Mollie Refund Fetch Failed",
            )
            return None

    def _log_refund_details(self, refunds: List[Any]) -> None:
        """Log details of each refund for debugging."""
        for i, refund in enumerate(refunds):
            frappe.logger().debug(
                f"Refund {i + 1}: ID={refund.id}, status={refund.status}, amount={extract_amount_value(refund.amount)}"
            )

    def _process_refund_list(self, payment_id: str, refunds: List[Any]) -> List[Dict[str, Any]]:
        """
        Process a list of refunds.

        Args:
            payment_id: The original payment ID
            refunds: List of Mollie refund objects

        Returns:
            List of processing results for each refund
        """
        processed_refunds = []

        for refund in refunds:
            result = self._process_single_refund(payment_id, refund)
            if result:
                processed_refunds.append(result)

        return processed_refunds

    def _process_single_refund(self, payment_id: str, refund: Any) -> Optional[Dict[str, Any]]:
        """
        Process a single refund.

        Args:
            payment_id: The original payment ID
            refund: Mollie refund object

        Returns:
            Processing result dict, or None if skipped
        """
        frappe.logger().info(f"Processing refund {refund.id} with status {refund.status}")

        # Only process completed refunds
        if refund.status != "refunded":
            frappe.logger().info(f"Skipping refund {refund.id} - status is {refund.status}, not 'refunded'")
            return None

        # Check if this refund has already been processed (idempotency)
        existing_pe = frappe.db.exists("Payment Entry", {"reference_no": refund.id, "payment_type": "Pay"})

        if existing_pe:
            frappe.logger().info(f"Refund {refund.id} already processed (Payment Entry: {existing_pe})")
            return None

        # Create the refund payment entry
        return self._create_refund_entry(payment_id, refund)

    def _create_refund_entry(self, payment_id: str, refund: Any) -> Dict[str, Any]:
        """
        Create a Payment Entry for a refund.

        Args:
            payment_id: The original payment ID
            refund: Mollie refund object

        Returns:
            Processing result dict
        """
        from verenigingen.verenigingen_payments.mollie.utils.unified_payment_entry_creator import (
            create_refund_payment_entry,
        )
        from verenigingen.verenigingen_payments.mollie.utils.webhook_utilities import (
            get_donation_by_payment_id,
        )

        # Find the original donation
        donation_doc = get_donation_by_payment_id(payment_id)
        if not donation_doc:
            frappe.logger().warning(f"Original donation not found for payment {payment_id}")
            return {
                "refund_id": refund.id,
                "amount": extract_amount_value(refund.amount),
                "status": "failed",
                "error": f"Original donation not found for payment {payment_id}",
            }

        # Create the refund payment entry
        refund_date = None
        if refund.created_at:
            refund_date = refund.created_at.date().isoformat()

        refund_pe = create_refund_payment_entry(
            donation_doc=donation_doc,
            mollie_payment_id=payment_id,
            refund_id=refund.id,
            refund_amount=extract_amount_float(refund.amount),
            refund_date=refund_date,
        )

        if refund_pe:
            frappe.logger().info(f"Successfully processed refund {refund.id}")
            return {
                "refund_id": refund.id,
                "amount": extract_amount_value(refund.amount),
                "payment_entry": refund_pe.name,
                "status": "processed",
            }
        else:
            frappe.logger().error(f"Failed to process refund {refund.id}")
            return {
                "refund_id": refund.id,
                "amount": extract_amount_value(refund.amount),
                "status": "failed",
                "error": "Failed to create refund Payment Entry",
            }


def process_payment_refunds(payment_id: str, payment: Optional[Any] = None) -> Dict[str, Any]:
    """
    Process any refunds associated with a payment.

    This is a standalone function that wraps RefundHandler for backward compatibility
    with existing code that calls _process_payment_refunds directly.

    Args:
        payment_id: Mollie payment ID
        payment: Optional Mollie payment object

    Returns:
        dict: Processing results
    """
    handler = RefundHandler()
    return handler.process_refunds(payment_id, payment)
