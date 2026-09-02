"""
Payment Type Router Service

Routes Mollie webhook payments to the appropriate processor based on payment type.
Supports both donation payments and membership dues payments with proper classification.
"""

from typing import Any, Dict, Optional

import frappe

from ..domain.payment_classification import PaymentClassifier, PaymentType


class PaymentTypeRouter:
    """
    Routes payments to appropriate processors based on classification.

    This service acts as a dispatcher that:
    1. Fetches payment data from Mollie
    2. Classifies the payment type (dues, donation, unknown)
    3. Routes to the appropriate processor
    4. Returns unified result format
    """

    def __init__(self):
        from ..core.client import MollieClient
        from .dues_payment_processor import DuesPaymentProcessor
        from .order_payment_processor import OrderPaymentProcessor

        self.mollie_client = MollieClient()
        self.classifier = PaymentClassifier()
        self.dues_processor = DuesPaymentProcessor()
        self.order_processor = OrderPaymentProcessor()

    def fetch_payment(self, payment_id: str) -> Any:
        """
        Fetch payment data from Mollie API.

        Args:
            payment_id: Mollie payment ID

        Returns:
            Mollie payment object

        Raises:
            Exception if payment cannot be fetched
        """
        try:
            payment = self.mollie_client.sdk_client.payments.get(payment_id)
            frappe.logger().info(
                f"✅ Fetched payment {payment_id}: status={payment.status}, "
                f"amount={payment.amount.get('value') if payment.amount else 'N/A'}"
            )
            return payment
        except Exception as e:
            frappe.logger().error(f"❌ Failed to fetch payment {payment_id}: {e}")
            raise

    def classify_payment(self, payment: Any) -> Dict[str, Any]:
        """
        Classify payment type using PaymentClassifier.

        Args:
            payment: Mollie payment object

        Returns:
            Dict with classification details:
                - payment_type: "dues", "donation", or "unknown"
                - confidence: Confidence level of classification
                - matched_by: Which rule produced the classification
                - member_id: Associated member (if dues)
                - donor_id: Associated donor (if donation)
        """
        classification = self.classifier.classify(payment)

        result = {
            "payment_type": classification.payment_type,
            "confidence": classification.confidence,
            "matched_by": classification.matched_by,
            "member_id": classification.member_id,
            "donor_id": classification.donor_id,
        }

        frappe.logger().info(
            f"🔍 Payment {payment.id} classified as '{classification.payment_type}' "
            f"(confidence: {classification.confidence}, matched_by: {classification.matched_by})"
        )

        return result

    def route_payment(self, payment_id: str, payment: Optional[Any] = None) -> Dict[str, Any]:
        """
        Route payment to appropriate processor based on type.

        Args:
            payment_id: Mollie payment ID
            payment: Optional pre-fetched payment object

        Returns:
            Dict with processing result:
                - status: "success", "error", "skipped", "already_processed"
                - payment_type: Classification result
                - processor: Which processor handled it
                - message: Human-readable result message
                - Additional processor-specific fields
        """
        try:
            # Fetch payment if not provided
            if not payment:
                payment = self.fetch_payment(payment_id)

            # Classify the payment
            classification = self.classify_payment(payment)

            # Build base result
            result = {
                "payment_id": payment_id,
                "payment_type": classification["payment_type"],
                "confidence": classification["confidence"],
                "matched_by": classification["matched_by"],
            }

            # Route based on payment type
            if classification["payment_type"] == PaymentType.ORDER:
                frappe.logger().info(f"🛒 Routing payment {payment_id} to OrderPaymentProcessor")
                result["processor"] = "OrderPaymentProcessor"

                # Process as shop/WooCommerce order
                order_result = self.order_processor.process_order_payment(payment_id, payment)
                result.update(order_result)

            elif classification["payment_type"] == PaymentType.DUES:
                frappe.logger().info(f"📋 Routing payment {payment_id} to DuesPaymentProcessor")
                result["processor"] = "DuesPaymentProcessor"

                # Process as membership dues
                dues_result = self.dues_processor.process_dues_payment(payment_id, payment)
                result.update(dues_result)

            elif classification["payment_type"] == PaymentType.DONATION:
                frappe.logger().info(f"💝 Routing payment {payment_id} to donation processor")
                result["processor"] = "DonationProcessor"
                result["status"] = "pending_implementation"
                result["message"] = (
                    f"Donation payment routing not yet implemented. "
                    f"Payment will be processed via fallback donation logic in webhook handler. "
                    f"Donor: {classification.get('donor_id', 'Unknown')}"
                )

                # NOTE: Donation processing currently handled by existing logic in
                # webhook_wrapper_service_unified.py. This should be refactored into
                # a dedicated DonationProcessor to complete the routing architecture.

            else:
                # Unknown payment type
                frappe.logger().warning(f"⚠️ Payment {payment_id} has unknown type - cannot process")
                result["status"] = "error"
                result["processor"] = "none"
                result["message"] = (
                    f"Cannot determine payment type - no matching member/donor/order found. "
                    f"Classification: {classification['matched_by']}"
                )

            return result

        except Exception as e:
            frappe.logger().error(f"❌ Payment routing failed for {payment_id}: {e}")
            frappe.log_error(
                title="Payment Router Error", message=f"Payment routing error: {e}\n{frappe.get_traceback()}"
            )

            return {
                "payment_id": payment_id,
                "status": "error",
                "processor": "none",
                "message": f"Payment routing failed: {str(e)}",
                "error": str(e),
            }


def get_payment_router() -> PaymentTypeRouter:
    """
    Factory function to get PaymentTypeRouter singleton.

    Returns:
        PaymentTypeRouter instance
    """
    # Could implement caching here if needed
    return PaymentTypeRouter()
