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
from frappe.utils import flt, getdate, today


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

        # A draft (docstatus 0) does NOT carry outstanding_amount == 0 - it carries
        # its full grand_total (calculate_outstanding_amount runs on every save that
        # is not cancelled). So this must be checked BEFORE the outstanding_amount
        # <= 0 "already paid" branch below, or a draft falls through as a normal
        # unpaid invoice and is handed to the allocator, which ERPNext then refuses
        # at Payment Entry submit time ("... must be submitted"). #856/#209.
        if ref_doc.docstatus != 1:
            not_submitted_msg = (
                f"{reference_doctype} {reference_name} is not submitted (docstatus {ref_doc.docstatus})"
            )
            result["error"] = not_submitted_msg
            frappe.log_error(
                title="ING Checkout: Reference document not submitted",
                message=(
                    f"Cannot create Payment Entry for transaction {transaction_name}: "
                    f"{reference_doctype} {reference_name} has docstatus {ref_doc.docstatus}, "
                    "needs manual review"
                ),
            )
            return result

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
            # Delegate to PaymentEntryCreationService so this path shares one
            # payment-entry contract with the rest of the app; Ponto and the Mollie
            # orphan path already do. Two behaviours change with it:
            #
            # * the remarks WORDING now persists. The service sets custom_remarks
            #   alongside the text; without it Payment Entry.validate() calls
            #   set_remarks(), which rebuilds the field and discards what was assigned.
            #   Note what this does NOT mean: the transaction id survived either way,
            #   because ERPNext's generated text appends "Transaction reference no
            #   {reference_no} dated {date}" (PaymentEntry.set_remarks). What was
            #   lost is the "ING Checkout payment" phrasing that tells an operator
            #   which gateway the entry came from.
            # * permissions are enforced rather than bypassed. This used
            #   ignore_permissions=True on the grounds that there is "no user session
            #   during webhook processing", which is not the case: the webhook entry
            #   point calls frappe.set_user() with the service account from
            #   Verenigingen Payments Settings.webhook_user (ing_checkout/utils/
            #   webhook_security.py) - the same account the Mollie path runs as, which
            #   holds Payment Entry create/write/submit.
            #
            # paid_to is no longer assigned after the fact: bank_account is passed
            # through to ERPNext, which derives paid_to AND the matching account
            # currency from it. The old post-hoc assignment was redundant here (the
            # same account was already passed in) but is a trap worth not copying.
            from decimal import Decimal

            from verenigingen.verenigingen_payments.services.payment import payment_entry_service

            payment_entry = payment_entry_service.create_payment_entry_from_invoice(
                invoice_name=reference_name,
                amount=Decimal(str(allocation_amount)),
                posting_date=getdate(today()),
                reference_no=transaction_id or transaction_name,
                reference_date=getdate(today()),
                mode_of_payment="iDEAL",
                bank_account=bank_account,
                remarks=f"ING Checkout payment: {transaction_id}",
                # Record the whole transaction, not just the part this invoice can
                # absorb. The cap above still decides what SETTLES the invoice; the
                # excess becomes an unallocated credit on the customer instead of
                # vanishing. Without this the ING clearing account was debited the
                # capped figure while Pay.nl had settled the full amount, so the
                # account could not reconcile against the settlement file. The
                # overpayment detection above is unchanged and still populates
                # result["overpayment"].
                cash_received=Decimal(str(transaction_amount)),
            )

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
