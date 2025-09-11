"""
Payment Processing Service

Handles payment-related operations for webhook processing.
Extracted from monolithic webhook handler for better maintainability.
"""

from typing import Any, Dict, Optional, Tuple

import frappe
from frappe.utils import flt

from verenigingen.api.refund_processor import (
    detect_chargeback_in_payment,
    detect_refund_in_payment,
    process_payment_chargeback,
    process_payment_refund,
)
from verenigingen.utils.validation_utilities import DocumentExistenceValidator


class PaymentProcessingService:
    """Service class for handling payment processing operations"""

    def __init__(self, debug_context: str = "webhook"):
        self.debug_context = debug_context
        self.logger = frappe.logger()

    def process_payment_webhook(self, payment_id: str, payment_data: Any) -> Dict[str, Any]:
        """
        Process a payment webhook with comprehensive validation

        Args:
            payment_id: Mollie payment ID
            payment_data: Mollie payment object

        Returns:
            Processing result dict with status and details
        """
        try:
            # Check for refunds first (can happen on any payment status)
            has_refund, refund_amount = detect_refund_in_payment(payment_data)
            if has_refund:
                self.logger.info(
                    f"🔄 [{self.debug_context}] Refund detected: €{refund_amount} for payment {payment_id}"
                )
                return process_payment_refund(payment_id, refund_amount, self.debug_context)

            # Check for chargebacks (can happen on any payment status)
            has_chargeback, chargeback_amount = detect_chargeback_in_payment(payment_data)
            if has_chargeback:
                self.logger.info(
                    f"⚠️ [{self.debug_context}] Chargeback detected: €{chargeback_amount} for payment {payment_id}"
                )
                return process_payment_chargeback(payment_id, chargeback_amount, self.debug_context)

            # Only process paid payments for donation creation
            if payment_data.status != "paid":
                return {"status": "ignored", "message": f"Payment not paid (status: {payment_data.status})"}

            return {"status": "ready_for_donation_processing", "message": "Payment validated and ready"}

        except Exception as e:
            error_msg = f"Payment processing failed for {payment_id}: {str(e)}"
            frappe.log_error(error_msg, f"Payment Processing Error [{self.debug_context}]")
            self.logger.error(f"❌ [{self.debug_context}] {error_msg}")
            return {"status": "error", "message": error_msg}

    def extract_mollie_ids(self, payment_data: Any) -> Dict[str, Optional[str]]:
        """
        Extract Mollie IDs (customer, mandate, subscription) from payment data

        Args:
            payment_data: Mollie payment object

        Returns:
            Dict with extracted IDs
        """
        mandate_id = None
        customer_id = None
        subscription_id = None

        # Debug logging to understand payment object structure
        self.logger.info(f"🔍 [{self.debug_context}] Debug payment object type: {type(payment_data)}")
        self.logger.info(f"🔍 [{self.debug_context}] Has _data: {hasattr(payment_data, '_data')}")
        self.logger.info(f"🔍 [{self.debug_context}] Has customer_id: {hasattr(payment_data, 'customer_id')}")

        # Try extracting from _data attribute (primary method)
        if hasattr(payment_data, "_data") and isinstance(payment_data._data, dict):
            self.logger.info(f"🔍 [{self.debug_context}] _data keys: {list(payment_data._data.keys())}")
            mandate_id = payment_data._data.get("mandateId")
            customer_id = payment_data._data.get("customerId")
            subscription_id = payment_data._data.get("subscriptionId")
            self.logger.info(
                f"🔍 [{self.debug_context}] From _data: customer={customer_id}, mandate={mandate_id}, subscription={subscription_id}"
            )

        # Try direct property access for customer ID
        if not customer_id and hasattr(payment_data, "customer_id"):
            customer_id = payment_data.customer_id
            self.logger.info(f"🔍 [{self.debug_context}] From direct property: customer_id={customer_id}")

        # Try alternative property names
        if not customer_id and hasattr(payment_data, "customerId"):
            customer_id = payment_data.customerId
            self.logger.info(f"🔍 [{self.debug_context}] From customerId property: {customer_id}")

        if not subscription_id and hasattr(payment_data, "subscription_id"):
            subscription_id = payment_data.subscription_id

        # Debug what we extracted
        self.logger.info(
            f"🔍 [{self.debug_context}] Final extracted IDs - Customer: {customer_id}, Mandate: {mandate_id}, Subscription: {subscription_id}"
        )

        return {"customer_id": customer_id, "mandate_id": mandate_id, "subscription_id": subscription_id}

    def create_payment_entry(self, donation, payment_id: str) -> Dict[str, Any]:
        """
        Create Payment Entry for a donation with proper accounting

        Args:
            donation: Donation document
            payment_id: Mollie payment ID

        Returns:
            Processing result dict
        """
        try:
            # Check if Payment Entry already exists for this payment
            existing_payment_entry = frappe.db.get_value(
                "Payment Entry", {"reference_no": payment_id, "docstatus": 1}, "name"
            )
            if existing_payment_entry:
                self.logger.info(
                    f"⚠️ [{self.debug_context}] Payment Entry {existing_payment_entry} already exists for payment {payment_id}"
                )
                return {
                    "status": "exists",
                    "message": f"Payment Entry already exists for payment {payment_id}",
                    "payment_entry": existing_payment_entry,
                }

            # Ensure customer exists for the donor
            customer_name = donation.donor
            if customer_name and not DocumentExistenceValidator.check_document_exists(
                "Customer", customer_name
            ):
                # Create customer record
                customer = frappe.new_doc("Customer")
                customer.customer_name = customer_name
                customer.customer_type = "Individual"
                customer.customer_group = (
                    frappe.db.get_single_value("Selling Settings", "customer_group") or "Individual"
                )
                customer.territory = (
                    frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"
                )
                customer.insert()
                customer_name = customer.name
                self.logger.info(f"✅ [{self.debug_context}] Created customer {customer_name} for donor")

            payment_entry = frappe.new_doc("Payment Entry")
            payment_entry.payment_type = "Receive"
            payment_entry.company = donation.company

            # Set customer as party
            if customer_name:
                payment_entry.party_type = "Customer"
                payment_entry.party = customer_name

            payment_entry.paid_amount = donation.amount
            payment_entry.received_amount = donation.amount
            payment_entry.reference_no = payment_id
            payment_entry.reference_date = frappe.utils.nowdate()

            # Get accounts from Verenigingen Settings
            verenigingen_settings = frappe.get_single("Verenigingen Settings")
            cash_account = frappe.get_value("Company", donation.company, "default_cash_account")
            receivable_account = verenigingen_settings.get("default_receivable_account")

            if not cash_account or not receivable_account:
                error_msg = f"Missing accounts - Cash: {cash_account}, Receivable: {receivable_account}"
                self.logger.error(f"❌ [{self.debug_context}] {error_msg}")
                return {"status": "error", "message": error_msg}

            payment_entry.paid_to = cash_account
            payment_entry.paid_from = receivable_account

            payment_entry.insert()

            # Rename Payment Entry with human-readable format: "Donor Name - Donation ID"
            try:
                new_name = self._generate_payment_entry_name(donation)
                frappe.rename_doc("Payment Entry", payment_entry.name, new_name)
                payment_entry.name = new_name
                self.logger.info(f"✅ [{self.debug_context}] Renamed Payment Entry to: {new_name}")

            except Exception as e:
                self.logger.warning(
                    f"⚠️ [{self.debug_context}] Could not rename Payment Entry {payment_entry.name}: {str(e)}"
                )

            payment_entry.submit()

            self.logger.info(
                f"✅ [{self.debug_context}] Payment Entry {payment_entry.name} created successfully"
            )

            return {
                "status": "success",
                "message": f"Payment Entry {payment_entry.name} created successfully",
                "payment_entry": payment_entry.name,
            }

        except Exception as e:
            error_msg = f"Failed to create payment entry for donation {donation.name}: {str(e)}"
            frappe.log_error(error_msg, f"Payment Entry Error [{self.debug_context}]")
            self.logger.error(f"❌ [{self.debug_context}] Payment Entry creation failed: {str(e)}")
            return {"status": "error", "message": error_msg}

    def _generate_payment_entry_name(self, donation) -> str:
        """Generate human-readable name for Payment Entry"""
        # Get donor's actual name
        donor_name = "Anonymous"
        if donation.donor:
            try:
                donor_doc = frappe.get_doc("Donor", donation.donor)
                # Use full_name if available, otherwise construct from first/last name
                if hasattr(donor_doc, "full_name") and donor_doc.full_name:
                    donor_name = donor_doc.full_name
                elif hasattr(donor_doc, "first_name") and donor_doc.first_name:
                    last_name = getattr(donor_doc, "last_name", "")
                    donor_name = f"{donor_doc.first_name} {last_name}".strip()
                elif hasattr(donor_doc, "donor_name") and donor_doc.donor_name:
                    donor_name = donor_doc.donor_name
            except Exception:
                donor_name = donation.donor  # Fall back to donor ID

        # Create human-readable name: "Donor Name - Donation ID"
        new_name = f"{donor_name} - {donation.name}"

        # Ensure uniqueness by adding counter if needed
        counter = 1
        original_new_name = new_name
        while DocumentExistenceValidator.check_document_exists("Payment Entry", new_name):
            new_name = f"{original_new_name} ({counter})"
            counter += 1

        return new_name

    def add_payment_history_entry(self, donation, payment_id: str) -> None:
        """
        Add payment history record to donation

        Args:
            donation: Donation document
            payment_id: Mollie payment ID
        """
        try:
            # Check if payment history entry already exists to prevent duplicates
            existing_entries = [
                entry
                for entry in (donation.get("payment_history") or [])
                if entry.get("mollie_payment_id") == payment_id and flt(entry.get("amount", 0)) > 0
            ]

            if existing_entries:
                self.logger.info(
                    f"⚠️ [{self.debug_context}] Payment history entry already exists for payment {payment_id}"
                )
                return

            # Add payment history record to donation
            payment_history = donation.append("payment_history", {})
            payment_history.payment_date = frappe.utils.nowdate()
            payment_history.amount = donation.amount
            payment_history.payment_method = "Mollie"
            payment_history.mollie_payment_id = payment_id
            payment_history.transaction_reference = payment_id
            payment_history.payment_status = "Completed"

            donation.save()

            self.logger.info(f"✅ [{self.debug_context}] Payment history updated for donation {donation.name}")

        except Exception as e:
            self.logger.error(f"❌ [{self.debug_context}] Failed to add payment history: {str(e)}")
            # Don't raise - payment history is non-critical
