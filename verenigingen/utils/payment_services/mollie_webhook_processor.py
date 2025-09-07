"""
Mollie Webhook Processor

Processes Mollie webhook notifications with idempotency protection and creates
donation records, payment entries, and payment history entries.
"""

import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

from verenigingen.utils.payment_services.donation_factory import DonationFactory


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

    def process_webhook(self, webhook_payload: str) -> Dict[str, Any]:
        """
        Main webhook processing entry point with full error handling and idempotency.

        Args:
            webhook_payload: JSON string from Mollie webhook

        Returns:
            Dict with processing status and details
        """
        try:
            # Parse webhook data
            webhook_data = (
                json.loads(webhook_payload) if isinstance(webhook_payload, str) else webhook_payload
            )
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

        Uses a custom doctype or table to track processed webhooks.
        """
        try:
            # Check if donation exists with this Mollie payment ID
            existing_donation = frappe.db.exists("Donation", {"payment_id": payment_id})
            if existing_donation:
                return True

            # Check webhook processing log (if we have one)
            # You might want to create a "Webhook Processing Log" doctype
            existing_log = frappe.db.exists(
                "Webhook Processing Log", {"payment_id": payment_id, "status": "completed", "docstatus": 1}
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
            # Try to insert a processing record
            processing_doc = frappe.get_doc(
                {
                    "doctype": "Webhook Processing Log",
                    "payment_id": payment_id,
                    "status": "processing",
                    "environment": self.environment,
                    "started_at": now_datetime(),
                    "expires_at": now_datetime() + timedelta(minutes=5),  # 5 minute lock timeout
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
            frappe.db.delete("Webhook Processing Log", {"payment_id": payment_id, "status": "processing"})
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
            # Update or create webhook processing log
            processing_log = frappe.get_doc(
                {
                    "doctype": "Webhook Processing Log",
                    "payment_id": payment_id,
                    "status": "completed",
                    "environment": self.environment,
                    "completed_at": now_datetime(),
                    "result": json.dumps(result),
                    "donation_id": result.get("donation_id"),
                    "payment_entry_id": result.get("payment_entry_id"),
                }
            )

            processing_log.insert(ignore_if_duplicate=True)
            processing_log.submit()
            frappe.db.commit()

        except Exception as e:
            frappe.log_error(f"Error marking webhook as processed: {str(e)}", "Webhook Completion Logging")
