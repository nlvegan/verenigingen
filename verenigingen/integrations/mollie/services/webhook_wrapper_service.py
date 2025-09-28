"""
Mollie Webhook Wrapper Service

A simple service layer that wraps the existing working webhook functions from
mollie_payment_webhook.py without breaking functionality. This provides a clean
interface while preserving all the tested business logic.
"""

import json
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
        # Import the unified idempotency manager - single source of truth
        from .unified_idempotency_manager import get_unified_idempotency_manager

        self.idempotency_manager = get_unified_idempotency_manager()

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
            self.logger.info("Starting webhook processing", {"payment_id": payment_id})

            # Debug: Verify service layer is being used
            # Debug logging disabled

            # Get payment from Mollie if not provided (needed for refund checking)
            if not payment_data:
                # Debug logging disabled
                log_payment_processing(payment_id, "fetch_payment_data", "started")
                try:
                    payment_data = self._fetch_payment_from_mollie(payment_id)
                    # Debug logging disabled
                    log_payment_processing(payment_id, "fetch_payment_data", "success")
                except Exception as e:
                    frappe.log_error(
                        f"SERVICE LAYER: FAILED to fetch payment data for {payment_id}: {e}",
                        "Service Layer ERROR",
                    )
                    raise

            # Process payment first (with idempotency protection), then refunds sequentially
            # This ensures refunds can always find the original payment

            # Check payment-level idempotency using unified system
            # This handles regular payment webhooks for the original transaction
            log_payment_processing(payment_id, "idempotency_check", "started")
            processing_state = self.idempotency_manager.check_payment_processing_state(
                payment_id, include_mollie_api=True
            )
            # Idempotency check complete

            if processing_state.is_fully_processed():
                # Payment already processed, checking for new refunds
                # Even if payment is processed, check if there are new refunds to handle
                try:
                    # Get Mollie client to check for refunds
                    # Checking for refunds
                    mollie_settings = frappe.get_single("Mollie Settings")
                    mollie = mollie_settings.get_mollie_client()
                    payment = mollie.payments.get(payment_id)
                    refunds = payment.refunds.list()

                    # Found refunds for existing payment

                    if len(refunds) > 0:
                        self.logger.info(
                            f"Payment {payment_id} already processed, but found {len(refunds)} refunds to process"
                        )
                        # Processing refunds for existing payment
                        # Process refunds using already-fetched data (single-fetch approach)
                        refund_result = self._process_refunds_for_existing_payment(payment_id, refunds)

                        duration = time.time() - start_time
                        return {
                            "status": "success",
                            "message": f"Payment already processed, processed {len(refund_result.get('refunds_processed', []))} refunds",
                            "payment_id": payment_id,
                            "idempotent": True,
                            "unified_state": {
                                "payment_entry_exists": processing_state.payment_entry_exists,
                                "payment_history_updated": processing_state.payment_history_updated,
                                "donation_status_updated": processing_state.donation_status_updated,
                                "refunds_processed": len(processing_state.refunds_processed),
                                "pending_operations_handled": len(refund_result.get("refunds_processed", [])),
                            },
                            "refund_processing": refund_result,
                        }
                    else:
                        # No refunds found for existing payment
                        pass
                except Exception as e:
                    frappe.log_error(
                        f"❌ DEBUG: Error checking for refunds on existing payment {payment_id}: {e}",
                        "Refund Debug",
                    )
                    self.logger.warning(f"Could not check for refunds on existing payment {payment_id}: {e}")

                duration = time.time() - start_time
                self.logger.success(
                    "Payment already processed (idempotent)",
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
                    "unified_state": {
                        "payment_entry_exists": processing_state.payment_entry_exists,
                        "payment_history_updated": processing_state.payment_history_updated,
                        "donation_status_updated": processing_state.donation_status_updated,
                        "fully_processed": processing_state.is_fully_processed(),
                    },
                }
            else:
                # Payment not complete, proceeding with new payment flow
                pass

            # Validate payment status
            if payment_data.status != "paid":
                duration = time.time() - start_time
                self.logger.info(
                    "Payment not in paid status",
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

            # Check idempotency for specific donation using unified system
            log_payment_processing(payment_id, "donation_idempotency_check", "started")
            idempotency_state = self.idempotency_manager.check_payment_processing_state(
                payment_id, include_mollie_api=False
            )

            # Process payment with idempotency protection
            log_payment_processing(payment_id, "payment_processing", "started")
            result = process_successful_payment_with_idempotency(donation, payment_data, idempotency_state)
            log_payment_processing(payment_id, "payment_processing", "success")

            # Now that payment is created, process any refunds sequentially (single-fetch approach)
            log_payment_processing(payment_id, "refund_check", "started")
            try:
                # Fetch payment + refunds data once
                mollie_settings = frappe.get_single("Mollie Settings")
                mollie = mollie_settings.get_mollie_client()
                payment = mollie.payments.get(payment_id)
                refunds = payment.refunds.list()

                # Fetched refunds for new payment processing

                # Process refunds using already-fetched data
                refund_result = self._process_refunds_for_new_payment(payment_id, refunds)
                frappe.log_error(
                    f"SERVICE LAYER: Refund result (AFTER payment): {frappe.as_json(refund_result)}",
                    "Refund Debug",
                )

                # Add refund results to the main result
                if refund_result.get("refunds_processed"):
                    result["refund_processing"] = refund_result
                    successful_refunds = [
                        r
                        for r in refund_result.get("refunds_processed", [])
                        if r.get("status") in ["success", "skipped"]
                    ]
                    if successful_refunds:
                        self.logger.info(
                            f"Successfully processed {len(successful_refunds)} refunds after payment creation"
                        )

                log_payment_processing(
                    payment_id,
                    "refund_check",
                    "success",
                    {"refunds_processed": len(refund_result.get("refunds_processed", []))},
                )
            except Exception as e:
                frappe.log_error(
                    f"SERVICE LAYER: Refund processing FAILED (after payment): {e}", "Refund Debug ERROR"
                )
                log_payment_processing(payment_id, "refund_check", "failed", {"error": str(e)})
                # Don't fail the whole webhook if refund processing fails - payment was successful

            duration = time.time() - start_time
            self.logger.success(
                "Webhook processing completed successfully",
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
            self.logger.error("Webhook processing failed", error=e, data={"payment_id": payment_id})
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

    def _process_payment_refunds(self, payment_id: str, payment_data: Any) -> Dict[str, Any]:
        """
        Process any refunds associated with this payment.

        This method fetches all refunds for the payment and processes any that haven't been handled yet.

        Args:
            payment_id (str): Mollie payment ID
            payment_data: Mollie payment object

        Returns:
            dict: Processing results including any refunds processed
        """
        try:
            self.logger.info(f"Checking for refunds on payment {payment_id}")
            # Debug logging disabled - using consolidated logging instead

            # Get Mollie client to fetch refunds
            mollie_settings = frappe.get_single("Mollie Settings")
            mollie = mollie_settings.get_mollie_client()

            # Fetch all refunds for this payment
            try:
                # Get the payment object first, then access its refunds
                payment = mollie.payments.get(payment_id)
                refunds = payment.refunds.list()
                # Found refunds, will process them

                # Debug logging disabled - using consolidated logging

                self.logger.info(f"Found {len(refunds)} refunds for payment {payment_id}")
            except Exception as e:
                self.logger.error(f"Could not fetch refunds for {payment_id}: {e}")
                self.logger.warning(f"Could not fetch refunds for payment {payment_id}: {e}")
                return {"refunds_processed": []}

            if not refunds:
                frappe.log_error(
                    f"REFUND DEBUG: No refunds found for payment {payment_id}", "Refund Processing"
                )
                self.logger.info(f"No refunds found for payment {payment_id}")
                return {"refunds_processed": []}

            processed_refunds = []

            # Process each refund
            for refund in refunds:
                # Handle both object and dict formats for refund data
                refund_id = refund.get("id") if isinstance(refund, dict) else refund.id
                refund_status = refund.get("status") if isinstance(refund, dict) else refund.status

                self.logger.info(f"Processing refund {refund_id} with status {refund_status}")

                # Only process completed refunds
                if refund_status != "refunded":
                    self.logger.info(
                        f"Skipping refund {refund_id} - status is {refund_status}, not 'refunded'"
                    )
                    continue

                # Check if this refund has already been processed (idempotency)
                # Use unified idempotency check for consistency across all code paths
                existing_refund = self.idempotency_manager.check_refund_idempotency(refund_id)
                if existing_refund:
                    self.logger.info(f"Refund {refund_id} already processed (Reference: {existing_refund})")
                    continue

                # Extract amount info (handle both object and dict formats)
                if isinstance(refund, dict):
                    amount_value = refund.get("amount", {}).get("value", "0")
                    amount_currency = refund.get("amount", {}).get("currency", "EUR")
                    refund_description = refund.get("description", "")
                    created_at = refund.get("created_at")
                else:
                    amount_value = refund.amount.value if hasattr(refund, "amount") else "0"
                    amount_currency = refund.amount.currency if hasattr(refund, "amount") else "EUR"
                    refund_description = getattr(refund, "description", "")
                    created_at = (
                        refund.created_at.isoformat()
                        if hasattr(refund, "created_at") and refund.created_at
                        else None
                    )

                # Create webhook payload structure that the refund service expects
                refund_webhook_payload = {
                    "payment_id": payment_id,
                    "refund_id": refund_id,
                    "refund": {
                        "id": refund_id,
                        "status": refund_status,
                        "amount": {"value": amount_value, "currency": amount_currency},
                        "description": refund_description,
                        "created_at": created_at,
                    },
                    "payment": {"id": payment_id},
                }

                # Process the refund using the complete hybrid RefundChargebackService
                result = self.refund_chargeback_service.process_refund_webhook(
                    json.dumps(refund_webhook_payload)
                )

                if result.get("status") == "success":
                    processed_refunds.append(
                        {
                            "refund_id": refund_id,
                            "amount": amount_value,
                            "credit_note": result.get("credit_note"),
                            "status": "success",
                        }
                    )
                    self.logger.info(
                        f"Successfully processed refund {refund_id} with Credit Note {result.get('credit_note')}"
                    )
                elif result.get("status") == "skipped":
                    processed_refunds.append(
                        {
                            "refund_id": refund_id,
                            "amount": amount_value,
                            "status": "skipped",
                            "message": result.get("message"),
                        }
                    )
                    self.logger.info(f"Skipped refund {refund_id}: {result.get('message')}")
                else:
                    self.logger.error(f"Failed to process refund {refund_id}: {result.get('message')}")
                    processed_refunds.append(
                        {
                            "refund_id": refund_id,
                            "amount": amount_value,
                            "status": "failed",
                            "error": result.get("message"),
                        }
                    )

            # Consolidated logging instead of individual refund logs
            successful_count = len([r for r in processed_refunds if r["status"] in ["success", "skipped"]])
            failed_count = len(processed_refunds) - successful_count

            # Show failure details if any failed
            failure_summary = ""
            if failed_count > 0:
                failed_refunds = [r for r in processed_refunds if r["status"] == "failed"]
                error_types = {}
                for failed in failed_refunds[:3]:  # Show up to 3 examples
                    error = failed.get("error", "Unknown error")
                    error_types[error] = error_types.get(error, 0) + 1
                failure_summary = f" | Failure types: {dict(error_types)}"

            self.logger.info(
                f"REFUND BULK PROCESSING COMPLETE: Payment {payment_id} - "
                f"Total: {len(refunds)}, Success: {successful_count}, Failed: {failed_count}{failure_summary}"
            )

            return {
                "refunds_processed": processed_refunds,
                "payment_id": payment_id,
                "total_refunds": len(refunds),
                "processed_count": successful_count,
            }

        except Exception as e:
            self.logger.error(f"Error processing refunds for payment {payment_id}: {e}")
            return {"refunds_processed": [], "error": str(e)}

    def _process_refund_with_credit_note(
        self, refund_data: Dict[str, Any], payment_id: str
    ) -> Dict[str, Any]:
        """
        Process refund using Credit Note approach via RefundChargebackService.

        Args:
            refund_data: Refund data from webhook payload
            payment_id: Original payment ID

        Returns:
            Dict with processing result
        """
        try:
            refund_info = refund_data["refund"]
            _ = refund_info["id"]  # refund_id used for debugging only

            # Find donation for this payment
            donation_name = self._find_donation_for_payment(payment_id)
            if not donation_name:
                return {"status": "error", "message": f"Donation for payment {payment_id} not found"}

            # Get donation document
            donation_doc = frappe.get_doc("Donation", donation_name)
            refund_amount = float(refund_info["amount"]["value"])

            # Use the RefundChargebackService Credit Note approach
            credit_note_result = self.refund_chargeback_service._create_refund_credit_note(
                refund_info, donation_doc, refund_amount
            )

            if credit_note_result["status"] == "success":
                # Update donation payment history with Credit Note reference
                self.refund_chargeback_service._update_donation_refund_history(
                    donation_name, refund_info, credit_note_result["credit_note"]
                )

                return {
                    "status": "success",
                    "credit_note": credit_note_result["credit_note"],
                    "amount": refund_amount,
                }
            elif credit_note_result["status"] == "skipped":
                return {
                    "status": "skipped",
                    "message": credit_note_result["message"],
                    "amount": refund_amount,
                }
            else:
                return {
                    "status": "error",
                    "message": credit_note_result.get("error", "Unknown error creating Credit Note"),
                }

        except Exception as e:
            self.logger.error(f"Error processing refund with credit note: {e}")
            return {"status": "error", "message": str(e)}

    def _find_donation_for_payment(self, payment_id: str) -> Optional[str]:
        """Find donation associated with the payment."""
        try:
            # Try to find donation by payment_id
            donation = frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")
            if donation:
                return donation

            # If not found, try to find via Payment Entry reference
            payment_entry = frappe.db.get_value("Payment Entry", {"reference_no": payment_id}, "name")
            if payment_entry:
                # Look for donation referencing this payment entry
                donation = frappe.db.get_value("Donation", {"payment_entry": payment_entry}, "name")
                return donation

            return None
        except Exception as e:
            self.logger.error(f"Error finding donation for payment {payment_id}: {e}")
            return None

    def _update_donation_refund_history(
        self, donation_name: str, refund_info: Dict[str, Any], payment_entry_id: str, refund_amount: float
    ) -> None:
        """Update donation payment history with refund information."""
        try:
            donation = frappe.get_doc("Donation", donation_name)

            # Add refund to payment history
            donation.append(
                "payment_history",
                {
                    "payment_date": frappe.utils.getdate(refund_info.get("created_at"))
                    if refund_info.get("created_at")
                    else frappe.utils.getdate(),
                    "payment_method": "Mollie",
                    "status": "Refunded",
                    "amount": -refund_amount,  # Negative amount for refund
                    "payment_entry": payment_entry_id,
                    "mollie_payment_id": refund_info["id"],
                    "notes": f"Refund: {refund_info.get('description', 'N/A')}",
                },
            )

            donation.save()

        except Exception as e:
            self.logger.error(f"Error updating donation refund history: {e}")

    def _process_refunds_for_existing_payment(self, payment_id: str, refunds) -> Dict[str, Any]:
        """Process refunds for an already-processed payment using unified idempotency."""
        processed_refunds = []

        for refund in refunds:
            refund_id = refund.get("id") if isinstance(refund, dict) else refund.id
            refund_status = refund.get("status") if isinstance(refund, dict) else refund.status

            # Only process completed refunds
            if refund_status != "refunded":
                continue

            # Check unified idempotency
            existing_refund = self.idempotency_manager.check_refund_idempotency(refund_id)
            if existing_refund:
                self.logger.info(f"Refund {refund_id} already processed (Reference: {existing_refund})")
                continue

            # Process the refund
            try:
                amount_value = (
                    refund.get("amount", {}).get("value", "0")
                    if isinstance(refund, dict)
                    else refund.amount.value
                )
                refund_webhook_payload = {
                    "payment_id": payment_id,
                    "refund_id": refund_id,
                    "refund": {
                        "id": refund_id,
                        "status": refund_status,
                        "amount": {"value": amount_value, "currency": "EUR"},
                    },
                }

                # Use the existing refund processing logic
                from ..services.refund_chargeback_service import RefundChargebackService

                refund_service = RefundChargebackService()
                result = refund_service.process_refund_webhook(json.dumps(refund_webhook_payload))

                processed_refunds.append(
                    {
                        "refund_id": refund_id,
                        "amount": amount_value,
                        "status": result.get("status", "unknown"),
                    }
                )

            except Exception as e:
                self.logger.error(f"Failed to process refund {refund_id}: {e}")
                processed_refunds.append({"refund_id": refund_id, "status": "failed", "error": str(e)})

        return {
            "refunds_processed": processed_refunds,
            "payment_id": payment_id,
            "total_refunds": len(refunds),
            "processed_count": len([r for r in processed_refunds if r["status"] in ["success", "skipped"]]),
        }

    def _process_refunds_for_new_payment(self, payment_id: str, refunds) -> Dict[str, Any]:
        """Process refunds for a newly-processed payment using unified idempotency."""
        # Same logic as existing payment since idempotency is unified
        return self._process_refunds_for_existing_payment(payment_id, refunds)
