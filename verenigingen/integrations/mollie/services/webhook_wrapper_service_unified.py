"""
Mollie Webhook Wrapper Service - UNIFIED IDEMPOTENCY VERSION

Complete consolidation of idempotency checks using the UnifiedIdempotencyManager.
This replaces the fragmented approach with a single authoritative source for
payment processing state across all webhook code paths.
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


class UnifiedWebhookWrapperService:
    """
    UNIFIED webhook wrapper using UnifiedIdempotencyManager.

    This eliminates all fragmented idempotency checks by using a single
    authoritative source for payment processing state. Prevents duplicate
    payment entries by ensuring all code paths check the same unified state.
    """

    def __init__(self):
        self.logger = MollieLogger("unified_webhook_wrapper")
        # Import the unified idempotency manager - single source of truth
        from .unified_idempotency_manager import get_unified_idempotency_manager

        self.idempotency_manager = get_unified_idempotency_manager()

    def process_payment_webhook(self, payment_id: str, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process payment webhook with UNIFIED idempotency management.

        This is the main entry point that ensures consistent state checking
        across all webhook processing scenarios.
        """
        start_time = time.time()

        try:
            self.logger.info(f"🚀 UNIFIED webhook processing started for payment {payment_id}")

            # STEP 1: UNIFIED IDEMPOTENCY CHECK - single source of truth
            self.logger.info(f"🔍 STEP 1: Unified idempotency check for {payment_id}")
            processing_state = self.idempotency_manager.check_payment_processing_state(
                payment_id, include_mollie_api=True
            )

            # STEP 2: Handle based on unified state
            if processing_state.is_fully_processed():
                return self._handle_fully_processed_payment(payment_id, processing_state, start_time)
            elif processing_state.needs_payment_processing():
                return self._handle_new_payment_processing(
                    payment_id, webhook_data, processing_state, start_time
                )
            else:
                # Partial processing - determine what needs to be completed
                return self._handle_partial_processing(payment_id, webhook_data, processing_state, start_time)

        except Exception as e:
            self.logger.error(f"❌ Unified webhook processing failed for {payment_id}: {e}")
            duration = time.time() - start_time
            record_operation_performance("unified_webhook_processing", duration, False)
            return {
                "status": "error",
                "message": f"Webhook processing failed: {str(e)}",
                "payment_id": payment_id,
                "duration_seconds": duration,
            }

    def _handle_fully_processed_payment(
        self, payment_id: str, processing_state, start_time: float
    ) -> Dict[str, Any]:
        """Handle payments that are already fully processed."""
        self.logger.info(f"✅ Payment {payment_id} already fully processed")

        # Handle any pending refunds/chargebacks identified by unified check
        refund_results = []
        if processing_state.has_pending_refunds():
            self.logger.info(f"Processing {len(processing_state.pending_refunds)} pending refunds")
            for pending_refund in processing_state.pending_refunds:
                try:
                    refund_result = self.payment_service.process_refunds_for_payment(payment_id)
                    refund_results.append(refund_result)
                    # Mark as processed in unified manager
                    if refund_result.get("status") == "success":
                        self.idempotency_manager.mark_refund_processed(
                            payment_id, pending_refund["refund_id"], refund_result.get("payment_entry")
                        )
                except Exception as e:
                    self.logger.error(
                        f"Failed to process pending refund {pending_refund.get('refund_id')}: {e}"
                    )

        # Handle any pending chargebacks
        chargeback_results = []
        if processing_state.has_pending_chargebacks():
            self.logger.info(f"Processing {len(processing_state.pending_chargebacks)} pending chargebacks")
            # TODO: Implement chargeback processing when needed

        duration = time.time() - start_time
        record_operation_performance("unified_webhook_processing", duration, True, {"idempotent": True})

        return {
            "status": "success",
            "message": f"Payment already processed, handled {len(refund_results)} pending operations",
            "payment_id": payment_id,
            "idempotent": True,
            "unified_state": {
                "payment_entry_exists": processing_state.payment_entry_exists,
                "payment_history_updated": processing_state.payment_history_updated,
                "donation_status_updated": processing_state.donation_status_updated,
                "refunds_processed": len(processing_state.refunds_processed),
                "pending_operations_handled": len(refund_results) + len(chargeback_results),
            },
            "refund_processing": refund_results,
            "duration_seconds": duration,
        }

    def _handle_new_payment_processing(
        self, payment_id: str, webhook_data: Dict[str, Any], processing_state, start_time: float
    ) -> Dict[str, Any]:
        """Handle payments that need initial processing."""
        self.logger.info(
            f"🔄 Payment {payment_id} needs processing: "
            f"PE={processing_state.payment_entry_exists}, "
            f"PH={processing_state.payment_history_updated}, "
            f"DS={processing_state.donation_status_updated}"
        )

        try:
            # Extract payment data from webhook
            payment_data = extract_mollie_payment_data(webhook_data)

            # Validate payment status
            if payment_data.get("status") != "paid":
                self.logger.info(f"Payment {payment_id} not in paid status: {payment_data.get('status')}")
                return {
                    "status": "skipped",
                    "message": f"Payment status '{payment_data.get('status')}' not processable",
                    "payment_id": payment_id,
                }

            # Process the payment using existing business logic
            result = process_successful_payment_with_idempotency(payment_id, payment_data)

            duration = time.time() - start_time
            record_operation_performance(
                "unified_webhook_processing", duration, result.get("status") == "success"
            )

            # Add unified state information to result
            if isinstance(result, dict):
                result["unified_processing"] = True
                result["duration_seconds"] = duration

            return result

        except Exception as e:
            self.logger.error(f"❌ Payment processing failed for {payment_id}: {e}")
            duration = time.time() - start_time
            record_operation_performance("unified_webhook_processing", duration, False)
            return {
                "status": "error",
                "message": f"Payment processing failed: {str(e)}",
                "payment_id": payment_id,
                "duration_seconds": duration,
            }

    def _handle_partial_processing(
        self, payment_id: str, webhook_data: Dict[str, Any], processing_state, start_time: float
    ) -> Dict[str, Any]:
        """Handle payments that are partially processed."""
        self.logger.info(f"🔄 Payment {payment_id} partially processed, completing missing components")

        # Determine what components need completion
        missing_components = []
        if not processing_state.payment_entry_exists:
            missing_components.append("payment_entry")
        if not processing_state.payment_history_updated:
            missing_components.append("payment_history")
        if not processing_state.donation_status_updated:
            missing_components.append("donation_status")

        self.logger.info(f"Missing components for {payment_id}: {missing_components}")

        try:
            # Use existing business logic to complete processing
            payment_data = extract_mollie_payment_data(webhook_data)
            result = process_successful_payment_with_idempotency(payment_id, payment_data)

            duration = time.time() - start_time
            record_operation_performance(
                "unified_webhook_processing", duration, result.get("status") == "success"
            )

            # Add partial processing information
            if isinstance(result, dict):
                result["partial_processing"] = True
                result["completed_components"] = missing_components
                result["duration_seconds"] = duration

            return result

        except Exception as e:
            self.logger.error(f"❌ Partial processing completion failed for {payment_id}: {e}")
            duration = time.time() - start_time
            record_operation_performance("unified_webhook_processing", duration, False)
            return {
                "status": "error",
                "message": f"Partial processing completion failed: {str(e)}",
                "payment_id": payment_id,
                "missing_components": missing_components,
                "duration_seconds": duration,
            }

    def process_refund_webhook(self, payment_id: str, refund_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process refund webhook with unified idempotency management.
        """
        start_time = time.time()

        try:
            refund_id = refund_data.get("id") or refund_data.get("refund", {}).get("id")
            self.logger.info(f"🔄 Processing refund webhook for {refund_id} (payment: {payment_id})")

            # Check unified state first
            processing_state = self.idempotency_manager.check_payment_processing_state(payment_id)

            if not processing_state.payment_entry_exists:
                return {
                    "status": "error",
                    "message": f"Cannot process refund - original payment {payment_id} not found",
                    "payment_id": payment_id,
                    "refund_id": refund_id,
                }

            # Check if this specific refund is already processed
            existing_refund = self.idempotency_manager.check_refund_idempotency(refund_id)
            if existing_refund:
                return {
                    "status": "success",
                    "message": f"Refund {refund_id} already processed",
                    "payment_id": payment_id,
                    "refund_id": refund_id,
                    "existing_reference": existing_refund,
                    "idempotent": True,
                }

            # Process the refund using existing business logic
            result = self.payment_service.process_refund_webhook(refund_data)

            # Mark as processed if successful
            if result.get("status") == "success":
                self.idempotency_manager.mark_refund_processed(
                    payment_id, refund_id, result.get("payment_entry")
                )

            duration = time.time() - start_time
            result["duration_seconds"] = duration

            return result

        except Exception as e:
            self.logger.error(f"❌ Refund webhook processing failed: {e}")
            duration = time.time() - start_time
            return {
                "status": "error",
                "message": f"Refund processing failed: {str(e)}",
                "payment_id": payment_id,
                "refund_id": refund_data.get("id", "unknown"),
                "duration_seconds": duration,
            }

    def _fetch_payment_from_mollie(self, payment_id: str) -> Dict[str, Any]:
        """Fetch payment data from Mollie API."""
        try:
            mollie_settings = frappe.get_single("Mollie Settings")
            mollie = mollie_settings.get_mollie_client()
            payment = mollie.payments.get(payment_id)

            return {
                "id": payment.id,
                "status": payment.status,
                "amount": {"value": payment.amount["value"], "currency": payment.amount["currency"]},
                "description": payment.description,
                "metadata": payment.metadata or {},
                "created_at": payment.created_at,
                "paid_at": getattr(payment, "paid_at", None),
                "method": getattr(payment, "method", None),
            }
        except Exception as e:
            self.logger.error(f"Failed to fetch payment {payment_id} from Mollie: {e}")
            raise MolliePaymentError(f"Cannot fetch payment data: {str(e)}")


# Global instance for backwards compatibility
_unified_webhook_service = None


def get_unified_webhook_service() -> UnifiedWebhookWrapperService:
    """Get the global unified webhook service instance."""
    global _unified_webhook_service
    if _unified_webhook_service is None:
        _unified_webhook_service = UnifiedWebhookWrapperService()
    return _unified_webhook_service
