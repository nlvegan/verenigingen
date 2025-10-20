"""
Mollie Membership Dues Payment Processor

Handles processing of Mollie payments for membership dues, including:
- Identifying dues payments vs donations by subscription_id
- Creating Payment Entries for historical dues payments
- Linking payments to members via customer_id
- Proper idempotency to prevent duplicate processing
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import flt, getdate

from verenigingen.integrations.mollie.core.mollie_client import MollieClient
from verenigingen.integrations.mollie.domain.payment_classification import PaymentClassifier
from verenigingen.verenigingen_payments.services.payment.payment_entry_creation_service import (
    payment_entry_service,
)


class DuesPaymentProcessor:
    """Process Mollie payments for membership dues"""

    def __init__(self):
        self.mollie_client = MollieClient()
        self.classifier = PaymentClassifier()

    def identify_payment_type(self, payment: Any) -> str:
        """
        Identify whether a payment is for membership dues or a donation.

        Uses the PaymentClassifier strategy pattern for classification with audit trail.

        Args:
            payment: Mollie payment object

        Returns:
            str: "dues", "donation", or "unknown"
        """
        result = self.classifier.classify(payment)
        return result.payment_type

    def find_member_for_payment(self, payment) -> Optional[str]:
        """
        Find the Member record associated with a Mollie payment.

        Args:
            payment: Mollie payment object

        Returns:
            str: Member name if found, None otherwise
        """
        customer_id = getattr(payment, "customer_id", None)
        subscription_id = getattr(payment, "subscription_id", None)
        description = getattr(payment, "description", "")

        # Method 1: Direct subscription_id match
        if subscription_id:
            member_name = frappe.db.get_value("Member", {"mollie_subscription_id": subscription_id}, "name")
            if member_name:
                frappe.logger().info(f"✅ Found member {member_name} by subscription_id")
                return member_name

        # Method 2: Customer ID match
        if customer_id:
            member_name = frappe.db.get_value("Member", {"mollie_customer_id": customer_id}, "name")
            if member_name:
                frappe.logger().info(f"✅ Found member {member_name} by customer_id")
                return member_name

        # Method 3: Parse member ID from description
        if description and isinstance(description, str):
            # Try to extract member ID pattern (e.g., "Assoc-Member-2024-01-0001")
            import re

            member_id_pattern = r"Assoc-Member-\d{4}-\d{2}-\d{4}"
            match = re.search(member_id_pattern, description)
            if match:
                potential_member_id = match.group(0)
                if frappe.db.exists("Member", potential_member_id):
                    frappe.logger().info(f"✅ Found member {potential_member_id} by parsing description")
                    return potential_member_id

        frappe.logger().warning(f"⚠️ No member found for payment {payment.id}")
        return None

    def check_payment_already_processed(self, payment_id: str) -> Dict[str, Any]:
        """
        Check if a payment has already been processed (robust idempotency check).

        Checks for BOTH Payment Entry and Bank Transaction with this reference
        to prevent duplicate processing regardless of creation mode.

        Args:
            payment_id: Mollie payment ID (e.g., "tr_xxxxxxxxx")

        Returns:
            dict: {
                "already_processed": bool,
                "payment_entry": str or None,
                "bank_transaction": str or None,
                "docstatus": int or None (0=Draft, 1=Submitted, 2=Cancelled),
                "details": str
            }
        """
        # Check for ANY Payment Entry with this reference_no (draft, submitted, cancelled)
        existing_entries = frappe.db.get_all(
            "Payment Entry", filters={"reference_no": payment_id}, fields=["name", "docstatus"], limit=1
        )

        if existing_entries:
            existing = existing_entries[0]
            status_map = {0: "Draft", 1: "Submitted", 2: "Cancelled"}
            status_text = status_map.get(existing.docstatus, "Unknown")

            # If cancelled, allow reprocessing (treat as not processed)
            if existing.docstatus == 2:
                frappe.logger().info(
                    f"Found cancelled Payment Entry {existing.name} for payment {payment_id}. "
                    f"Allowing reprocessing."
                )
                # Don't return yet - still check for Bank Transaction below
            else:
                # Draft or Submitted - consider as already processed
                return {
                    "already_processed": True,
                    "payment_entry": existing.name,
                    "bank_transaction": None,
                    "docstatus": existing.docstatus,
                    "details": f"Payment Entry {existing.name} already exists ({status_text})",
                }

        # Check for ANY Bank Transaction with this reference_number
        existing_bt = frappe.db.get_all(
            "Bank Transaction",
            filters={"reference_number": payment_id},
            fields=["name", "docstatus"],
            limit=1,
        )

        if existing_bt:
            bt = existing_bt[0]
            status_map = {0: "Draft", 1: "Submitted", 2: "Cancelled"}
            status_text = status_map.get(bt.docstatus, "Unknown")

            # Allow reprocessing if cancelled
            if bt.docstatus == 2:
                frappe.logger().info(
                    f"Found cancelled Bank Transaction {bt.name} for payment {payment_id}. "
                    f"Allowing reprocessing."
                )
                # Fall through to return "not processed" at end
            else:
                # Draft or Submitted - already processed
                frappe.logger().info(
                    f"Found existing Bank Transaction {bt.name} for payment {payment_id} ({status_text})"
                )
                return {
                    "already_processed": True,
                    "payment_entry": None,
                    "bank_transaction": bt.name,
                    "docstatus": bt.docstatus,
                    "details": f"Bank Transaction {bt.name} already exists ({status_text})",
                }

        # Nothing found - payment not yet processed
        return {
            "already_processed": False,
            "payment_entry": None,
            "bank_transaction": None,
            "docstatus": None,
            "details": "Payment not yet processed",
        }

    def process_dues_payment(self, payment_id: str, payment=None) -> Dict[str, Any]:
        """
        Process a membership dues payment from Mollie.

        Creates a Payment Entry for the member's dues payment.
        Uses proper idempotency checks to prevent duplicate processing.

        Args:
            payment_id: Mollie payment ID
            payment: Optional Mollie payment object (if already fetched)

        Returns:
            dict: Processing result with status, payment_entry, member, etc.
        """
        result = {
            "payment_id": payment_id,
            "status": "pending",
            "payment_type": "unknown",
            "member": None,
            "payment_entry": None,
            "bank_transaction": None,
            "error": None,
            "skipped_reason": None,
        }

        try:
            # Fetch payment from Mollie if not provided
            if not payment:
                payment = self.mollie_client.sdk_client.payments.get(payment_id)

            result["payment_status"] = payment.status
            result["amount"] = (
                f"{payment.amount['value']} {payment.amount['currency']}" if payment.amount else "Unknown"
            )

            # Only process paid payments
            if payment.status != "paid":
                result["status"] = "skipped"
                result["skipped_reason"] = f"Payment status is '{payment.status}', not 'paid'"
                return result

            # Check idempotency
            idempotency_check = self.check_payment_already_processed(payment_id)
            if idempotency_check["already_processed"]:
                result["status"] = "already_processed"
                result["payment_entry"] = idempotency_check["payment_entry"]
                result["bank_transaction"] = idempotency_check["bank_transaction"]
                result["skipped_reason"] = idempotency_check["details"]
                return result

            # Identify payment type
            payment_type = self.identify_payment_type(payment)
            result["payment_type"] = payment_type

            if payment_type != "dues":
                result["status"] = "skipped"
                result["skipped_reason"] = f"Payment type is '{payment_type}', not membership dues"
                return result

            # Find associated member
            member_name = self.find_member_for_payment(payment)
            if not member_name:
                result["status"] = "error"
                result["error"] = "No member found for this payment"
                return result

            result["member"] = member_name

            # Check payment creation mode from settings
            mollie_settings = frappe.get_single("Mollie Settings")
            creation_mode = getattr(mollie_settings, "dues_payment_creation_mode", "Bank Transaction")

            if creation_mode == "Payment Entry":
                # Legacy mode: Create Payment Entry directly
                record_name = self._create_payment_entry_for_dues(member_name, payment)
                record_type = "Payment Entry"
            else:
                # Default mode: Create Bank Transaction for reconciliation
                record_name = self._create_bank_transaction_for_dues(member_name, payment)
                record_type = "Bank Transaction"

            if record_name:
                result["status"] = "success"
                # Set BOTH fields for frontend compatibility, only one will have value
                result["payment_entry"] = record_name if creation_mode == "Payment Entry" else None
                result["bank_transaction"] = record_name if creation_mode != "Payment Entry" else None
                result["record_type"] = record_type
                frappe.logger().info(
                    f"✅ Successfully processed dues payment {payment_id} for member {member_name} "
                    f"(created {record_type}: {record_name})"
                )
            else:
                result["status"] = "error"
                result["error"] = f"Failed to create {record_type}"

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            frappe.log_error(
                f"Error processing dues payment {payment_id}: {e}", "Dues Payment Processing Error"
            )

        return result

    def _create_payment_entry_for_dues(self, member_name: str, payment) -> Optional[str]:
        """
        Create a Payment Entry for a membership dues payment from Mollie.

        Creates an unallocated payment entry - reconciliation with Sales Invoices
        happens separately (either automatically via payment hooks or manually).

        Args:
            member_name: Member document name
            payment: Mollie payment object

        Returns:
            str: Payment Entry name if created, None otherwise
        """
        # Get member and customer
        member = frappe.get_doc("Member", member_name)
        customer = member.customer

        if not customer:
            frappe.throw(f"Member {member_name} has no linked Customer record")

        # Extract payment data from Mollie
        payment_id = payment.id
        amount = float(payment.amount["value"]) if payment.amount else 0.0
        currency = payment.amount["currency"] if payment.amount else "EUR"
        paid_at = getattr(payment, "paid_at", None)
        payment_date = getdate(paid_at) if paid_at else getdate()

        # Get settings and accounts
        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        mollie_settings = frappe.get_single("Mollie Settings")
        company = verenigingen_settings.donation_company or frappe.defaults.get_global_default("company")
        mode_of_payment = getattr(verenigingen_settings, "mode_of_payment", None) or "Mollie"

        # Get Mollie clearing account (where money sits until settlement)
        mollie_clearing_account = getattr(mollie_settings, "mollie_clearing_account", None)
        if not mollie_clearing_account:
            frappe.throw(
                "Mollie Clearing Account not configured. "
                "Please set it in Mollie Settings to track payments awaiting settlement."
            )

        # Get customer receivable account (customer's outstanding balance)
        # Use dues-specific receivable account from settings, fallback to company default
        customer_account = getattr(verenigingen_settings, "dues_payments_receivable_account", None)
        if not customer_account:
            customer_account = frappe.get_cached_value("Company", company, "default_receivable_account")

        if not customer_account:
            frappe.throw(f"Missing customer receivable account for company {company}")

        # Create Payment Entry FIRST (separate concern from invoice matching)
        # Payment Entry creation should always succeed even if we can't match an invoice
        payment_entry = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": customer,
                "company": company,
                "paid_from": customer_account,
                "paid_to": mollie_clearing_account,  # Use clearing account, not bank account
                "paid_amount": amount,
                "received_amount": amount,
                "reference_no": payment_id,
                "reference_date": payment_date,
                "posting_date": payment_date,
                "mode_of_payment": mode_of_payment,
                "remarks": f"Membership dues payment via Mollie for {member.full_name} (awaiting settlement). "
                f"Manual reconciliation may be required.",
                "custom_member": member_name,  # Link to member for payment history tracking
            }
        )

        payment_entry.insert()
        payment_entry.submit()

        frappe.logger().info(
            f"✅ Created Payment Entry {payment_entry.name} for member {member_name} "
            f"(amount: {currency} {amount}, payment: {payment_id})"
        )

        return payment_entry.name

    def _create_bank_transaction_for_dues(self, member_name: str, payment) -> Optional[str]:
        """
        Create a Bank Transaction for a membership dues payment from Mollie.

        This creates an unreconciled bank transaction that can later be matched
        to Sales Invoices via the Bank Reconciliation Tool.

        Args:
            member_name: Member document name
            payment: Mollie payment object

        Returns:
            str: Bank Transaction name if created, None otherwise
        """
        # Get member and customer
        member = frappe.get_doc("Member", member_name)
        customer = member.customer

        if not customer:
            frappe.throw(f"Member {member_name} has no linked Customer record")

        # Extract payment data from Mollie
        payment_id = payment.id
        amount = float(payment.amount["value"]) if payment.amount else 0.0
        currency = payment.amount["currency"] if payment.amount else "EUR"
        paid_at = getattr(payment, "paid_at", None)
        payment_date = getdate(paid_at) if paid_at else getdate()

        # Get settings and accounts
        mollie_settings = frappe.get_single("Mollie Settings")
        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        company = verenigingen_settings.donation_company or frappe.defaults.get_global_default("company")

        # Get Mollie clearing account (where money sits until settlement)
        mollie_clearing_account = getattr(mollie_settings, "mollie_clearing_account", None)
        if not mollie_clearing_account:
            frappe.throw(
                "Mollie Clearing Account not configured. "
                "Please set it in Mollie Settings to track payments awaiting settlement."
            )

        # Get Bank Account linked to the clearing account
        bank_account = frappe.db.get_value("Bank Account", {"account": mollie_clearing_account}, "name")
        if not bank_account:
            frappe.throw(
                f"No Bank Account found linked to clearing account {mollie_clearing_account}. "
                f"Please create a Bank Account record and link it to this GL Account."
            )

        # Create unreconciled Bank Transaction
        bank_transaction = frappe.get_doc(
            {
                "doctype": "Bank Transaction",
                "date": payment_date,
                "deposit": amount,
                "withdrawal": 0.0,
                "currency": currency,
                "bank_account": bank_account,
                "company": company,
                "reference_number": payment_id,
                "description": f"Mollie dues payment for {member.full_name} (Member: {member_name})",
                "party_type": "Customer",
                "party": customer,
                "status": "Unreconciled",
                "unallocated_amount": amount,
            }
        )

        bank_transaction.insert()
        bank_transaction.submit()

        frappe.logger().info(
            f"✅ Created Bank Transaction {bank_transaction.name} for member {member_name} "
            f"(amount: {currency} {amount}, payment: {payment_id}, status: Unreconciled)"
        )

        return bank_transaction.name

    def _create_payment_entry_for_dues_OLD_CUSTOM_IMPLEMENTATION(
        self, member_name: str, payment
    ) -> Optional[str]:
        """
        Create a Payment Entry for a membership dues payment.

        Args:
            member_name: Member document name
            payment: Mollie payment object

        Returns:
            str: Payment Entry name if created, None otherwise

        Raises:
            frappe.ValidationError: If member has no customer or required accounts missing
        """
        try:
            # Get member and customer
            member = frappe.get_doc("Member", member_name)
            customer = member.customer

            if not customer:
                error_msg = f"Member {member_name} has no linked Customer record - data integrity issue"
                frappe.log_error(error_msg, "Member Data Integrity Error")
                raise frappe.ValidationError(error_msg)

            # Get company
            settings = frappe.get_single("Verenigingen Settings")
            company = settings.donation_company or frappe.defaults.get_global_default("company")

            # Extract payment data
            payment_id = payment.id
            amount = float(payment.amount["value"]) if payment.amount else 0.0
            currency = payment.amount["currency"] if payment.amount else "EUR"
            paid_at = getattr(payment, "paid_at", None)
            payment_date = getdate(paid_at) if paid_at else getdate()

            # Validate currency matches company
            company_currency = frappe.get_cached_value("Company", company, "default_currency")
            if currency != company_currency:
                frappe.logger().warning(
                    f"Currency mismatch: Payment {payment_id} is in {currency} "
                    f"but company {company} uses {company_currency}"
                )
                # For now, log warning but continue - could add currency conversion later

            # Get required accounts
            # 1. Bank/Cash account (paid_to) - where money is received
            mollie_bank_account = getattr(settings, "mollie_bank_account", None) or frappe.db.get_value(
                "Company", company, "default_bank_account"
            )

            if not mollie_bank_account:
                raise frappe.ValidationError(
                    f"No Mollie bank account configured. Please set 'mollie_bank_account' in Verenigingen Settings "
                    f"or configure default_bank_account for company {company}"
                )

            # 2. Find unpaid Sales Invoice FIRST to determine correct receivable account
            # IMPORTANT: Match currency to prevent accounting errors
            # Also fetch debit_to to use the invoice's receivable account
            unpaid_invoice = frappe.db.get_value(
                "Sales Invoice",
                {
                    "customer": customer,
                    "docstatus": 1,
                    "currency": currency,  # Match payment currency
                    "status": ["in", ["Unpaid", "Overdue", "Partly Paid"]],
                    "outstanding_amount": [">", 0],
                },
                ["name", "outstanding_amount", "currency", "debit_to"],
                order_by="posting_date asc",
                as_dict=True,
            )

            # 3. Customer receivable account (paid_from) - customer's outstanding balance
            # Prefer invoice's debit_to account to prevent account mismatch errors
            if unpaid_invoice and unpaid_invoice.debit_to:
                customer_account = unpaid_invoice.debit_to
                frappe.logger().info(
                    f"Using Sales Invoice's receivable account: {customer_account} "
                    f"(from invoice {unpaid_invoice.name})"
                )
            else:
                # Fallback to customer's default account
                customer_account = frappe.db.get_value(
                    "Party Account", {"parent": customer, "company": company}, "account"
                )

                if not customer_account:
                    # Fallback to company default
                    customer_account = frappe.get_cached_value(
                        "Company", company, "default_receivable_account"
                    )

                if not customer_account:
                    raise frappe.ValidationError(
                        f"No receivable account found for customer {customer}. "
                        f"Please configure Party Account or company default_receivable_account"
                    )

            # 4. Mode of Payment
            mode_of_payment = getattr(settings, "mode_of_payment", None) or "Mollie"

            # Verify mode of payment exists
            if not frappe.db.exists("Mode of Payment", mode_of_payment):
                frappe.logger().warning(
                    f"Mode of Payment '{mode_of_payment}' not found, creating Payment Entry without it"
                )
                mode_of_payment = None

            # Store comprehensive Mollie metadata for audit trail and compliance
            payment_metadata = {
                "mollie_payment_id": payment_id,
                "mollie_created_at": str(payment.created_at),
                "mollie_paid_at": str(paid_at) if paid_at else None,
                "mollie_authorized_at": str(getattr(payment, "authorized_at", None))
                if getattr(payment, "authorized_at", None)
                else None,
                "mollie_method": getattr(payment, "method", None),
                "mollie_status": getattr(payment, "status", None),  # Payment status (paid, failed, etc.)
                "mollie_sequence_type": getattr(
                    payment, "sequence_type", None
                ),  # 'first', 'recurring', 'oneoff'
                "mollie_settlement_id": getattr(payment, "settlement_id", None),
                "mollie_subscription_id": getattr(payment, "subscription_id", None),
                "mollie_customer_id": getattr(payment, "customer_id", None),
                "mollie_mandate_id": getattr(payment, "mandate_id", None),
                "mollie_profile_id": getattr(
                    payment, "profile_id", None
                ),  # Critical for multi-profile setups
                "mollie_description": getattr(payment, "description", None),
                "payment_amount_value": str(getattr(payment.amount, "value", None))
                if hasattr(payment, "amount")
                else None,
                "payment_amount_currency": str(getattr(payment.amount, "currency", None))
                if hasattr(payment, "amount")
                else None,
                "mollie_webhook_url": getattr(payment, "webhook_url", None),
                "mollie_redirect_url": getattr(payment, "redirect_url", None),
                "mollie_metadata": getattr(payment, "metadata", None),  # Custom metadata if present
                "processed_by": "batch_processor",
                "processed_at": frappe.utils.now(),
                "processor_user": frappe.session.user,
            }

            # Add SEPA-specific details if direct debit
            if getattr(payment, "method", None) == "directdebit" and hasattr(payment, "details"):
                details = payment.details
                # Handle both dict and object-style access
                if isinstance(details, dict):
                    payment_metadata["mollie_consumer_account"] = details.get(
                        "consumerAccount"
                    )  # IBAN last 4 digits
                    payment_metadata["mollie_consumer_name"] = details.get("consumerName")
                    payment_metadata["mollie_consumer_bic"] = details.get("consumerBic")
                else:
                    # Mollie SDK uses object-style access
                    payment_metadata["mollie_consumer_account"] = getattr(details, "consumerAccount", None)
                    payment_metadata["mollie_consumer_name"] = getattr(details, "consumerName", None)
                    payment_metadata["mollie_consumer_bic"] = getattr(details, "consumerBic", None)

            # Create Payment Entry
            payment_entry = frappe.get_doc(
                {
                    "doctype": "Payment Entry",
                    "payment_type": "Receive",
                    "party_type": "Customer",
                    "party": customer,
                    "company": company,
                    "paid_from": customer_account,
                    "paid_to": mollie_bank_account,
                    "paid_amount": amount,
                    "received_amount": amount,
                    "reference_no": payment_id,
                    "reference_date": payment_date,
                    "posting_date": payment_date,
                    "remarks": f"Membership dues payment for {member.full_name} via Mollie (subscription payment)",
                }
            )

            # Add mode of payment if available
            if mode_of_payment:
                payment_entry.mode_of_payment = mode_of_payment

            # Store metadata in user_remark field (standard ERPNext field for additional info)
            # We use JSON format for structured storage
            payment_entry.user_remark = frappe.as_json(payment_metadata, indent=2)

            # Link to Sales Invoice if found
            if unpaid_invoice:
                allocated_amount = min(amount, unpaid_invoice.outstanding_amount)
                payment_entry.append(
                    "references",
                    {
                        "reference_doctype": "Sales Invoice",
                        "reference_name": unpaid_invoice.name,
                        "allocated_amount": allocated_amount,
                    },
                )
                frappe.logger().info(
                    f"✅ Linked payment to Sales Invoice {unpaid_invoice.name} "
                    f"(allocated: {allocated_amount} of {unpaid_invoice.outstanding_amount})"
                )
            else:
                frappe.logger().warning(
                    f"⚠️ No unpaid Sales Invoice found for customer {customer}. "
                    f"Payment Entry created as unallocated payment."
                )

            # Insert and submit
            payment_entry.insert()
            payment_entry.submit()

            # DO NOT manually commit - let Frappe handle transaction management
            # frappe.db.commit()  # REMOVED - violates framework transaction pattern

            frappe.logger().info(f"✅ Created Payment Entry {payment_entry.name} for member {member_name}")
            return payment_entry.name

        except frappe.ValidationError:
            # Re-raise validation errors (expected errors)
            raise
        except Exception as e:
            frappe.log_error(
                f"Error creating payment entry for member {member_name}: {e}",
                "Dues Payment Entry Creation Error",
            )
            raise

    def batch_process_customer_payments(
        self, customer_id: str, limit: int = 250, only_unpaid: bool = False
    ) -> Dict[str, Any]:
        """
        Retrieve and process all payments for a Mollie customer.

        This is the main method for batch processing historical dues payments.

        Args:
            customer_id: Mollie customer ID
            limit: Maximum number of payments to retrieve
            only_unpaid: If True, only process payments not yet in Payment Entry

        Returns:
            dict: {
                "customer_id": str,
                "total_retrieved": int,
                "processed": int,
                "skipped": int,
                "errors": int,
                "results": List[dict]
            }
        """
        # Enforce maximum limit to prevent memory exhaustion
        MAX_LIMIT = 250
        if limit > MAX_LIMIT:
            raise ValueError(
                f"Limit cannot exceed {MAX_LIMIT}. "
                f"Requested: {limit}. Please use smaller batches to prevent memory issues."
            )

        batch_result = {
            "customer_id": customer_id,
            "total_retrieved": 0,
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "results": [],
        }

        try:
            # Retrieve all payments for customer
            customer_obj = self.mollie_client.sdk_client.customers.get(customer_id)
            payments = customer_obj.payments.list(limit=limit)

            batch_result["total_retrieved"] = len(payments)

            for payment in payments:
                # Process each payment
                result = self.process_dues_payment(payment.id, payment)

                batch_result["results"].append(result)

                if result["status"] == "success":
                    batch_result["processed"] += 1
                elif result["status"] == "skipped" or result["status"] == "already_processed":
                    batch_result["skipped"] += 1
                elif result["status"] == "error":
                    batch_result["errors"] += 1

            frappe.logger().info(
                f"✅ Batch processing complete for customer {customer_id}: "
                f"{batch_result['processed']} processed, {batch_result['skipped']} skipped, {batch_result['errors']} errors"
            )

        except Exception as e:
            batch_result["error"] = str(e)
            frappe.log_error(f"Error batch processing payments for customer {customer_id}: {e}")

        return batch_result
