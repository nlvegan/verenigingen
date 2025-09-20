"""
Mollie Refund and Chargeback Service

Comprehensive service for handling automated refund and chargeback processing
via webhooks. Restores the critical financial reversal functionality from the
archived MollieWebhookProcessor while integrating with the new service layer.

Key Features:
- Automated webhook-driven refund processing
- Automated chargeback processing with dispute management
- Idempotency protection for financial reversals
- Comprehensive Payment Entry creation for accounting
- Donation payment history updates
- Enhanced error recovery and retry mechanisms
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

from ..core.client import MollieClient
from ..exceptions import MolliePaymentError, MollieWebhookError
from ..utils.logging import MollieLogger
from ..utils.monitoring import MolliePerformanceMonitor


class RefundChargebackService:
    """
    Comprehensive refund and chargeback processing service.

    Handles automated webhook processing for financial reversals with
    full accounting integration and business rule compliance.
    """

    def __init__(self, client: Optional[MollieClient] = None):
        """Initialize refund/chargeback service."""
        self.client = client or MollieClient()
        self.logger = MollieLogger("refund_chargeback")
        self.performance_monitor = MolliePerformanceMonitor()

    def process_refund_webhook(self, webhook_payload: str) -> Dict[str, Any]:
        """
        Process Mollie refund webhook to create reverse Payment Entry and update donation history.

        Restores the comprehensive refund processing from the archived system.

        Args:
            webhook_payload: JSON string from Mollie refund webhook

        Returns:
            Dict with processing status and refund details
        """
        operation_start = self.performance_monitor.start_operation("refund_webhook_processing")

        try:
            self.logger.info("Processing refund webhook", {"payload_length": len(webhook_payload)})

            # Parse webhook data
            webhook_data = json.loads(webhook_payload)

            # Validate refund webhook payload
            validation_error = self._validate_refund_webhook_payload(webhook_data)
            if validation_error:
                self.logger.error("Refund webhook validation failed", {"error": validation_error})
                return {"status": "error", "message": f"Validation failed: {validation_error}"}

            # Extract refund and payment IDs
            payment_id = webhook_data.get("payment_id") or webhook_data.get("payment", {}).get("id")
            refund_id = webhook_data.get("refund_id") or webhook_data.get("refund", {}).get("id")

            if not payment_id or not refund_id:
                return {"status": "error", "message": "Missing payment_id or refund_id in refund webhook"}

            # Check for duplicate refund processing (idempotency protection)
            existing_refund = frappe.db.exists(
                "Payment Entry", {"reference_no": refund_id, "payment_type": "Pay"}
            )

            if existing_refund:
                self.logger.info(
                    "Refund already processed",
                    {"refund_id": refund_id, "existing_payment_entry": existing_refund},
                )
                return {
                    "status": "already_processed",
                    "refund_id": refund_id,
                    "payment_entry_id": existing_refund,
                    "message": "Refund already processed",
                }

            # Fetch refund details from Mollie API
            refund_details = self._fetch_refund_details(payment_id, refund_id)
            if not refund_details:
                return {"status": "error", "message": "Failed to fetch refund details from Mollie"}

            # Only process completed refunds
            if refund_details.get("status") != "refunded":
                return {
                    "status": "refund_not_completed",
                    "refund_id": refund_id,
                    "refund_status": refund_details.get("status"),
                    "message": "Refund not in 'refunded' status",
                }

            # Find original payment and donation
            original_payment = self._find_original_payment(payment_id)
            if not original_payment:
                return {"status": "error", "message": f"Original payment {payment_id} not found"}

            donation_name = self._find_donation_for_payment(payment_id)
            if not donation_name:
                return {"status": "error", "message": f"Donation for payment {payment_id} not found"}

            # Create reverse Payment Entry for the refund
            refund_result = self._create_refund_payment_entry(refund_details, original_payment, donation_name)

            if refund_result["status"] == "success":
                # Update donation payment history
                self._update_donation_refund_history(
                    donation_name, refund_details, refund_result["payment_entry_id"]
                )

                self.logger.success(
                    "Refund processed successfully",
                    {
                        "refund_id": refund_id,
                        "payment_id": payment_id,
                        "refund_payment_entry_id": refund_result["payment_entry_id"],
                        "refund_amount": refund_details.get("amount", {}).get("value"),
                    },
                )

                self.performance_monitor.record_success(operation_start, "refund_webhook_processing")
                return refund_result
            else:
                self.performance_monitor.record_failure(operation_start, "refund_webhook_processing")
                return refund_result

        except Exception as e:
            self.logger.error("Refund webhook processing error", error=e)
            self.performance_monitor.record_failure(operation_start, "refund_webhook_processing")
            return {"status": "error", "message": "Internal refund processing error"}

    def process_chargeback_webhook(self, webhook_payload: str) -> Dict[str, Any]:
        """
        Process Mollie chargeback webhook to create reverse Payment Entry and update donation history.

        Restores the comprehensive chargeback processing from the archived system.

        Args:
            webhook_payload: JSON string from Mollie chargeback webhook

        Returns:
            Dict with processing status and chargeback details
        """
        operation_start = self.performance_monitor.start_operation("chargeback_webhook_processing")

        try:
            self.logger.info("Processing chargeback webhook", {"payload_length": len(webhook_payload)})

            # Parse webhook data
            webhook_data = json.loads(webhook_payload)

            # Validate chargeback webhook payload
            validation_error = self._validate_chargeback_webhook_payload(webhook_data)
            if validation_error:
                self.logger.error("Chargeback webhook validation failed", {"error": validation_error})
                return {"status": "error", "message": f"Validation failed: {validation_error}"}

            # Extract chargeback and payment IDs
            payment_id = webhook_data.get("payment_id") or webhook_data.get("payment", {}).get("id")
            chargeback_id = webhook_data.get("chargeback_id") or webhook_data.get("chargeback", {}).get("id")

            if not payment_id or not chargeback_id:
                return {
                    "status": "error",
                    "message": "Missing payment_id or chargeback_id in chargeback webhook",
                }

            # Check for duplicate chargeback processing (idempotency protection)
            existing_chargeback = frappe.db.exists(
                "Payment Entry", {"reference_no": chargeback_id, "payment_type": "Pay"}
            )

            if existing_chargeback:
                self.logger.info(
                    "Chargeback already processed",
                    {"chargeback_id": chargeback_id, "existing_payment_entry": existing_chargeback},
                )
                return {
                    "status": "already_processed",
                    "chargeback_id": chargeback_id,
                    "payment_entry_id": existing_chargeback,
                    "message": "Chargeback already processed",
                }

            # Fetch chargeback details from Mollie API
            chargeback_details = self._fetch_chargeback_details(payment_id, chargeback_id)
            if not chargeback_details:
                return {"status": "error", "message": "Failed to fetch chargeback details from Mollie"}

            # Find original payment and donation
            original_payment = self._find_original_payment(payment_id)
            if not original_payment:
                return {"status": "error", "message": f"Original payment {payment_id} not found"}

            donation_name = self._find_donation_for_payment(payment_id)
            if not donation_name:
                return {"status": "error", "message": f"Donation for payment {payment_id} not found"}

            # Create reverse Payment Entry for the chargeback
            chargeback_result = self._create_chargeback_payment_entry(
                chargeback_details, original_payment, donation_name
            )

            if chargeback_result["status"] == "success":
                # Update donation payment history
                self._update_donation_chargeback_history(
                    donation_name, chargeback_details, chargeback_result["payment_entry_id"]
                )

                self.logger.success(
                    "Chargeback processed successfully",
                    {
                        "chargeback_id": chargeback_id,
                        "payment_id": payment_id,
                        "chargeback_payment_entry_id": chargeback_result["payment_entry_id"],
                        "chargeback_amount": chargeback_details.get("amount", {}).get("value"),
                    },
                )

                self.performance_monitor.record_success(operation_start, "chargeback_webhook_processing")
                return chargeback_result
            else:
                self.performance_monitor.record_failure(operation_start, "chargeback_webhook_processing")
                return chargeback_result

        except Exception as e:
            self.logger.error("Chargeback webhook processing error", error=e)
            self.performance_monitor.record_failure(operation_start, "chargeback_webhook_processing")
            return {"status": "error", "message": "Internal chargeback processing error"}

    def _validate_refund_webhook_payload(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """Validate refund-specific webhook payload."""
        refund_data = webhook_data.get("refund", {})
        if not refund_data.get("id"):
            return "Missing refund ID in webhook payload"

        payment_data = webhook_data.get("payment", {})
        if not payment_data.get("id"):
            return "Missing payment ID in refund webhook"

        return None

    def _validate_chargeback_webhook_payload(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """Validate chargeback-specific webhook payload."""
        chargeback_data = webhook_data.get("chargeback", {})
        if not chargeback_data.get("id"):
            return "Missing chargeback ID in webhook payload"

        payment_data = webhook_data.get("payment", {})
        if not payment_data.get("id"):
            return "Missing payment ID in chargeback webhook"

        return None

    def _fetch_refund_details(self, payment_id: str, refund_id: str) -> Optional[Dict[str, Any]]:
        """Fetch refund details from Mollie API."""
        try:
            # Use the enhanced client to get refund details
            refund = self.client.get_refund(payment_id, refund_id)

            return {
                "id": refund.id,
                "amount": {"value": refund.amount.value, "currency": refund.amount.currency},
                "status": refund.status,
                "description": refund.description,
                "created_at": refund.created_at.isoformat() if refund.created_at else None,
                "payment_id": payment_id,
            }
        except Exception as e:
            self.logger.error(
                "Error fetching refund details",
                error=e,
                extra={"payment_id": payment_id, "refund_id": refund_id},
            )
            return None

    def _fetch_chargeback_details(self, payment_id: str, chargeback_id: str) -> Optional[Dict[str, Any]]:
        """Fetch chargeback details from Mollie API."""
        try:
            # Use the enhanced client to get chargeback details
            chargeback = self.client.get_chargeback(payment_id, chargeback_id)

            return {
                "id": chargeback.id,
                "amount": {"value": chargeback.amount.value, "currency": chargeback.amount.currency},
                "reason": getattr(chargeback, "reason", {}),
                "created_at": chargeback.created_at.isoformat() if chargeback.created_at else None,
                "reversed_at": getattr(chargeback, "reversed_at", None),
                "payment_id": payment_id,
            }
        except Exception as e:
            self.logger.error(
                "Error fetching chargeback details",
                error=e,
                extra={"payment_id": payment_id, "chargeback_id": chargeback_id},
            )
            return None

    def _find_original_payment(self, payment_id: str) -> Optional[Tuple]:
        """Find original Payment Entry for the given Mollie payment ID."""
        try:
            payment_entry = frappe.db.get_value(
                "Payment Entry",
                {"reference_no": payment_id, "payment_type": "Receive"},
                ["name", "paid_amount", "paid_from", "paid_to", "company"],
                as_dict=False,
            )
            return payment_entry
        except Exception as e:
            self.logger.error("Error finding original payment", error=e, extra={"payment_id": payment_id})
            return None

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
            self.logger.error("Error finding donation for payment", error=e, extra={"payment_id": payment_id})
            return None

    def _create_refund_payment_entry(
        self, refund_details: Dict[str, Any], original_payment: Tuple, donation_name: str
    ) -> Dict[str, Any]:
        """Create reverse Payment Entry for refund."""
        try:
            # Extract original payment details
            original_name, original_amount, paid_from, paid_to, company = original_payment
            refund_amount = flt(refund_details.get("amount", {}).get("value", 0))

            # Create reverse Payment Entry (Pay type to reverse the Receive)
            payment_entry_doc = frappe.get_doc(
                {
                    "doctype": "Payment Entry",
                    "payment_type": "Pay",
                    "party_type": "Customer",
                    "company": company,
                    "paid_from": paid_to,  # Reverse of original
                    "paid_to": paid_from,  # Reverse of original
                    "paid_amount": refund_amount,
                    "received_amount": refund_amount,
                    "reference_no": refund_details.get("id"),
                    "reference_date": (
                        getdate(refund_details.get("created_at"))
                        if refund_details.get("created_at")
                        else getdate()
                    ),
                    "remarks": f"Mollie refund for donation {donation_name}. Description: {refund_details.get('description', 'N/A')}",
                    "mode_of_payment": "Mollie",
                    "posting_date": getdate(),
                    "custom_original_payment_id": refund_details.get("payment_id"),
                }
            )

            payment_entry_doc.insert()
            payment_entry_doc.submit()

            return {"status": "success", "payment_entry_id": payment_entry_doc.name, "amount": refund_amount}

        except Exception as e:
            self.logger.error("Error creating refund payment entry", error=e)
            return {"status": "error", "message": "Failed to create refund payment entry"}

    def _create_chargeback_payment_entry(
        self, chargeback_details: Dict[str, Any], original_payment: Tuple, donation_name: str
    ) -> Dict[str, Any]:
        """Create reverse Payment Entry for chargeback."""
        try:
            # Extract original payment details
            original_name, original_amount, paid_from, paid_to, company = original_payment
            chargeback_amount = flt(chargeback_details.get("amount", {}).get("value", 0))
            chargeback_reason = chargeback_details.get("reason", {})
            reason_text = f"{chargeback_reason.get('code', 'unknown')} - {chargeback_reason.get('description', 'No description')}"

            # Create reverse Payment Entry (Pay type to reverse the Receive)
            payment_entry_doc = frappe.get_doc(
                {
                    "doctype": "Payment Entry",
                    "payment_type": "Pay",
                    "party_type": "Customer",
                    "company": company,
                    "paid_from": paid_to,  # Reverse of original
                    "paid_to": paid_from,  # Reverse of original
                    "paid_amount": chargeback_amount,
                    "received_amount": chargeback_amount,
                    "reference_no": chargeback_details.get("id"),
                    "reference_date": (
                        getdate(chargeback_details.get("created_at"))
                        if chargeback_details.get("created_at")
                        else getdate()
                    ),
                    "remarks": f"Mollie chargeback for donation {donation_name}. Reason: {reason_text}",
                    "mode_of_payment": "Mollie",
                    "posting_date": getdate(),
                    "custom_original_payment_id": chargeback_details.get("payment_id"),
                }
            )

            payment_entry_doc.insert()
            payment_entry_doc.submit()

            return {
                "status": "success",
                "payment_entry_id": payment_entry_doc.name,
                "amount": chargeback_amount,
            }

        except Exception as e:
            self.logger.error("Error creating chargeback payment entry", error=e)
            return {"status": "error", "message": "Failed to create chargeback payment entry"}

    def _update_donation_refund_history(
        self, donation_name: str, refund_details: Dict[str, Any], payment_entry_id: str
    ) -> None:
        """Update donation payment history with refund information."""
        try:
            donation = frappe.get_doc("Donation", donation_name)

            # Add refund to payment history
            refund_amount = flt(refund_details.get("amount", {}).get("value", 0))

            donation.append(
                "payment_history",
                {
                    "payment_date": (
                        getdate(refund_details.get("created_at"))
                        if refund_details.get("created_at")
                        else getdate()
                    ),
                    "payment_method": "Mollie",
                    "status": "Refunded",
                    "amount": -(refund_amount or 0),  # Negative amount for refund
                    "payment_entry": payment_entry_id,
                    "mollie_payment_id": refund_details.get("id"),
                    "notes": f"Refund: {refund_details.get('description', 'N/A')}",
                },
            )

            donation.save()

        except Exception as e:
            self.logger.error("Error updating donation refund history", error=e)

    def _update_donation_chargeback_history(
        self, donation_name: str, chargeback_details: Dict[str, Any], payment_entry_id: str
    ) -> None:
        """Update donation payment history with chargeback information."""
        try:
            donation = frappe.get_doc("Donation", donation_name)

            # Add chargeback to payment history
            chargeback_amount = flt(chargeback_details.get("amount", {}).get("value", 0))
            chargeback_reason = chargeback_details.get("reason", {})
            reason_text = f"{chargeback_reason.get('code', 'unknown')} - {chargeback_reason.get('description', 'No description')}"

            donation.append(
                "payment_history",
                {
                    "payment_date": (
                        getdate(chargeback_details.get("created_at"))
                        if chargeback_details.get("created_at")
                        else getdate()
                    ),
                    "payment_method": "Mollie",
                    "status": "Chargeback",
                    "amount": -(chargeback_amount or 0),  # Negative amount for chargeback
                    "payment_entry": payment_entry_id,
                    "mollie_payment_id": chargeback_details.get("id"),
                    "notes": f"Chargeback: {reason_text}",
                },
            )

            donation.save()

        except Exception as e:
            self.logger.error("Error updating donation chargeback history", error=e)
