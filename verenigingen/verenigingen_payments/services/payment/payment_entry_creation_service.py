"""
Payment Entry Creation Service

Unified payment entry creation service that consolidates duplicate logic from:
- batch_processing_service._create_payment_entry_for_invoice()
- direct_debit_batch.create_payment_entry_for_invoice()
- sepa_reconciliation.create_payment_entry_from_transaction()

This service provides standardized payment entry creation with:
- Explicit permission checking before database operations
- Proper exception handling (fail-fast for financial operations)
- Input validation (amount, invoice existence)
- Optional graceful degradation to draft entries

Does NOT handle:
- Gateway-specific payments (Mollie clearing accounts, custom fields)
- Payment plan entries (different pattern - builds from scratch)
- Fee entries (Journal Entry doctype)
- Membership status updates (caller responsibility)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

import frappe
from frappe import _

if TYPE_CHECKING:
    from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry


class PaymentEntryCreationService:
    """
    Service for creating payment entries from invoices.

    Provides standardized payment entry creation with permission-aware
    operations, proper error handling, and input validation.
    """

    @staticmethod
    def create_payment_entry_from_invoice(
        invoice_name: str,
        amount: Decimal,
        posting_date: date,
        reference_no: str,
        reference_date: date,
        mode_of_payment: str,
        payment_type: str = "Receive",
        bank_transaction_name: Optional[str] = None,
        allow_draft_on_permission_failure: bool = False,
    ) -> "PaymentEntry":
        """
        Create and submit payment entry from invoice.

        Args:
            invoice_name: Sales Invoice name
            amount: Payment amount (must be positive)
            posting_date: Posting date for payment entry
            reference_no: Payment reference number
            reference_date: Reference date for payment
            mode_of_payment: Payment method (SEPA Direct Debit, Bank Transfer, etc.)
            payment_type: Payment type (Receive/Pay), default "Receive"
            bank_transaction_name: Optional link to Bank Transaction for reconciliation
            allow_draft_on_permission_failure: If True, return draft entry if user lacks
                                               submit permission (for reconciliation workflows)

        Returns:
            PaymentEntry: Created and submitted Payment Entry document
                         (or draft if allow_draft_on_permission_failure=True and lacking permission)

        Raises:
            frappe.DoesNotExistError: If invoice doesn't exist
            frappe.ValidationError: If amount is invalid (negative, zero)
            frappe.PermissionError: If user lacks create permission, or lacks submit permission
                                   in strict mode (allow_draft_on_permission_failure=False)

        Examples:
            # Standard batch processing (strict mode - must submit)
            from verenigingen.verenigingen_payments.services.payment import payment_entry_service

            payment_entry = payment_entry_service.create_payment_entry_from_invoice(
                invoice_name="SI-2024-001",
                amount=Decimal("50.00"),
                posting_date=date.today(),
                reference_no="BATCH-001",
                reference_date=date.today(),
                mode_of_payment="SEPA Direct Debit"
            )
            # Returns: submitted Payment Entry or raises exception

            # Bank reconciliation (graceful degradation)
            payment_entry = payment_entry_service.create_payment_entry_from_invoice(
                invoice_name="SI-2024-001",
                amount=Decimal("50.00"),
                posting_date=transaction_date,
                reference_no=bank_trans.reference_number,
                reference_date=transaction_date,
                mode_of_payment="SEPA Direct Debit",
                bank_transaction_name=bank_trans.name,
                allow_draft_on_permission_failure=True  # Can return draft
            )
            # Returns: submitted Payment Entry, or draft if lacking submit permission, or raises
        """
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        # Validate amount
        if amount <= Decimal("0"):
            frappe.throw(_("Payment amount must be greater than zero. Got: {0}").format(amount))

        # Validate invoice exists
        if not frappe.db.exists("Sales Invoice", invoice_name):
            frappe.throw(_("Sales Invoice {0} does not exist").format(invoice_name))

        # Check permissions BEFORE starting any database operations
        if not frappe.has_permission("Payment Entry", "create"):
            frappe.throw(
                _("Insufficient permissions to create payment entry"),
                frappe.PermissionError,
            )

        # Check submit permission for strict mode
        if not allow_draft_on_permission_failure:
            # In strict mode, we need submit permission upfront
            # Check on doctype level first (more efficient)
            if not frappe.has_permission("Payment Entry", "submit"):
                frappe.throw(
                    _("Insufficient permissions to submit payment entry"),
                    frappe.PermissionError,
                )

        try:
            # Get the invoice
            invoice = frappe.get_doc("Sales Invoice", invoice_name)

            # Convert Decimal to float for ERPNext API compatibility
            amount_float = float(amount)

            # Create payment entry using ERPNext's standard function
            # This auto-populates accounts, party information, and references
            payment_entry = get_payment_entry(dt="Sales Invoice", dn=invoice.name, party_amount=amount_float)

            # Set payment details
            payment_entry.payment_type = payment_type
            payment_entry.mode_of_payment = mode_of_payment
            payment_entry.reference_no = reference_no
            payment_entry.reference_date = reference_date
            payment_entry.posting_date = posting_date

            # Set paid/received amounts explicitly
            payment_entry.paid_amount = amount_float
            payment_entry.received_amount = amount_float

            # Link to bank transaction if provided (for reconciliation path)
            if bank_transaction_name:
                payment_entry.bank_transaction = bank_transaction_name

            # Insert payment entry
            payment_entry.insert()

            # Try to submit
            # In strict mode, we already checked permission above
            # In graceful mode, we check instance-level permission here
            if allow_draft_on_permission_failure:
                # Check instance-level permission
                if frappe.has_permission("Payment Entry", "submit", payment_entry):
                    payment_entry.submit()
                    frappe.logger().info(
                        f"Created and submitted payment entry {payment_entry.name} for invoice {invoice_name}"
                    )
                else:
                    # Graceful degradation - return draft for manual review
                    frappe.logger().warning(
                        f"User {frappe.session.user} created draft payment entry {payment_entry.name} "
                        f"for invoice {invoice_name} - lacks submit permission. Manual review required."
                    )
            else:
                # Strict mode - we already validated permission, just submit
                payment_entry.submit()
                frappe.logger().info(
                    f"Created and submitted payment entry {payment_entry.name} for invoice {invoice_name}"
                )

            return payment_entry

        except frappe.PermissionError:
            # Re-raise permission errors as-is (security boundary)
            raise

        except frappe.ValidationError as e:
            # ERPNext raises ValidationError for both:
            # 1. Business rule violations (currency mismatch, account config)
            # 2. Data validation (party doesn't exist, etc.)
            #
            # Distinguish by checking error message for setup/config keywords
            error_msg = str(e).lower()

            # Setup/configuration errors - likely need admin intervention
            setup_keywords = [
                "account",
                "currency",
                "does not exist",
                "not permitted",
                "is mandatory",
                "must be",
            ]

            if any(keyword in error_msg for keyword in setup_keywords):
                # Log as configuration error for admin visibility
                frappe.log_error(
                    f"Payment entry configuration error for invoice {invoice_name}: {str(e)}\n"
                    f"This may indicate missing account setup, currency mismatch, or party configuration issues.",
                    "Payment Entry Configuration Error",
                )
                # Re-raise with additional context for admins
                frappe.throw(
                    _(
                        "Payment entry creation failed due to system configuration: {0}\n\n"
                        "Please check account setup, currency configuration, and party settings."
                    ).format(str(e)),
                    frappe.ValidationError,
                )
            else:
                # Business rule violation or data issue - re-raise as-is
                # These are typically user-correctable (e.g., duplicate entry, invalid state)
                raise

        except Exception as e:
            # Unexpected errors (framework issues, database errors, etc.)
            # These are rare and indicate serious problems
            frappe.log_error(
                f"Unexpected error creating payment entry for invoice {invoice_name}: {str(e)}",
                "Payment Entry Unexpected Error",
            )
            frappe.throw(
                _(
                    "An unexpected error occurred while creating payment entry for invoice {0}. "
                    "Please contact system administrator."
                ).format(invoice_name),
                exc=e,
            )


# Singleton instance for convenience
payment_entry_service = PaymentEntryCreationService()
