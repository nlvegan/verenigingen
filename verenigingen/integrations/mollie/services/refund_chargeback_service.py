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

            # Log refund status for debugging (consolidated logging will be done at bulk level)
            refund_status = refund_details.get("status")

            # Process refunds in completed states (refunded, processed, etc.)
            valid_refund_statuses = ["refunded", "processed", "pending"]
            if refund_status not in valid_refund_statuses:
                return {
                    "status": "refund_not_completed",
                    "refund_id": refund_id,
                    "refund_status": refund_status,
                    "message": f"Refund status '{refund_status}' not in valid statuses: {valid_refund_statuses}",
                }

            # Find original payment and donation
            original_payment = self._find_original_payment(payment_id)
            if not original_payment:
                return {"status": "error", "message": f"Original payment {payment_id} not found"}

            donation_name = self._find_donation_for_payment(payment_id)
            if not donation_name:
                return {"status": "error", "message": f"Donation for payment {payment_id} not found"}

            # Get donation document and create Credit Note for refund
            donation_doc = frappe.get_doc("Donation", donation_name)
            refund_amount = flt(refund_details.get("amount", {}).get("value", 0))

            credit_note_result = self._create_refund_credit_note(refund_details, donation_doc, refund_amount)

            # Always try to update payment history, regardless of Credit Note success
            payment_history_updated = False
            if credit_note_result["status"] == "success":
                # Update donation payment history with Credit Note
                try:
                    self._update_donation_refund_history(
                        donation_name, refund_details, credit_note_result["credit_note"]
                    )
                    payment_history_updated = True
                except Exception as e:
                    self.logger.error(f"Failed to update payment history for Credit Note: {e}")
            else:
                # Try Payment Entry fallback AND update payment history independently
                try:
                    payment_entry_result = self._create_refund_payment_entry(
                        refund_details, donation_doc, refund_amount
                    )
                    if payment_entry_result.get("status") == "success":
                        # Payment Entry succeeded, try to update payment history
                        try:
                            self._update_donation_refund_history_payment_entry(
                                donation_name, refund_details, payment_entry_result.get("payment_entry_id")
                            )
                            payment_history_updated = True
                        except Exception as pe_history_error:
                            self.logger.error(
                                f"Payment Entry created but payment history update failed: {pe_history_error}"
                            )
                    else:
                        # Payment Entry failed, but still try to update payment history
                        try:
                            self._update_donation_refund_history_payment_entry(
                                donation_name, refund_details, None
                            )
                            payment_history_updated = True
                        except Exception as fallback_error:
                            self.logger.error(
                                f"Both Payment Entry and payment history update failed: {fallback_error}"
                            )
                except Exception as e:
                    self.logger.error(f"Payment Entry fallback completely failed: {e}")
                    # Still try to update payment history as standalone operation
                    try:
                        self._update_donation_refund_history_payment_entry(
                            donation_name, refund_details, None
                        )
                        payment_history_updated = True
                    except Exception as standalone_error:
                        self.logger.error(
                            f"Standalone payment history update also failed: {standalone_error}"
                        )

            # Determine overall success based on Credit Note OR payment history update
            if credit_note_result["status"] == "success" or payment_history_updated:
                success_details = {
                    "refund_id": refund_id,
                    "payment_id": payment_id,
                    "refund_amount": refund_details.get("amount", {}).get("value"),
                    "payment_history_updated": payment_history_updated,
                }

                if credit_note_result["status"] == "success":
                    success_details["credit_note"] = credit_note_result["credit_note"]
                    success_details["method"] = "Credit Note"
                else:
                    success_details["method"] = "Payment History Only"

                self.logger.success("Refund processed successfully", success_details)
                self.performance_monitor.record_success(operation_start, "refund_webhook_processing")

                return {
                    "status": "success",
                    "payment_history_updated": payment_history_updated,
                    "credit_note": credit_note_result.get("credit_note"),
                    "method": success_details["method"],
                }
            elif credit_note_result["status"] == "error":
                # Credit Note failed - try Payment Entry fallback
                self.logger.info(
                    "Credit Note skipped - trying Payment Entry fallback",
                    {
                        "refund_id": refund_id,
                        "payment_id": payment_id,
                        "message": credit_note_result["message"],
                    },
                )

                # Try Payment Entry approach for donations without Sales Invoices
                payment_entry_result = self._create_refund_payment_entry(
                    refund_details, donation_doc, refund_amount, original_payment
                )

                if payment_entry_result["status"] == "success":
                    # Update donation payment history with Payment Entry reference
                    self._update_donation_refund_history_payment_entry(
                        donation_name, refund_details, payment_entry_result["payment_entry"]
                    )

                    self.logger.success(
                        "Refund processed via Payment Entry fallback",
                        {
                            "refund_id": refund_id,
                            "payment_id": payment_id,
                            "payment_entry": payment_entry_result["payment_entry"],
                            "refund_amount": refund_details.get("amount", {}).get("value"),
                        },
                    )

                    self.performance_monitor.record_success(operation_start, "refund_webhook_processing")
                    return payment_entry_result
                else:
                    # Both methods failed
                    self.logger.error(
                        "Both Credit Note and Payment Entry approaches failed",
                        {
                            "refund_id": refund_id,
                            "payment_id": payment_id,
                            "credit_note_error": credit_note_result["message"],
                            "payment_entry_error": payment_entry_result.get("message", "Unknown error"),
                        },
                    )
                    self.performance_monitor.record_failure(operation_start, "refund_webhook_processing")
                    return {
                        "status": "error",
                        "message": f"Both refund approaches failed. Credit Note: {credit_note_result['message']}, Payment Entry: {payment_entry_result.get('message', 'Unknown error')}",
                        "refund_id": refund_id,
                        "payment_id": payment_id,
                        "credit_note_error": credit_note_result["message"],
                        "payment_entry_error": payment_entry_result.get("message", "Unknown error"),
                    }
            else:
                self.performance_monitor.record_failure(operation_start, "refund_webhook_processing")
                return credit_note_result

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

            # Handle both dict and object formats for refund data
            if isinstance(refund, dict):
                refund_id = refund.get("id")
                amount_value = refund.get("amount", {}).get("value", "0")
                amount_currency = refund.get("amount", {}).get("currency", "EUR")
                status = refund.get("status")
                description = refund.get("description", "")
                created_at = refund.get("created_at")
            else:
                refund_id = refund.id
                amount_value = refund.amount.value if hasattr(refund, "amount") else "0"
                amount_currency = refund.amount.currency if hasattr(refund, "amount") else "EUR"
                status = refund.status
                description = refund.description
                created_at = refund.created_at.isoformat() if refund.created_at else None

            return {
                "id": refund_id,
                "amount": {"value": amount_value, "currency": amount_currency},
                "status": status,
                "description": description,
                "created_at": created_at,
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
                ["name", "paid_amount", "paid_from", "paid_to", "company", "party_type", "party"],
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

    def _create_refund_credit_note(
        self, refund_details: Dict[str, Any], donation_doc, refund_amount: float
    ) -> Dict[str, Any]:
        """Create Credit Note for refund using ERPNext standard approach."""
        try:
            # Get the original Sales Invoice from the donation
            original_invoice_name = donation_doc.get("sales_invoice")
            if not original_invoice_name:
                return {"status": "error", "message": "No Sales Invoice linked to donation"}

            # Create Credit Note using ERPNext's make_return_doc function
            from erpnext.controllers.sales_and_purchase_return import make_return_doc

            self.logger.info(
                f"Creating credit note from invoice {original_invoice_name}",
                extra={"donation": donation_doc.name, "invoice": original_invoice_name},
            )

            credit_note = make_return_doc("Sales Invoice", original_invoice_name)

            # Fix the "Party is mandatory" error by ensuring customer is properly set
            if not getattr(credit_note, "customer", None):
                # Get the customer from the original sales invoice
                original_invoice = frappe.get_doc("Sales Invoice", original_invoice_name)
                credit_note.customer = original_invoice.customer
                self.logger.info(f"Fixed missing customer field: set to {original_invoice.customer}")

            # Ensure other required fields are properly set
            if not getattr(credit_note, "company", None):
                original_invoice = frappe.get_doc("Sales Invoice", original_invoice_name)
                credit_note.company = original_invoice.company
                self.logger.info(f"Fixed missing company field: set to {original_invoice.company}")

            # Log credit note details after fixing
            self.logger.info(
                f"Credit note prepared with customer: {getattr(credit_note, 'customer', 'NOT SET')}",
                extra={
                    "credit_note_customer": getattr(credit_note, "customer", None),
                    "credit_note_company": getattr(credit_note, "company", None),
                    "items_count": len(credit_note.items) if hasattr(credit_note, "items") else 0,
                    "docstatus": getattr(credit_note, "docstatus", None),
                },
            )

            # Adjust the credit note for partial refund amount
            if credit_note.items:
                original_item = credit_note.items[0]
                original_rate = flt(original_item.rate)
                original_qty = flt(original_item.qty)
                original_amount = original_rate * abs(original_qty)  # abs() because return qty is negative

                # Calculate proportional quantity for partial refund
                if original_amount > 0:
                    refund_proportion = refund_amount / original_amount
                    adjusted_qty = -abs(original_qty) * refund_proportion  # Negative for credit note
                    credit_note.items[0].qty = adjusted_qty
                else:
                    # Fallback: set qty to achieve the refund amount
                    if original_rate > 0:
                        credit_note.items[0].qty = -refund_amount / original_rate

            # Add reference information
            credit_note.remarks = f"Credit note for Mollie refund {refund_details.get('id', 'N/A')}. Original donation: {donation_doc.name}"

            # Set additional refund details if available
            if refund_details.get("description"):
                credit_note.remarks += f". Description: {refund_details.get('description')}"

            # Log details before insert/submit
            self.logger.info(
                f"About to insert credit note with customer: {getattr(credit_note, 'customer', 'NOT SET')}",
                extra={
                    "customer": getattr(credit_note, "customer", None),
                    "company": getattr(credit_note, "company", None),
                    "remarks": getattr(credit_note, "remarks", None),
                },
            )

            # Insert and submit the Credit Note
            credit_note.insert()

            self.logger.info(f"Credit note {credit_note.name} inserted successfully")

            credit_note.submit()

            self.logger.info(f"Credit note {credit_note.name} submitted successfully")

            self.logger.info(
                "Created refund Credit Note",
                extra={
                    "credit_note": credit_note.name,
                    "refund_amount": refund_amount,
                    "donation": donation_doc.name,
                    "original_invoice": original_invoice_name,
                },
            )

            return {
                "status": "success",
                "credit_note": credit_note.name,
                "amount": refund_amount,
            }

        except Exception as e:
            # Log detailed error information for debugging
            self.logger.error(
                "Failed to create refund Credit Note",
                error=e,
                extra={
                    "donation": donation_doc.name,
                    "refund_details": refund_details,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "original_invoice": original_invoice_name
                    if "original_invoice_name" in locals()
                    else None,
                },
            )
            # Return the actual error message instead of generic one
            return {"status": "error", "message": f"{type(e).__name__}: {str(e)}"}

    def _create_refund_payment_entry(
        self, refund_details: Dict[str, Any], donation_doc, refund_amount: float, original_payment: Tuple
    ) -> Dict[str, Any]:
        """Create refund Payment Entry for donations without Sales Invoice."""
        try:
            # Extract original payment details (7-value tuple)
            (
                original_pe_name,
                original_amount,
                paid_from,
                paid_to,
                company,
                party_type,
                party,
            ) = original_payment

            # Add null safety check
            if not original_pe_name:
                return {"status": "error", "message": "Invalid original payment entry"}

            # Get required accounting details from original Payment Entry
            original_pe = frappe.get_doc("Payment Entry", original_pe_name)

            # Create refund Payment Entry with proper accounting flow
            refund_pe = frappe.new_doc("Payment Entry")
            refund_pe.payment_type = "Pay"  # Outgoing payment (refund)

            # For refunds, keep same account flow as original (not reversed)
            refund_pe.paid_from = paid_from  # Same as original (bank account)
            refund_pe.paid_to = paid_to  # Same as original (receivable account)
            refund_pe.company = company

            # Only set party if original payment was party-based AND accounts support party relationships
            should_set_party = False
            if party_type and party:
                # Check if the accounts are Receivable/Payable type (required for party relationships)
                try:
                    paid_from_type = frappe.db.get_value("Account", paid_from, "account_type")
                    paid_to_type = frappe.db.get_value("Account", paid_to, "account_type")

                    # Party relationships require at least one account to be Receivable or Payable
                    if paid_from_type in ["Receivable", "Payable"] or paid_to_type in [
                        "Receivable",
                        "Payable",
                    ]:
                        should_set_party = True
                        self.logger.info(
                            f"Setting party for refund Payment Entry: {party_type} {party}",
                            extra={"paid_from_type": paid_from_type, "paid_to_type": paid_to_type},
                        )
                    else:
                        self.logger.info(
                            f"Skipping party for refund - accounts don't support party relationships",
                            extra={"paid_from_type": paid_from_type, "paid_to_type": paid_to_type},
                        )
                except Exception as e:
                    self.logger.error(f"Error checking account types for party support: {e}")
                    should_set_party = False

            if should_set_party:
                refund_pe.party_type = party_type
                refund_pe.party = party

            refund_pe.paid_amount = refund_amount
            refund_pe.received_amount = refund_amount
            refund_pe.reference_no = refund_details.get("id", "")
            refund_pe.reference_date = frappe.utils.getdate()
            refund_pe.mode_of_payment = original_pe.mode_of_payment or "Mollie"
            refund_pe.cost_center = original_pe.cost_center

            # Set descriptive title and remarks
            refund_pe.title = f"Refund - {original_pe.title or donation_doc.name}"
            refund_pe.remarks = f"Mollie refund {refund_details.get('id', 'N/A')} for original donation {donation_doc.name}. Original Payment Entry: {original_pe_name}"

            # Add refund description if available
            if refund_details.get("description"):
                refund_pe.remarks += f". Refund reason: {refund_details.get('description')}"

            # Insert and submit the Payment Entry (let Frappe handle transactions)
            refund_pe.insert()
            refund_pe.submit()

            self.logger.info(
                "Created refund Payment Entry",
                extra={
                    "payment_entry": refund_pe.name,
                    "refund_amount": refund_amount,
                    "donation": donation_doc.name,
                    "original_payment_entry": original_pe_name,
                },
            )

            return {
                "status": "success",
                "payment_entry": refund_pe.name,
                "amount": refund_amount,
            }

        except Exception as e:
            self.logger.error(
                "Error creating refund Payment Entry",
                extra={"donation": donation_doc.name, "refund_details": refund_details, "error": str(e)},
            )
            return {"status": "error", "message": f"Failed to create refund Payment Entry: {str(e)}"}

    def _create_chargeback_payment_entry(
        self, chargeback_details: Dict[str, Any], original_payment: Tuple, donation_name: str
    ) -> Dict[str, Any]:
        """Create reverse Payment Entry for chargeback."""
        try:
            # Extract original payment details
            original_name, original_amount, paid_from, paid_to, company, party_type, party = original_payment
            chargeback_amount = flt(chargeback_details.get("amount", {}).get("value", 0))
            chargeback_reason = chargeback_details.get("reason", {})
            reason_text = f"{chargeback_reason.get('code', 'unknown')} - {chargeback_reason.get('description', 'No description')}"

            # Create reverse Payment Entry (Pay type to reverse the Receive)
            # For chargebacks, we don't need party relationships - it's a simple account transfer
            payment_entry_doc = frappe.get_doc(
                {
                    "doctype": "Payment Entry",
                    "payment_type": "Pay",
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
        self, donation_name: str, refund_details: Dict[str, Any], credit_note_id: str
    ) -> None:
        """Update donation payment history with refund information."""
        try:
            donation = frappe.get_doc("Donation", donation_name)

            # Add refund to payment history
            refund_amount = flt(refund_details.get("amount", {}).get("value", 0))

            donation.append(
                "payments",
                {
                    "payment_date": (
                        getdate(refund_details.get("created_at"))
                        if refund_details.get("created_at")
                        else getdate()
                    ),
                    "payment_method": "Mollie",
                    "payment_status": "Refunded",
                    "amount": -(refund_amount or 0),  # Negative amount for refund
                    "mollie_payment_id": refund_details.get("id"),
                    "payment_reference": f"Credit Note {credit_note_id}: {refund_details.get('description', 'N/A')}",
                },
            )

            donation.save()

        except Exception as e:
            self.logger.error("Error updating donation refund history", error=e)

    def _update_donation_refund_history_payment_entry(
        self, donation_name: str, refund_details: Dict[str, Any], payment_entry_id: str
    ) -> None:
        """Update donation payment history with Payment Entry refund information."""
        try:
            donation = frappe.get_doc("Donation", donation_name)
            # Add refund to payment history
            refund_amount = flt(refund_details.get("amount", {}).get("value", 0))
            donation.append(
                "payments",
                {
                    "payment_date": (
                        getdate(refund_details.get("created_at"))
                        if refund_details.get("created_at")
                        else getdate()
                    ),
                    "payment_method": "Mollie",
                    "payment_status": "Refunded",
                    "amount": -(refund_amount or 0),  # Negative amount for refund
                    "mollie_payment_id": refund_details.get("id"),
                    "payment_reference": f"Refund Payment Entry {payment_entry_id}: {refund_details.get('description', 'N/A')}",
                },
            )
            donation.save()
        except Exception as e:
            self.logger.error("Error updating donation refund history with payment entry", error=e)

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
                "payments",
                {
                    "payment_date": (
                        getdate(chargeback_details.get("created_at"))
                        if chargeback_details.get("created_at")
                        else getdate()
                    ),
                    "payment_method": "Mollie",
                    "payment_status": "Failed",  # Use "Failed" for chargebacks as "Chargeback" not in options
                    "amount": -(chargeback_amount or 0),  # Negative amount for chargeback
                    "payment_entry": payment_entry_id,
                    "mollie_payment_id": chargeback_details.get("id"),
                    "payment_reference": f"Chargeback: {reason_text}",
                },
            )

            donation.save()

        except Exception as e:
            self.logger.error("Error updating donation chargeback history", error=e)
