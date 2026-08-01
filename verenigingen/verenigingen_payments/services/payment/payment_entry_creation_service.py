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

Gateway payments (Mollie, Ponto, ING) are supported via `bank_account`, `remarks` and
`system_context`; the four hand-rolled gateway wrappers are being migrated onto this
service so a fix lands in one place rather than four.

Does NOT handle:
- Unallocated payment entries (this service is invoice-driven by construction)
- Payment plan entries (different pattern - builds from scratch)
- Fee entries (Journal Entry doctype)
- Membership status updates (caller responsibility)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, Optional

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
        custom_fields: Optional[Dict[str, Any]] = None,
        bank_account: Optional[str] = None,
        remarks: Optional[str] = None,
        system_context: bool = False,
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
            custom_fields: Optional dict of custom field names to values to set on payment entry
                          (e.g., {"custom_sepa_batch": "BATCH-001", "custom_sepa_batch_item": "ITEM-001"})
            bank_account: Optional GL account the money lands in (a gateway clearing
                          account such as Mollie clearing, Ponto bank or ING). Passed
                          through to ERPNext, which derives paid_to/paid_from and the
                          matching account currency from it. Defaults to the company's
                          bank/cash account when omitted.
            remarks: Optional remarks text. Sets custom_remarks so Payment Entry.validate()
                     does not regenerate it. Omit to keep ERPNext's generated text.
            system_context: If True, skip the create/submit permission gates and insert
                            with ignore_permissions, then submit unconditionally. For
                            gateway webhook callers ONLY - they run with no user session,
                            and authorisation comes from the verified webhook. Never set
                            this on a path that serves a user request.

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

            # SEPA reconciliation with custom fields
            payment_entry = payment_entry_service.create_payment_entry_from_invoice(
                invoice_name="SI-2024-001",
                amount=Decimal("50.00"),
                posting_date=transaction_date,
                reference_no=bank_trans.reference_number,
                reference_date=transaction_date,
                mode_of_payment="SEPA Direct Debit",
                custom_fields={
                    "custom_bank_transaction": bank_trans.name,
                    "custom_sepa_batch": batch.name,
                    "custom_sepa_batch_item": item.name,
                }
            )
        """
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        # Validate amount
        if amount <= Decimal("0"):
            frappe.throw(_("Payment amount must be greater than zero. Got: {0}").format(amount))

        # Validate invoice exists
        if not frappe.db.exists("Sales Invoice", invoice_name):
            frappe.throw(_("Sales Invoice {0} does not exist").format(invoice_name))

        # Check permissions BEFORE starting any database operations.
        # SECURITY JUSTIFICATION: system_context skips these gates for gateway webhook
        # callers, which run with no user session and so have no permissions to check.
        # The payment is authorised by the gateway's own signed webhook, verified before
        # this point; the audit trail is the Payment Entry plus its reference_no. This is
        # an explicit, greppable opt-in - it must never be set on a request-serving path.
        if not system_context:
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

        # Skipping our own gates is not sufficient for a system-context caller: ERPNext's
        # get_payment_entry calls frappe.has_permission("Sales Invoice", "read", throw=True)
        # internally (get_reference_details), so the whole operation has to run elevated.
        # frappe.permissions.has_permission short-circuits only for Administrator, so that
        # is the elevation - restored in the finally below.
        # NOTE: that internal check does not exist in erpnext 16.20 (this bench) but does in
        # 16.30 (CI), so an implementation that only skipped our gates passed locally and
        # failed on CI. Elevating is correct on both.
        original_user = frappe.session.user
        if system_context and original_user != "Administrator":
            frappe.set_user("Administrator")

        try:
            # Get the invoice
            invoice = frappe.get_doc("Sales Invoice", invoice_name)

            # Convert Decimal to float for ERPNext API compatibility
            amount_float = float(amount)

            # Create payment entry using ERPNext's standard function
            # This auto-populates accounts, party information, and references.
            # bank_account is passed THROUGH rather than assigned afterwards: ERPNext
            # derives paid_to/paid_from *and* the matching account currency from the
            # account it resolves here (payment_entry.py:2921-2925), so a post-hoc
            # assignment would move the account and leave the currency behind.
            payment_entry = get_payment_entry(
                dt="Sales Invoice",
                dn=invoice.name,
                party_amount=amount_float,
                bank_account=bank_account,
            )

            # Set payment details
            payment_entry.payment_type = payment_type
            payment_entry.mode_of_payment = mode_of_payment
            payment_entry.reference_no = reference_no
            payment_entry.reference_date = reference_date
            payment_entry.posting_date = posting_date

            # Gateway callers supply their own remarks (payment id, orphan banner,
            # payment-link name); otherwise keep the text ERPNext generated.
            # custom_remarks MUST be set alongside: Payment Entry.validate() calls
            # set_remarks(), which regenerates the field from the amount/party and
            # returns early only when custom_remarks is truthy. Assigning remarks alone
            # is silently discarded on save.
            if remarks:
                payment_entry.remarks = remarks
                payment_entry.custom_remarks = 1

            # Set paid/received amounts explicitly
            payment_entry.paid_amount = amount_float
            payment_entry.received_amount = amount_float

            # Link to bank transaction if provided (for reconciliation path)
            if bank_transaction_name:
                payment_entry.bank_transaction = bank_transaction_name

            # Apply custom fields if provided (for SEPA batch tracking, etc.)
            if custom_fields:
                for field_name, field_value in custom_fields.items():
                    if hasattr(payment_entry, field_name):
                        setattr(payment_entry, field_name, field_value)
                    else:
                        frappe.logger().warning(
                            f"Custom field '{field_name}' not found on Payment Entry - skipping"
                        )

            # Insert payment entry.
            # SECURITY JUSTIFICATION: see the system_context gate above - a gateway
            # webhook has no user session to carry create permission, and the write is
            # authorised by the verified webhook rather than by a Frappe role.
            payment_entry.insert(ignore_permissions=system_context)

            # Try to submit
            # System context submits unconditionally: there is no user whose instance
            # permission could be consulted, and leaving a gateway payment as a draft
            # would strand the money off the ledger.
            if system_context:
                payment_entry.submit()
                frappe.logger().info(
                    f"Created and submitted payment entry {payment_entry.name} for invoice "
                    f"{invoice_name} in system context"
                )
            # In strict mode, we already checked permission above
            # In graceful mode, we check instance-level permission here
            elif allow_draft_on_permission_failure:
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

        finally:
            # Always hand the session back, including on the error paths above - a
            # webhook request continues after this call.
            if frappe.session.user != original_user:
                frappe.set_user(original_user)


# Singleton instance for convenience
payment_entry_service = PaymentEntryCreationService()
