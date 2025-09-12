"""
Mollie Webhook Processor

Processes Mollie webhook notifications with idempotency protection and creates
donation records, payment entries, and payment history entries.
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

from verenigingen.utils.payment_services.constants import (
    LOG_CATEGORY_SECURITY,
    LOG_CATEGORY_VALIDATION,
    LOG_CATEGORY_WEBHOOK,
    MOLLIE_PAYMENT_STATUS_PAID,
    MOLLIE_REFUND_STATUS_REFUNDED,
    WEBHOOK_PROCESSING_TIMEOUT_MINUTES,
    WEBHOOK_TYPE_CHARGEBACK,
    WEBHOOK_TYPE_PAYMENT,
    WEBHOOK_TYPE_REFUND,
)
from verenigingen.utils.payment_services.logging_utils import (
    PaymentLogger,
    log_signature_validation_failed,
    log_webhook_received,
)

from .donation_factory import DonationFactory


class MollieWebhookProcessor:
    """
    Processes Mollie webhooks and creates donation records with idempotency protection.

    Key features:
    - Idempotency protection to prevent duplicate processing
    - Payment metadata parsing and validation
    - Mollie API querying for complete payment data
    - Orchestrates donation creation via DonationFactory
    """

    def __init__(self, environment: str = "test"):
        """
        Initialize webhook processor.

        Args:
            environment: "test" or "live" for different processing rules
        """
        self.environment = environment
        self.donation_factory = DonationFactory()

        # Initialize Mollie client based on environment
        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

        self.gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

    def _validate_webhook_signature(self, payload: str, signature: str) -> bool:
        """
        Validate webhook signature using Mollie webhook secret.

        Args:
            payload: Raw webhook payload string
            signature: X-Mollie-Signature header value

        Returns:
            Boolean indicating if signature is valid
        """
        try:
            # Get webhook secret from Mollie settings
            mollie_settings = frappe.get_single("Mollie Settings")
            webhook_secret = getattr(mollie_settings, "webhook_secret", None)

            if not webhook_secret:
                frappe.log_error("Mollie webhook secret not configured in settings", LOG_CATEGORY_SECURITY)
                return False

            # Generate expected signature
            expected_signature = hmac.new(
                webhook_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
            ).hexdigest()

            # Compare signatures using constant-time comparison
            return hmac.compare_digest(signature, expected_signature)

        except Exception as e:
            frappe.log_error(f"Error validating webhook signature: {str(e)}", LOG_CATEGORY_SECURITY)
            return False

    def _validate_webhook_payload(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """
        Validate webhook payload structure and content.

        Args:
            webhook_data: Parsed webhook JSON data

        Returns:
            Error message if validation fails, None if valid
        """
        try:
            # Check required top-level fields
            if not isinstance(webhook_data, dict):
                return "Webhook payload must be a JSON object"

            # Validate webhook ID/payment ID
            webhook_id = webhook_data.get("id")
            if not webhook_id:
                return "Missing webhook ID in payload"

            if not isinstance(webhook_id, str) or not webhook_id.strip():
                return "Invalid webhook ID format"

            # Additional validation based on webhook type
            if "payment" in webhook_data:
                return self._validate_payment_webhook_payload(webhook_data)
            elif "refund" in webhook_data:
                return self._validate_refund_webhook_payload(webhook_data)
            elif "chargeback" in webhook_data:
                return self._validate_chargeback_webhook_payload(webhook_data)

            return None

        except Exception as e:
            frappe.log_error(f"Error validating webhook payload: {str(e)}", LOG_CATEGORY_VALIDATION)
            return f"Payload validation error: {str(e)}"

    def _validate_payment_webhook_payload(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """Validate payment-specific webhook payload."""
        payment_id = webhook_data.get("id")
        if not payment_id or not payment_id.startswith(("tr_", "test_")):
            return f"Invalid payment ID format: {payment_id}"
        return None

    def _validate_refund_webhook_payload(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """Validate refund-specific webhook payload."""
        refund_data = webhook_data.get("refund", {})
        if not refund_data.get("id"):
            return "Missing refund ID in webhook payload"

        payment_id = webhook_data.get("payment_id") or webhook_data.get("id")
        if not payment_id:
            return "Missing payment ID in refund webhook"

        return None

    def _validate_chargeback_webhook_payload(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """Validate chargeback-specific webhook payload."""
        chargeback_data = webhook_data.get("chargeback", {})
        if not chargeback_data.get("id"):
            return "Missing chargeback ID in webhook payload"

        payment_id = webhook_data.get("payment_id") or webhook_data.get("id")
        if not payment_id:
            return "Missing payment ID in chargeback webhook"

        return None

    def process_webhook(self, webhook_payload: str, signature: Optional[str] = None) -> Dict[str, Any]:
        """
        Main webhook processing entry point with full error handling and idempotency.

        Args:
            webhook_payload: JSON string from Mollie webhook
            signature: Optional webhook signature for validation

        Returns:
            Dict with processing status and details
        """
        try:
            # Parse webhook data first for signature validation logging
            webhook_data = (
                json.loads(webhook_payload) if isinstance(webhook_payload, str) else webhook_payload
            )

            # Validate webhook signature if provided
            if signature and not self._validate_webhook_signature(webhook_payload, signature):
                log_signature_validation_failed(
                    webhook_data.get("id", "unknown"),
                    {"provided_signature": signature[:20] + "...", "payload_preview": webhook_payload[:100]},
                )
                return {"status": "error", "message": "Invalid webhook signature"}

            # Validate webhook payload structure
            validation_error = self._validate_webhook_payload(webhook_data)
            if validation_error:
                frappe.log_error(
                    f"Webhook payload validation failed: {validation_error}. Payload: {webhook_payload}",
                    LOG_CATEGORY_VALIDATION,
                )
                return {"status": "error", "message": validation_error}

            payment_id = webhook_data.get("id")
            if not payment_id:
                return {"status": "error", "message": "Missing payment ID in webhook"}

            # Idempotency check - prevent duplicate processing
            if self._is_already_processed(payment_id):
                return {
                    "status": "already_processed",
                    "payment_id": payment_id,
                    "message": "Webhook already processed successfully",
                }

            # Mark as processing to prevent concurrent processing
            processing_lock = self._create_processing_lock(payment_id)
            if not processing_lock:
                return {
                    "status": "concurrent_processing",
                    "payment_id": payment_id,
                    "message": "Another instance is processing this webhook",
                }

            try:
                # Query Mollie API for complete payment details
                payment_details = self._fetch_payment_details(payment_id)
                if not payment_details:
                    return {"status": "error", "message": "Failed to fetch payment details from Mollie"}

                # Validate payment status
                if payment_details.get("status") != "paid":
                    return {
                        "status": "payment_not_completed",
                        "payment_id": payment_id,
                        "payment_status": payment_details.get("status"),
                        "message": "Payment not in 'paid' status, skipping donation creation",
                    }

                # Parse and validate payment metadata
                metadata = self._parse_payment_metadata(payment_details)
                if not metadata:
                    return {"status": "error", "message": "Invalid or missing payment metadata"}

                # Create donation and related records
                result = self._process_payment_completion(payment_details, metadata)

                # Mark as successfully processed
                self._mark_as_processed(payment_id, result)

                return result

            finally:
                # Always release the processing lock
                self._release_processing_lock(payment_id)

        except Exception as e:
            error_msg = f"Webhook processing error: {str(e)}"
            frappe.log_error(
                f"{error_msg}\nPayload: {webhook_payload}\nTraceback: {frappe.get_traceback()}",
                "Mollie Webhook Processing Error",
            )
            return {"status": "error", "message": "Internal processing error", "error_logged": True}

    def _is_already_processed(self, payment_id: str) -> bool:
        """
        Check if this payment has already been processed successfully.

        Uses webhook processing log to track processed webhooks.
        """
        try:
            # Check if donation exists with this Mollie payment ID
            existing_donation = frappe.db.exists("Donation", {"payment_id": payment_id})
            if existing_donation:
                return True

            # Check webhook processing log using correct field names
            existing_log = frappe.db.exists(
                "Webhook Processing Log", {"webhook_id": payment_id, "status": "success"}
            )

            return bool(existing_log)

        except Exception as e:
            frappe.log_error(
                f"Error checking webhook processing status: {str(e)}", "Webhook Idempotency Check"
            )
            # On error, assume not processed to be safe
            return False

    def _create_processing_lock(self, payment_id: str) -> bool:
        """
        Create a processing lock to prevent concurrent webhook processing.

        Returns True if lock created successfully, False if already locked.
        """
        try:
            # Try to insert a processing record using correct field names
            processing_doc = frappe.get_doc(
                {
                    "doctype": "Webhook Processing Log",
                    "webhook_id": payment_id,
                    "webhook_type": "payment",
                    "status": "processing",  # This will be changed to "success" when complete
                    "processed_at": now_datetime(),
                }
            )

            processing_doc.insert(ignore_if_duplicate=True)
            frappe.db.commit()
            return True

        except frappe.DuplicateEntryError:
            return False
        except Exception as e:
            frappe.log_error(f"Error creating processing lock: {str(e)}", "Webhook Processing Lock")
            return False

    def _release_processing_lock(self, payment_id: str) -> None:
        """Release processing lock for this payment."""
        try:
            frappe.db.delete("Webhook Processing Log", {"webhook_id": payment_id, "status": "processing"})
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(f"Error releasing processing lock: {str(e)}", "Webhook Lock Release")

    def _fetch_payment_details(self, payment_id: str) -> Optional[Dict[str, Any]]:
        """
        Query Mollie API for complete payment details.

        Args:
            payment_id: Mollie payment ID

        Returns:
            Complete payment data from Mollie API or None if error
        """
        try:
            # Use gateway to fetch payment details
            result = self.gateway.get_payment(payment_id)

            if result.get("status") == "success":
                return result.get("payment_data")
            else:
                frappe.log_error(
                    f"Failed to fetch payment details: {result.get('message')}", "Mollie API Error"
                )
                return None

        except Exception as e:
            frappe.log_error(
                f"Error fetching payment details from Mollie: {str(e)}", "Mollie API Fetch Error"
            )
            return None

    def _parse_payment_metadata(self, payment_details: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse and validate payment metadata from payment description.

        Args:
            payment_details: Complete payment data from Mollie

        Returns:
            Parsed metadata dict or None if invalid
        """
        try:
            # Metadata should be in the payment description as JSON
            description = payment_details.get("description", "")

            if not description:
                frappe.log_error("No description found in payment details", "Metadata Parse Error")
                return None

            # Parse JSON metadata
            try:
                metadata = json.loads(description)
            except json.JSONDecodeError:
                frappe.log_error(
                    f"Failed to parse JSON from description: {description}", "Metadata Parse Error"
                )
                return None

            # Validate required fields
            required_fields = ["type", "donation_id", "donor_email", "donor_name", "amount"]
            for field in required_fields:
                if field not in metadata:
                    frappe.log_error(
                        f"Missing required field '{field}' in metadata: {metadata}",
                        "Metadata Validation Error",
                    )
                    return None

            # Validate amount matches
            payment_amount = flt(payment_details.get("amount", {}).get("value", 0))
            metadata_amount = flt(metadata.get("amount", 0))

            if abs(payment_amount - metadata_amount) > 0.01:  # Allow 1 cent tolerance
                frappe.log_error(
                    f"Amount mismatch: payment={payment_amount}, metadata={metadata_amount}",
                    "Metadata Amount Validation Error",
                )
                return None

            return metadata

        except Exception as e:
            frappe.log_error(f"Error parsing payment metadata: {str(e)}", "Metadata Parse Error")
            return None

    def _process_payment_completion(
        self, payment_details: Dict[str, Any], metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process completed payment by creating donation and related records.

        Args:
            payment_details: Complete payment data from Mollie
            metadata: Parsed and validated metadata

        Returns:
            Processing result dict
        """
        try:
            payment_type = metadata.get("type")

            if payment_type == "single_donation":
                return self._process_single_donation(payment_details, metadata)
            elif payment_type == "recurring_donation":
                return self._process_recurring_donation(payment_details, metadata)
            else:
                return {"status": "error", "message": f"Unknown payment type: {payment_type}"}

        except Exception as e:
            frappe.log_error(
                f"Error processing payment completion: {str(e)}\nPayment: {payment_details}\nMetadata: {metadata}",
                "Payment Processing Error",
            )
            return {"status": "error", "message": "Failed to process payment completion"}

    def _process_single_donation(
        self, payment_details: Dict[str, Any], metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process single donation payment."""
        try:
            # Use DonationFactory to create all required records
            result = self.donation_factory.create_single_donation_from_payment(payment_details, metadata)

            if result["status"] == "success":
                return {
                    "status": "completed",
                    "payment_id": payment_details.get("id"),
                    "donation_id": result["donation_id"],
                    "payment_entry_id": result.get("payment_entry_id"),
                    "message": "Single donation created successfully",
                    "amount": metadata.get("amount"),
                    "donor_name": metadata.get("donor_name"),
                }
            else:
                return result

        except Exception as e:
            frappe.log_error(
                f"Error processing single donation: {str(e)}", "Single Donation Processing Error"
            )
            return {"status": "error", "message": "Failed to process single donation"}

    def _process_recurring_donation(
        self, payment_details: Dict[str, Any], metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process recurring donation payment (first payment or subsequent)."""
        try:
            # Check if this is first payment (has mandate) or recurring payment
            mandate_id = payment_details.get("mandateId")
            subscription_id = payment_details.get("subscriptionId")

            if mandate_id and not subscription_id:
                # This is the first payment - mandate created, subscription will be created by Mollie
                result = self.donation_factory.create_recurring_first_donation_from_payment(
                    payment_details, metadata
                )
            elif subscription_id:
                # This is a recurring payment from an established subscription
                result = self.donation_factory.create_recurring_donation_from_payment(
                    payment_details, metadata
                )
            else:
                return {"status": "error", "message": "Recurring payment missing mandate or subscription ID"}

            if result["status"] == "success":
                return {
                    "status": "completed",
                    "payment_id": payment_details.get("id"),
                    "donation_id": result["donation_id"],
                    "payment_entry_id": result.get("payment_entry_id"),
                    "mandate_id": mandate_id,
                    "subscription_id": subscription_id,
                    "message": "Recurring donation processed successfully",
                    "amount": metadata.get("amount"),
                    "donor_name": metadata.get("donor_name"),
                }
            else:
                return result

        except Exception as e:
            frappe.log_error(
                f"Error processing recurring donation: {str(e)}", "Recurring Donation Processing Error"
            )
            return {"status": "error", "message": "Failed to process recurring donation"}

    def _mark_as_processed(self, payment_id: str, result: Dict[str, Any]) -> None:
        """Mark webhook as successfully processed."""
        try:
            # Update existing processing record or create new one using correct field names
            existing_log = frappe.db.get_value("Webhook Processing Log", {"webhook_id": payment_id}, "name")

            if existing_log:
                # Update existing record
                log_doc = frappe.get_doc("Webhook Processing Log", existing_log)
                log_doc.status = "success"
                log_doc.processed_at = now_datetime()
                log_doc.processing_result = json.dumps(result)
                log_doc.save()
            else:
                # Create new record
                processing_log = frappe.get_doc(
                    {
                        "doctype": "Webhook Processing Log",
                        "webhook_id": payment_id,
                        "webhook_type": "payment",
                        "status": "success",
                        "processed_at": now_datetime(),
                        "processing_result": json.dumps(result),
                    }
                )
                processing_log.insert()

            frappe.db.commit()

        except Exception as e:
            frappe.log_error(f"Error marking webhook as processed: {str(e)}", "Webhook Completion Logging")

    def process_refund_webhook(self, webhook_payload: str) -> Dict[str, Any]:
        """
        Process Mollie refund webhook to create reverse Payment Entry and update donation history.

        Args:
            webhook_payload: JSON string from Mollie refund webhook

        Returns:
            Dict with processing status and details
        """
        try:
            # Parse webhook data
            webhook_data = (
                json.loads(webhook_payload) if isinstance(webhook_payload, str) else webhook_payload
            )

            payment_id = webhook_data.get("payment_id") or webhook_data.get("id")
            refund_id = webhook_data.get("refund_id") or webhook_data.get("refund", {}).get("id")

            if not payment_id or not refund_id:
                return {"status": "error", "message": "Missing payment_id or refund_id in refund webhook"}

            # Check for duplicate refund processing
            existing_refund = frappe.db.exists(
                "Payment Entry", {"reference_no": refund_id, "payment_type": "Pay"}
            )

            if existing_refund:
                return {
                    "status": "already_processed",
                    "refund_id": refund_id,
                    "message": "Refund already processed",
                }

            # Fetch refund details from Mollie API
            refund_details = self._fetch_refund_details(payment_id, refund_id)
            if not refund_details:
                return {"status": "error", "message": "Failed to fetch refund details from Mollie"}

            # Only process paid refunds
            if refund_details.get("status") != "refunded":
                return {
                    "status": "refund_not_completed",
                    "refund_id": refund_id,
                    "refund_status": refund_details.get("status"),
                    "message": "Refund not in 'refunded' status",
                }

            # Find the original Payment Entry
            original_payment = frappe.db.get_value(
                "Payment Entry",
                {"reference_no": payment_id, "payment_type": "Receive"},
                ["name", "party", "paid_amount", "paid_from", "paid_to"],
            )

            if not original_payment:
                return {
                    "status": "error",
                    "message": f"Original payment entry not found for payment_id: {payment_id}",
                }

            # Find associated donation
            donation_name = frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")
            if not donation_name:
                return {"status": "error", "message": f"Donation not found for payment_id: {payment_id}"}

            # Create reverse Payment Entry for the refund
            refund_result = self._create_refund_payment_entry(refund_details, original_payment, donation_name)

            if refund_result["status"] == "success":
                # Update donation payment history
                self._update_donation_refund_history(
                    donation_name, refund_details, refund_result["payment_entry_id"]
                )

                return {
                    "status": "completed",
                    "payment_id": payment_id,
                    "refund_id": refund_id,
                    "donation_id": donation_name,
                    "refund_payment_entry_id": refund_result["payment_entry_id"],
                    "refund_amount": refund_details.get("amount", {}).get("value"),
                    "message": "Refund processed successfully",
                }
            else:
                return refund_result

        except Exception as e:
            frappe.log_error(
                f"Refund webhook processing error: {str(e)}\nPayload: {webhook_payload}",
                "Mollie Refund Webhook Error",
            )
            return {"status": "error", "message": "Internal refund processing error"}

    def process_chargeback_webhook(self, webhook_payload: str) -> Dict[str, Any]:
        """
        Process Mollie chargeback webhook to create reverse Payment Entry and update donation history.

        Args:
            webhook_payload: JSON string from Mollie chargeback webhook

        Returns:
            Dict with processing status and details
        """
        try:
            # Parse webhook data
            webhook_data = (
                json.loads(webhook_payload) if isinstance(webhook_payload, str) else webhook_payload
            )

            payment_id = webhook_data.get("payment_id") or webhook_data.get("id")
            chargeback_id = webhook_data.get("chargeback_id") or webhook_data.get("chargeback", {}).get("id")

            if not payment_id or not chargeback_id:
                return {
                    "status": "error",
                    "message": "Missing payment_id or chargeback_id in chargeback webhook",
                }

            # Check for duplicate chargeback processing
            existing_chargeback = frappe.db.exists(
                "Payment Entry", {"reference_no": chargeback_id, "payment_type": "Pay"}
            )

            if existing_chargeback:
                return {
                    "status": "already_processed",
                    "chargeback_id": chargeback_id,
                    "message": "Chargeback already processed",
                }

            # Fetch chargeback details from Mollie API
            chargeback_details = self._fetch_chargeback_details(payment_id, chargeback_id)
            if not chargeback_details:
                return {"status": "error", "message": "Failed to fetch chargeback details from Mollie"}

            # Find the original Payment Entry
            original_payment = frappe.db.get_value(
                "Payment Entry",
                {"reference_no": payment_id, "payment_type": "Receive"},
                ["name", "party", "paid_amount", "paid_from", "paid_to"],
            )

            if not original_payment:
                return {
                    "status": "error",
                    "message": f"Original payment entry not found for payment_id: {payment_id}",
                }

            # Find associated donation
            donation_name = frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")
            if not donation_name:
                return {"status": "error", "message": f"Donation not found for payment_id: {payment_id}"}

            # Create reverse Payment Entry for the chargeback
            chargeback_result = self._create_chargeback_payment_entry(
                chargeback_details, original_payment, donation_name
            )

            if chargeback_result["status"] == "success":
                # Update donation payment history
                self._update_donation_chargeback_history(
                    donation_name, chargeback_details, chargeback_result["payment_entry_id"]
                )

                return {
                    "status": "completed",
                    "payment_id": payment_id,
                    "chargeback_id": chargeback_id,
                    "donation_id": donation_name,
                    "chargeback_payment_entry_id": chargeback_result["payment_entry_id"],
                    "chargeback_amount": chargeback_details.get("amount", {}).get("value"),
                    "message": "Chargeback processed successfully",
                }
            else:
                return chargeback_result

        except Exception as e:
            frappe.log_error(
                f"Chargeback webhook processing error: {str(e)}\nPayload: {webhook_payload}",
                "Mollie Chargeback Webhook Error",
            )
            return {"status": "error", "message": "Internal chargeback processing error"}

    def _fetch_refund_details(self, payment_id: str, refund_id: str) -> Optional[Dict[str, Any]]:
        """Fetch refund details from Mollie API."""
        try:
            refund = self.gateway.client.payment_refunds.get(refund_id, payment_id=payment_id)
            if refund:
                return {
                    "id": refund.id,
                    "amount": {"value": refund.amount.value, "currency": refund.amount.currency},
                    "status": refund.status,
                    "description": refund.description,
                    "created_at": refund.created_at.isoformat() if refund.created_at else None,
                    "payment_id": payment_id,
                }
            return None
        except Exception as e:
            frappe.log_error(f"Error fetching refund details: {str(e)}", "Mollie Refund Fetch Error")
            return None

    def _fetch_chargeback_details(self, payment_id: str, chargeback_id: str) -> Optional[Dict[str, Any]]:
        """Fetch chargeback details from Mollie API."""
        try:
            chargeback = self.gateway.client.payment_chargebacks.get(chargeback_id, payment_id=payment_id)
            if chargeback:
                return {
                    "id": chargeback.id,
                    "amount": {"value": chargeback.amount.value, "currency": chargeback.amount.currency},
                    "reason": getattr(chargeback, "reason", {}),
                    "created_at": chargeback.created_at.isoformat() if chargeback.created_at else None,
                    "reversed_at": getattr(chargeback, "reversed_at", None),
                    "payment_id": payment_id,
                }
            return None
        except Exception as e:
            frappe.log_error(f"Error fetching chargeback details: {str(e)}", "Mollie Chargeback Fetch Error")
            return None

    def _create_refund_payment_entry(
        self, refund_details: Dict[str, Any], original_payment: Tuple, donation_name: str
    ) -> Dict[str, Any]:
        """Create reverse Payment Entry for refund."""
        try:
            # DonationFactory already imported at top of file

            # Get Mollie clearing account from settings
            mollie_settings = frappe.get_single("Mollie Settings")
            mollie_clearing_account = getattr(mollie_settings, "mollie_clearing_account", None)

            if not mollie_clearing_account:
                return {
                    "status": "error",
                    "message": "mollie_clearing_account not configured in Mollie Settings",
                }

            refund_amount = flt(refund_details.get("amount", {}).get("value", 0))

            # Create reverse payment entry (Pay type) to reverse the original Receive
            payment_entry_doc = frappe.get_doc(
                {
                    "doctype": "Payment Entry",
                    "payment_type": "Pay",  # Reverse of original Receive
                    "party_type": "Donor",
                    "party": original_payment[1],  # Same donor
                    "paid_from": original_payment[4],  # paid_to becomes paid_from (reverse)
                    "paid_to": mollie_clearing_account,  # paid_from becomes paid_to (reverse)
                    "paid_amount": refund_amount,
                    "received_amount": refund_amount,
                    "reference_no": refund_details.get("id"),
                    "reference_date": getdate(refund_details.get("created_at"))
                    if refund_details.get("created_at")
                    else getdate(),
                    "remarks": f"Mollie refund for donation {donation_name}. Description: {refund_details.get('description', 'N/A')}",
                    "custom_donation": donation_name,
                    "custom_reversal_type": "Refund",
                    "custom_original_payment_id": refund_details.get("payment_id"),
                }
            )

            payment_entry_doc.insert()
            payment_entry_doc.submit()

            return {"status": "success", "payment_entry_id": payment_entry_doc.name, "amount": refund_amount}

        except Exception as e:
            frappe.log_error(
                f"Error creating refund payment entry: {str(e)}", "Refund Payment Entry Creation Error"
            )
            return {"status": "error", "message": "Failed to create refund payment entry"}

    def _create_chargeback_payment_entry(
        self, chargeback_details: Dict[str, Any], original_payment: Tuple, donation_name: str
    ) -> Dict[str, Any]:
        """Create reverse Payment Entry for chargeback."""
        try:
            # DonationFactory already imported at top of file

            # Get Mollie clearing account from settings
            mollie_settings = frappe.get_single("Mollie Settings")
            mollie_clearing_account = getattr(mollie_settings, "mollie_clearing_account", None)

            if not mollie_clearing_account:
                return {
                    "status": "error",
                    "message": "mollie_clearing_account not configured in Mollie Settings",
                }

            chargeback_amount = flt(chargeback_details.get("amount", {}).get("value", 0))
            chargeback_reason = chargeback_details.get("reason", {})
            reason_text = f"{chargeback_reason.get('code', 'unknown')} - {chargeback_reason.get('description', 'No description')}"

            # Create reverse payment entry (Pay type) to reverse the original Receive
            payment_entry_doc = frappe.get_doc(
                {
                    "doctype": "Payment Entry",
                    "payment_type": "Pay",  # Reverse of original Receive
                    "party_type": "Donor",
                    "party": original_payment[1],  # Same donor
                    "paid_from": original_payment[4],  # paid_to becomes paid_from (reverse)
                    "paid_to": mollie_clearing_account,  # paid_from becomes paid_to (reverse)
                    "paid_amount": chargeback_amount,
                    "received_amount": chargeback_amount,
                    "reference_no": chargeback_details.get("id"),
                    "reference_date": getdate(chargeback_details.get("created_at"))
                    if chargeback_details.get("created_at")
                    else getdate(),
                    "remarks": f"Mollie chargeback for donation {donation_name}. Reason: {reason_text}",
                    "custom_donation": donation_name,
                    "custom_reversal_type": "Chargeback",
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
            frappe.log_error(
                f"Error creating chargeback payment entry: {str(e)}",
                "Chargeback Payment Entry Creation Error",
            )
            return {"status": "error", "message": "Failed to create chargeback payment entry"}

    def _update_donation_refund_history(
        self, donation_name: str, refund_details: Dict[str, Any], payment_entry_id: str
    ) -> None:
        """Update donation payment history with refund information."""
        try:
            # Get the donation document
            donation_doc = frappe.get_doc("Donation", donation_name)

            # Add refund to payment history
            refund_amount = flt(refund_details.get("amount", {}).get("value", 0))

            donation_doc.append(
                "payment_history",
                {
                    "payment_date": getdate(refund_details.get("created_at"))
                    if refund_details.get("created_at")
                    else getdate(),
                    "payment_method": "Mollie Refund",
                    "amount": -(refund_amount or 0),  # Negative amount for refund
                    "payment_entry": payment_entry_id,
                    "mollie_payment_id": refund_details.get("id"),
                    "notes": f"Refund: {refund_details.get('description', 'N/A')}",
                },
            )

            donation_doc.save()

        except Exception as e:
            frappe.log_error(
                f"Error updating donation refund history: {str(e)}", "Donation Refund History Update Error"
            )

    def _update_donation_chargeback_history(
        self, donation_name: str, chargeback_details: Dict[str, Any], payment_entry_id: str
    ) -> None:
        """Update donation payment history with chargeback information."""
        try:
            # Get the donation document
            donation_doc = frappe.get_doc("Donation", donation_name)

            # Add chargeback to payment history
            chargeback_amount = flt(chargeback_details.get("amount", {}).get("value", 0))
            chargeback_reason = chargeback_details.get("reason", {})
            reason_text = f"{chargeback_reason.get('code', 'unknown')} - {chargeback_reason.get('description', 'No description')}"

            donation_doc.append(
                "payment_history",
                {
                    "payment_date": getdate(chargeback_details.get("created_at"))
                    if chargeback_details.get("created_at")
                    else getdate(),
                    "payment_method": "Mollie Chargeback",
                    "amount": -(chargeback_amount or 0),  # Negative amount for chargeback
                    "payment_entry": payment_entry_id,
                    "mollie_payment_id": chargeback_details.get("id"),
                    "notes": f"Chargeback: {reason_text}",
                },
            )

            donation_doc.save()

        except Exception as e:
            frappe.log_error(
                f"Error updating donation chargeback history: {str(e)}",
                "Donation Chargeback History Update Error",
            )
