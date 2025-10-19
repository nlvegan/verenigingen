"""
Mollie Membership Dues Payment Processor

Handles processing of Mollie payments for membership dues, including:
- Identifying dues payments vs donations by subscription_id
- Creating Payment Entries for historical dues payments
- Linking payments to members via customer_id
- Proper idempotency to prevent duplicate processing
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import flt, getdate

from verenigingen.integrations.mollie.core.mollie_client import MollieClient
from verenigingen.integrations.mollie.domain.payment_classification import PaymentClassifier


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

        Checks for Payment Entry with this reference_no in ANY state (draft, submitted, cancelled)
        to prevent duplicate processing even after failures.

        Args:
            payment_id: Mollie payment ID (e.g., "tr_xxxxxxxxx")

        Returns:
            dict: {
                "already_processed": bool,
                "payment_entry": str or None,
                "docstatus": int or None (0=Draft, 1=Submitted, 2=Cancelled),
                "details": str
            }
        """
        # Check for ANY Payment Entry with this reference_no (draft, submitted, cancelled)
        existing_entries = frappe.db.get_all(
            "Payment Entry", filters={"reference_no": payment_id}, fields=["name", "docstatus"], limit=1
        )

        if not existing_entries:
            return {
                "already_processed": False,
                "payment_entry": None,
                "docstatus": None,
                "details": "Payment not yet processed",
            }

        existing = existing_entries[0]
        status_map = {0: "Draft", 1: "Submitted", 2: "Cancelled"}
        status_text = status_map.get(existing.docstatus, "Unknown")

        # If cancelled, allow reprocessing (treat as not processed)
        if existing.docstatus == 2:
            frappe.logger().info(
                f"Found cancelled Payment Entry {existing.name} for payment {payment_id}. "
                f"Allowing reprocessing."
            )
            return {
                "already_processed": False,
                "payment_entry": existing.name,
                "docstatus": existing.docstatus,
                "details": f"Previous Payment Entry {existing.name} was cancelled, allowing reprocessing",
            }

        # Draft or Submitted - consider as already processed
        return {
            "already_processed": True,
            "payment_entry": existing.name,
            "docstatus": existing.docstatus,
            "details": f"Payment Entry {existing.name} already exists ({status_text})",
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
            "error": None,
            "skipped_reason": None,
        }

        try:
            # Fetch payment from Mollie if not provided
            if not payment:
                client = self.mollie_client._get_mollie_client()
                payment = client.payments.get(payment_id)

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

            # Create Payment Entry
            payment_entry_name = self._create_payment_entry_for_dues(member_name, payment)

            if payment_entry_name:
                result["status"] = "success"
                result["payment_entry"] = payment_entry_name
                frappe.logger().info(
                    f"✅ Successfully processed dues payment {payment_id} for member {member_name}"
                )
            else:
                result["status"] = "error"
                result["error"] = "Failed to create Payment Entry"

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            frappe.log_error(
                f"Error processing dues payment {payment_id}: {e}", "Dues Payment Processing Error"
            )

        return result

    def _create_payment_entry_for_dues(self, member_name: str, payment) -> Optional[str]:
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

            # 2. Customer receivable account (paid_from) - customer's outstanding balance
            customer_account = frappe.db.get_value(
                "Party Account", {"parent": customer, "company": company}, "account"
            )

            if not customer_account:
                # Fallback to company default
                customer_account = frappe.get_cached_value("Company", company, "default_receivable_account")

            if not customer_account:
                raise frappe.ValidationError(
                    f"No receivable account found for customer {customer}. "
                    f"Please configure Party Account or company default_receivable_account"
                )

            # 3. Mode of Payment
            mode_of_payment = getattr(settings, "mode_of_payment", None) or "Mollie"

            # Verify mode of payment exists
            if not frappe.db.exists("Mode of Payment", mode_of_payment):
                frappe.logger().warning(
                    f"Mode of Payment '{mode_of_payment}' not found, creating Payment Entry without it"
                )
                mode_of_payment = None

            # Find unpaid Sales Invoice to reconcile against
            # IMPORTANT: Match currency to prevent accounting errors
            unpaid_invoice = frappe.db.get_value(
                "Sales Invoice",
                {
                    "customer": customer,
                    "docstatus": 1,
                    "currency": currency,  # Match payment currency
                    "status": ["in", ["Unpaid", "Overdue", "Partly Paid"]],
                    "outstanding_amount": [">", 0],
                },
                ["name", "outstanding_amount", "currency"],
                order_by="posting_date asc",
                as_dict=True,
            )

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
            client = self.mollie_client._get_mollie_client()
            customer_obj = client.customers.get(customer_id)
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
