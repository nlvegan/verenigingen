"""
Mollie Webhook Wrapper Service

A simple service layer that wraps the existing working webhook functions from
mollie_payment_webhook.py without breaking functionality. This provides a clean
interface while preserving all the tested business logic.
"""

import time
from typing import Any, Dict, Optional

import frappe

# Import the working functions from the existing webhook handler
from verenigingen.integrations.mollie.api.payment_webhook import (
    check_payment_processing_status,
    check_payment_processing_status_by_id,
    create_payment_entry_for_donation,
    extract_mollie_payment_data,
    find_donation_for_payment,
    find_donation_for_payment_by_id,
    process_successful_payment_with_idempotency,
    update_donation_payment_history,
    update_donation_with_mollie_data,
)

# Import custom exceptions
from ..exceptions import MolliePaymentError, MollieSecurityError, MollieWebhookError
from ..utils.error_recovery import CircuitBreakerConfig, RetryConfig, error_recovery

# Import logging and monitoring utilities
from ..utils.logging import MollieLogger, log_payment_processing, log_webhook_received
from ..utils.monitoring import record_operation_performance


class WebhookWrapperService:
    """
    Service wrapper for Mollie webhook processing.

    This class provides a clean service interface while delegating to the existing
    working functions in mollie_payment_webhook.py. This preserves all business logic
    while providing better structure for testing and future enhancements.
    """

    def __init__(self):
        self.logger = MollieLogger("webhook_wrapper")
        # Import the refund/chargeback service for financial reversals
        from .refund_chargeback_service import RefundChargebackService

        self.refund_chargeback_service = RefundChargebackService()

    def process_webhook(self, payment_id: str, payment_data: Any = None) -> Dict[str, Any]:
        """
        Process a Mollie webhook for the given payment ID.

        Args:
            payment_id: The Mollie payment ID from the webhook
            payment_data: Optional full payment object from Mollie API

        Returns:
            Dict containing processing results

        Raises:
            MollieWebhookError: When webhook processing fails
        """
        start_time = time.time()

        try:
            # Log webhook received
            webhook_data = {"payment_id": payment_id, "has_payment_data": payment_data is not None}
            log_webhook_received(payment_id, webhook_data)
            self.logger.info(f"Starting webhook processing", {"payment_id": payment_id})

            # Check for idempotency first
            log_payment_processing(payment_id, "idempotency_check", "started")
            processing_status = check_payment_processing_status_by_id(payment_id)
            if processing_status.get("all_complete"):
                duration = time.time() - start_time
                self.logger.success(
                    f"Payment already processed (idempotent)",
                    {"payment_id": payment_id, "components": processing_status},
                    duration=duration,
                )
                log_payment_processing(payment_id, "idempotency_check", "success", {"idempotent": True})
                record_operation_performance("webhook_processing", duration, True, {"idempotent": True})
                return {
                    "status": "success",
                    "message": "Payment already processed",
                    "payment_id": payment_id,
                    "idempotent": True,
                    "components": processing_status,
                }

            # Get payment from Mollie if not provided
            if not payment_data:
                log_payment_processing(payment_id, "fetch_payment_data", "started")
                payment_data = self._fetch_payment_from_mollie(payment_id)
                log_payment_processing(payment_id, "fetch_payment_data", "success")

            # Validate payment status
            if payment_data.status != "paid":
                duration = time.time() - start_time
                self.logger.info(
                    f"Payment not in paid status",
                    {"payment_id": payment_id, "status": payment_data.status},
                    duration=duration,
                )
                log_payment_processing(
                    payment_id, "status_validation", "skipped", {"status": payment_data.status}
                )
                record_operation_performance(
                    "webhook_processing", duration, True, {"status": payment_data.status, "processed": False}
                )
                return {
                    "status": "success",
                    "message": f"Payment status: {payment_data.status}",
                    "payment_id": payment_id,
                    "processed": False,
                }

            # Find related donation
            log_payment_processing(payment_id, "find_donation", "started")
            donation = find_donation_for_payment(payment_id, payment_data)
            if not donation:
                duration = time.time() - start_time
                error_msg = f"No donation found for payment {payment_id}"
                self.logger.error(error_msg, data={"payment_id": payment_id})
                log_payment_processing(payment_id, "find_donation", "error", {"error": "no_donation_found"})
                record_operation_performance(
                    "webhook_processing", duration, False, {"error": "no_donation_found"}
                )
                raise MollieWebhookError(error_msg, payment_id=payment_id)

            log_payment_processing(payment_id, "find_donation", "success", {"donation_name": donation.name})

            # Check idempotency for specific donation
            log_payment_processing(payment_id, "donation_idempotency_check", "started")
            idempotency_status = check_payment_processing_status(donation, payment_id)

            # Process payment with idempotency protection
            log_payment_processing(payment_id, "payment_processing", "started")
            result = process_successful_payment_with_idempotency(donation, payment_data, idempotency_status)
            log_payment_processing(payment_id, "payment_processing", "success")

            duration = time.time() - start_time
            self.logger.success(
                f"Webhook processing completed successfully",
                {
                    "payment_id": payment_id,
                    "donation_name": donation.name,
                    "result_keys": list(result.keys()) if isinstance(result, dict) else None,
                },
                duration=duration,
            )
            record_operation_performance(
                "webhook_processing", duration, True, {"donation_found": True, "payment_processed": True}
            )

            return {
                "status": "success",
                "message": "Payment processed successfully",
                "payment_id": payment_id,
                "data": result,
            }

        except MollieWebhookError as e:
            # Log our custom exceptions with performance tracking
            duration = time.time() - start_time
            self.logger.error(f"Webhook processing failed", error=e, data={"payment_id": payment_id})
            record_operation_performance(
                "webhook_processing", duration, False, {"error_type": "MollieWebhookError"}
            )

            # Create recovery workflow for webhook errors
            error_recovery.create_recovery_workflow(
                "webhook_processing_failure",
                {
                    "operation_type": "webhook_processing",
                    "payment_id": payment_id,
                    "error_details": {
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "duration": duration,
                    },
                    "payment_data": payment_data if "payment_data" in locals() else None,
                },
                "automatic_retry",
            )
            raise
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"Webhook processing failed for {payment_id}: {str(e)}"
            self.logger.error(error_msg, error=e, data={"payment_id": payment_id})
            record_operation_performance(
                "webhook_processing",
                duration,
                False,
                {"error_type": type(e).__name__, "unexpected_error": True},
            )

            # Create recovery workflow for unexpected errors
            error_recovery.create_recovery_workflow(
                "webhook_processing_unexpected_failure",
                {
                    "operation_type": "webhook_processing",
                    "payment_id": payment_id,
                    "error_details": {
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "duration": duration,
                        "unexpected": True,
                    },
                },
                "manual_review",
            )
            raise MollieWebhookError(error_msg, payment_id=payment_id, original_error=e)

    def find_donation_for_payment(self, payment_id: str, payment_data: Any = None) -> Optional[Any]:
        """
        Find donation for the given payment.

        Args:
            payment_id: Mollie payment ID
            payment_data: Optional full payment object

        Returns:
            Donation document or None
        """
        return find_donation_for_payment(payment_id, payment_data)

    def check_processing_status(self, payment_id: str) -> Dict[str, Any]:
        """
        Check the processing status for a payment.

        Args:
            payment_id: Mollie payment ID

        Returns:
            Dict with processing status details
        """
        return check_payment_processing_status_by_id(payment_id)

    def extract_payment_data(self, payment_obj: Any) -> Dict[str, Any]:
        """
        Extract structured data from Mollie payment object.

        Args:
            payment_obj: Mollie payment object

        Returns:
            Dict with extracted payment data
        """
        return extract_mollie_payment_data(payment_obj)

    def _fetch_payment_from_mollie(self, payment_id: str) -> Any:
        """
        Fetch payment details from Mollie API with enhanced error recovery.

        Args:
            payment_id: Mollie payment ID

        Returns:
            Mollie payment object

        Raises:
            MolliePaymentError: When API call fails after all retries
        """

        def fetch_operation():
            mollie_settings = frappe.get_single("Mollie Settings")
            mollie = mollie_settings.get_mollie_client()
            return mollie.payments.get(payment_id)

        # Use error recovery with retry logic and circuit breaker
        return error_recovery.execute_with_circuit_breaker(
            lambda: error_recovery.execute_with_retry(
                fetch_operation,
                f"fetch_payment_{payment_id}",
                RetryConfig(max_attempts=3, base_delay=1.0, max_delay=30.0),
                {"payment_id": payment_id},
            ),
            "mollie_api_fetch",
            CircuitBreakerConfig(failure_threshold=5, recovery_timeout=60),
            {"payment_id": payment_id, "operation": "fetch_payment"},
        )

    def process_refund_webhook(self, webhook_payload: str) -> Dict[str, Any]:
        """
        Process Mollie refund webhook.

        Args:
            webhook_payload: JSON string from Mollie refund webhook

        Returns:
            Dict containing refund processing results

        Raises:
            MollieWebhookError: When refund webhook processing fails
        """
        try:
            self.logger.info("Processing refund webhook", {"payload_length": len(webhook_payload)})
            result = self.refund_chargeback_service.process_refund_webhook(webhook_payload)
            self.logger.success("Refund webhook processed successfully", result)
            return result
        except Exception as e:
            error_msg = f"Refund webhook processing failed: {str(e)}"
            self.logger.error(error_msg, error=e)
            raise MollieWebhookError(error_msg, original_error=e)

    def process_chargeback_webhook(self, webhook_payload: str) -> Dict[str, Any]:
        """
        Process Mollie chargeback webhook.

        Args:
            webhook_payload: JSON string from Mollie chargeback webhook

        Returns:
            Dict containing chargeback processing results

        Raises:
            MollieWebhookError: When chargeback webhook processing fails
        """
        try:
            self.logger.info("Processing chargeback webhook", {"payload_length": len(webhook_payload)})
            result = self.refund_chargeback_service.process_chargeback_webhook(webhook_payload)
            self.logger.success("Chargeback webhook processed successfully", result)
            return result
        except Exception as e:
            error_msg = f"Chargeback webhook processing failed: {str(e)}"
            self.logger.error(error_msg, error=e)
            raise MollieWebhookError(error_msg, original_error=e)
