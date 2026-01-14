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
    - Overpayment detection and alerting (via shared PaymentAlertService)
    - Failure alerting for manual intervention (via shared PaymentAlertService)
    """

    SOURCE_NAME = "ING Checkout"

    def __init__(self):
        """Initialize the transaction service."""
        self._settings = None
        self._alert_service = None

    @property
    def settings(self) -> Dict[str, Any]:
        """Lazy-load payment settings."""
        if self._settings is None:
            from verenigingen.utils.settings_utils import get_payments_settings

            self._settings = get_payments_settings() or {}
        return self._settings

    @property
    def alert_service(self):
        """Lazy-load shared payment alert service."""
        if self._alert_service is None:
            from verenigingen.utils.payment_alert_service import get_payment_alert_service

            self._alert_service = get_payment_alert_service()
        return self._alert_service

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
        Handle overpayment detection - delegates to shared PaymentAlertService.

        Args:
            transaction_name: The INGCheckoutTransaction document name
            reference_name: The reference document name (e.g., Sales Invoice)
            transaction_amount: Amount paid in the transaction
            outstanding_amount: Amount that was due
        """
        self.alert_service.send_overpayment_alert(
            source=self.SOURCE_NAME,
            transaction_id=transaction_name,
            reference_name=reference_name,
            amount_paid=transaction_amount,
            amount_due=outstanding_amount,
            transaction_doctype="ING Checkout Transaction",
            transaction_name=transaction_name,
        )

    def send_payment_entry_failure_alert(
        self,
        transaction_name: str,
        reference_name: Optional[str],
        amount: float,
        error_message: str,
    ) -> None:
        """
        Send alert when Payment Entry creation fails - delegates to shared PaymentAlertService.

        Args:
            transaction_name: The INGCheckoutTransaction document name
            reference_name: The reference document name (optional)
            amount: Transaction amount
            error_message: The error that occurred
        """
        self.alert_service.send_payment_entry_failure_alert(
            source=self.SOURCE_NAME,
            transaction_id=transaction_name,
            reference_name=reference_name,
            amount=amount,
            error_message=error_message,
        )


def get_transaction_service() -> TransactionService:
    """Factory function to get TransactionService instance."""
    return TransactionService()
