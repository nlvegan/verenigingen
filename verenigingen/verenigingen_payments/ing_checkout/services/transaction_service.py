# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
ING Checkout Transaction Service

Handles Payment Entry creation and related business logic for ING Checkout transactions.
Extracted from INGCheckoutTransaction DocType for better separation of concerns.

Security:
- Uses savepoints for atomic Payment Entry creation
- Validates amounts before creating Payment Entries
- Uses configured bank account only (no fallbacks)
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import flt


class TransactionService:
    """
    Service for handling ING Checkout transaction operations.

    Provides:
    - Payment Entry creation from confirmed transactions
    - Overpayment detection and alerting
    - Failure alerting for manual intervention
    """

    def __init__(self):
        """Initialize the transaction service."""
        self._settings = None

    @property
    def settings(self) -> Dict[str, Any]:
        """Lazy-load payment settings."""
        if self._settings is None:
            from verenigingen.utils.settings_utils import get_payments_settings

            self._settings = get_payments_settings() or {}
        return self._settings

    def create_payment_entry_for_transaction(
        self,
        transaction_name: str,
        transaction_id: str,
        reference_doctype: str,
        reference_name: str,
        amount: float,
    ) -> Dict[str, Any]:
        """
        Create Payment Entry for a paid ING Checkout transaction.

        Args:
            transaction_name: The INGCheckoutTransaction document name
            transaction_id: The Pay.nl transaction/order ID
            reference_doctype: Type of reference document (e.g., 'Sales Invoice')
            reference_name: Name of the reference document
            amount: Transaction amount

        Returns:
            Dict with:
                - success: bool
                - payment_entry: str (name of created Payment Entry, if successful)
                - error: str (error message, if failed)
                - overpayment: float (if overpayment detected)
        """
        result = {
            "success": False,
            "payment_entry": None,
            "error": None,
            "overpayment": None,
        }

        # Validate inputs
        validation_error = self._validate_payment_entry_inputs(
            transaction_name, reference_doctype, reference_name, amount
        )
        if validation_error:
            result["error"] = validation_error
            return result

        # Only handle Sales Invoice for now
        if reference_doctype != "Sales Invoice":
            result["error"] = f"Unsupported reference type: {reference_doctype}"
            frappe.log_error(
                title="ING Checkout: Unsupported reference type",
                message=f"Cannot create Payment Entry for {reference_doctype}",
            )
            return result

        # Get the reference document
        if not frappe.db.exists(reference_doctype, reference_name):
            result["error"] = f"Reference document not found: {reference_name}"
            frappe.log_error(
                title="ING Checkout: Reference document not found",
                message=f"Cannot find {reference_doctype} {reference_name}",
            )
            return result

        ref_doc = frappe.get_doc(reference_doctype, reference_name)

        # Get and validate bank account
        bank_account = self.settings.get("ing_checkout_bank_account")
        if not bank_account:
            result["error"] = "Bank account not configured in Verenigingen Payments Settings"
            frappe.log_error(
                title="ING Checkout: Bank account not configured",
                message=(
                    f"Cannot create Payment Entry for transaction {transaction_name}. "
                    "Configure 'ING Checkout Bank Account' in Verenigingen Payments Settings."
                ),
            )
            return result

        if not frappe.db.exists("Account", bank_account):
            result["error"] = f"Bank account {bank_account} does not exist"
            frappe.log_error(
                title="ING Checkout: Invalid bank account",
                message=f"Bank account {bank_account} does not exist",
            )
            return result

        # Validate amounts
        transaction_amount = flt(amount)
        outstanding_amount = flt(ref_doc.outstanding_amount)

        if transaction_amount <= 0:
            result["error"] = f"Invalid transaction amount: {transaction_amount}"
            frappe.log_error(
                title="ING Checkout: Invalid transaction amount",
                message=f"Transaction {transaction_name} has invalid amount: {transaction_amount}",
            )
            return result

        if outstanding_amount <= 0:
            result["error"] = "Invoice already paid"
            frappe.logger().info(
                f"Sales Invoice {reference_name} already paid (outstanding: {outstanding_amount})"
            )
            return result

        # Check for overpayment
        if transaction_amount > outstanding_amount:
            overpayment = transaction_amount - outstanding_amount
            result["overpayment"] = overpayment

        # Calculate allocation - allocate up to outstanding amount
        allocation_amount = min(transaction_amount, outstanding_amount)

        try:
            # Use ERPNext's get_payment_entry for proper account handling
            from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

            payment_entry = get_payment_entry(
                dt="Sales Invoice",
                dn=reference_name,
                party_amount=allocation_amount,
                bank_account=bank_account,
            )

            # Override with ING Checkout specific fields
            payment_entry.posting_date = frappe.utils.today()
            payment_entry.reference_no = transaction_id or transaction_name
            payment_entry.reference_date = frappe.utils.today()
            payment_entry.mode_of_payment = "iDEAL"
            payment_entry.paid_to = bank_account
            payment_entry.remarks = f"ING Checkout payment: {transaction_id}"

            # SECURITY JUSTIFICATION: Creating Payment Entry from webhook callback.
            # No user session during webhook processing. Audit trail via Payment Entry.
            payment_entry.insert(ignore_permissions=True)
            payment_entry.submit()

            result["success"] = True
            result["payment_entry"] = payment_entry.name

            frappe.logger().info(
                f"Created Payment Entry {payment_entry.name} for ING Checkout transaction {transaction_name} "
                f"(amount: {allocation_amount}, invoice: {reference_name})"
            )

        except Exception as e:
            result["error"] = str(e)
            frappe.log_error(
                title="ING Checkout: Payment Entry creation failed",
                message=f"Transaction: {transaction_name}\nInvoice: {reference_name}\nError: {str(e)}",
            )
            raise  # Re-raise for savepoint handling

        return result

    def _validate_payment_entry_inputs(
        self,
        transaction_name: str,
        reference_doctype: Optional[str],
        reference_name: Optional[str],
        amount: float,
    ) -> Optional[str]:
        """
        Validate inputs for Payment Entry creation.

        Returns:
            Error message string if validation fails, None if valid
        """
        if not transaction_name:
            return "Transaction name is required"

        if not reference_doctype or not reference_name:
            return f"Transaction {transaction_name} has no reference document"

        if amount is None or flt(amount) <= 0:
            return f"Invalid amount for transaction {transaction_name}"

        return None

    def handle_overpayment(
        self,
        transaction_name: str,
        reference_name: str,
        transaction_amount: float,
        outstanding_amount: float,
    ) -> None:
        """
        Handle overpayment detection - log and alert for manual review.

        Args:
            transaction_name: The INGCheckoutTransaction document name
            reference_name: The reference document name (e.g., Sales Invoice)
            transaction_amount: Amount paid in the transaction
            outstanding_amount: Amount that was due
        """
        overpayment = transaction_amount - outstanding_amount

        # Log for review
        frappe.log_error(
            title=f"ING Checkout: Overpayment detected - {transaction_name}",
            message=(
                f"Transaction: {transaction_name}\n"
                f"Invoice: {reference_name}\n"
                f"Transaction Amount: {transaction_amount:.2f}\n"
                f"Outstanding Amount: {outstanding_amount:.2f}\n"
                f"Overpayment: {overpayment:.2f}\n\n"
                "Action Required: Review for refund or credit note."
            ),
        )

        # Add comment to transaction
        try:
            transaction = frappe.get_doc("ING Checkout Transaction", transaction_name)
            transaction.add_comment(
                "Comment",
                f"Overpayment of {overpayment:.2f} detected.\n"
                f"Customer paid {transaction_amount:.2f} but only {outstanding_amount:.2f} was due.\n"
                f"Allocated {outstanding_amount:.2f} to invoice. Review for refund.",
            )
        except Exception as e:
            frappe.logger().warning(f"Failed to add overpayment comment: {e}")

        # Send alert email
        self._send_overpayment_alert(
            transaction_name, reference_name, transaction_amount, outstanding_amount, overpayment
        )

    def _send_overpayment_alert(
        self,
        transaction_name: str,
        reference_name: str,
        transaction_amount: float,
        outstanding_amount: float,
        overpayment: float,
    ) -> None:
        """Send alert email for overpayment."""
        try:
            recipients = frappe.get_hooks("accounts_managers_email") or []
            if not recipients:
                frappe.log_error(
                    title="No Alert Recipients Configured",
                    message=(
                        f"Cannot send overpayment alert for {transaction_name}: "
                        "accounts_managers_email hook not configured. "
                        f"Overpayment of {overpayment:.2f} requires manual review."
                    ),
                )
                return

            frappe.sendmail(
                recipients=recipients,
                subject=f"ING Checkout Overpayment: {transaction_name} - {overpayment:.2f}",
                message=(
                    f"<p>An overpayment has been detected for ING Checkout transaction.</p>"
                    f"<p><strong>Transaction:</strong> {transaction_name}</p>"
                    f"<p><strong>Invoice:</strong> {reference_name}</p>"
                    f"<p><strong>Amount Paid:</strong> {transaction_amount:.2f}</p>"
                    f"<p><strong>Amount Due:</strong> {outstanding_amount:.2f}</p>"
                    f"<p><strong>Overpayment:</strong> {overpayment:.2f}</p>"
                    f"<p>Please review and process a refund or credit note as appropriate.</p>"
                ),
            )
        except Exception as e:
            frappe.logger().warning(f"Failed to send overpayment alert email: {e}")

    def send_payment_entry_failure_alert(
        self,
        transaction_name: str,
        reference_name: Optional[str],
        amount: float,
        error_message: str,
    ) -> None:
        """
        Send alert email when Payment Entry creation fails.

        Args:
            transaction_name: The INGCheckoutTransaction document name
            reference_name: The reference document name (optional)
            amount: Transaction amount
            error_message: The error that occurred
        """
        try:
            recipients = frappe.get_hooks("accounts_managers_email") or []
            if not recipients:
                frappe.log_error(
                    title="No Alert Recipients Configured",
                    message=(
                        f"Cannot send Payment Entry failure alert for {transaction_name}: "
                        "accounts_managers_email hook not configured. "
                        f"Error: {error_message}"
                    ),
                )
                return

            frappe.sendmail(
                recipients=recipients,
                subject=f"URGENT: ING Checkout Payment Entry Failed - {transaction_name}",
                message=(
                    f"<p><strong>Payment Entry creation failed for ING Checkout transaction.</strong></p>"
                    f"<p><strong>Transaction:</strong> {transaction_name}</p>"
                    f"<p><strong>Invoice:</strong> {reference_name or 'N/A'}</p>"
                    f"<p><strong>Amount:</strong> {flt(amount):.2f}</p>"
                    f"<p><strong>Error:</strong></p>"
                    f"<pre>{error_message}</pre>"
                    f"<p>Manual intervention is required to create the Payment Entry.</p>"
                ),
            )
        except Exception as e:
            frappe.logger().warning(f"Failed to send payment entry failure alert email: {e}")


def get_transaction_service() -> TransactionService:
    """Factory function to get TransactionService instance."""
    return TransactionService()
