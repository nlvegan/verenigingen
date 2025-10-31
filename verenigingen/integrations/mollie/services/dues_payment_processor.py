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

        # Use centralized Bank Transaction creator
        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            get_bank_transaction_creator,
        )

        self.bank_tx_creator = get_bank_transaction_creator()

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

    def process_dues_payment(
        self, payment_id: str, payment=None, creation_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a membership dues payment from Mollie.

        Creates a Payment Entry or Bank Transaction for the member's dues payment.
        Uses proper idempotency checks to prevent duplicate processing.

        Args:
            payment_id: Mollie payment ID
            payment: Optional Mollie payment object (if already fetched)
            creation_mode: Optional override for document creation mode.
                         "Payment Entry" to create Payment Entry directly
                         "Bank Transaction" to create Bank Transaction for reconciliation
                         None (default) to use centralized configuration

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

            # Check idempotency using centralized service
            from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
                get_bank_transaction_creator,
            )

            creator = get_bank_transaction_creator()
            idempotency_check = creator.check_already_processed(
                payment_id,
                check_payment_entry=True,  # Dual mode: check both Payment Entry and Bank Transaction
            )

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

            # Determine creation mode: use override if provided, otherwise use centralized configuration
            if creation_mode is None:
                from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
                    get_mollie_config,
                )

                mollie_config = get_mollie_config()
                creation_mode = mollie_config.get_dues_payment_creation_mode()

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

        # Get company first (needed for currency validation)
        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        company = verenigingen_settings.donation_company or frappe.defaults.get_global_default("company")

        # Extract payment data using centralized extractor
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config
        from verenigingen.verenigingen_payments.utils.payment_data_extractor import get_payment_data_extractor

        extractor = get_payment_data_extractor()
        payment_id = extractor.extract_payment_id(payment)
        amount = extractor.extract_amount(payment)
        currency = extractor.extract_currency(payment, company)
        payment_date = extractor.extract_date(payment, field_name="paid_at")
        mode_of_payment = getattr(verenigingen_settings, "mode_of_payment", None) or "Mollie"

        # Get Mollie clearing account from centralized configuration (throws if not configured)
        mollie_config = get_mollie_config()
        mollie_clearing_account = mollie_config.get_clearing_account()

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

        # Get bank account configuration using centralized helper
        config = self.bank_tx_creator.get_mollie_bank_account_config()

        if config.get("error"):
            frappe.throw(config["error"])

        bank_account = config["bank_account"]
        company = config["company"]

        # Extract payment data from Mollie
        payment_id = payment.id
        payment_description = getattr(payment, "description", None)

        # Build description with member context (start with payment description for title_field visibility)
        if payment_description:
            additional_description = f"{payment_id} | Member: {member.full_name}"
        else:
            additional_description = f"Mollie dues payment | {payment_id} | Member: {member.full_name}"

        # Use centralized PaymentDataExtractor for consistent extraction
        from verenigingen.verenigingen_payments.utils.payment_data_extractor import get_payment_data_extractor

        extractor = get_payment_data_extractor()
        payment_date = extractor.extract_date(payment, field_name="paid_at")
        amount = extractor.extract_amount(payment)
        currency = extractor.extract_currency(payment, company)

        # Build full description
        if payment_description:
            description = f"{payment_description} | {additional_description}"
        else:
            description = additional_description

        # Use centralized create() method with party fields
        bank_transaction_name = self.bank_tx_creator.create(
            date=payment_date,
            bank_account=bank_account,
            company=company,
            deposit=amount,
            withdrawal=0.0,
            currency=currency,
            reference_number=payment_id,
            transaction_id=payment_id,
            description=description,
            party_type="Customer",
            party=customer,
        )

        if bank_transaction_name:
            frappe.logger().info(
                f"✅ Created Bank Transaction {bank_transaction_name} for member {member_name} "
                f"(amount: {currency} {amount}, payment: {payment_id}, status: Unreconciled)"
            )

        return bank_transaction_name

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
