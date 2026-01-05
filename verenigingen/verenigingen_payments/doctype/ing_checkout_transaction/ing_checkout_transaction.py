# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
ING Checkout Transaction DocType

Tracks Pay.nl payment transactions and handles Payment Entry creation
when payments are confirmed.

Security:
- Uses savepoints for atomic Payment Entry creation
- Validates amounts before creating Payment Entries
- Uses configured bank account only (no fallbacks)
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

# Status code mapping from Pay.nl
STATUS_MAP = {
    20: "Pending",
    25: "Processing",
    100: "Paid",
    -90: "Cancelled",
    -63: "Denied",
    -64: "Expired",
    -81: "Refunded",
}


class INGCheckoutTransaction(Document):
    """
    Tracks ING Checkout (Pay.nl) payment transactions.

    Links payments to reference documents (Sales Invoice, etc.)
    and stores customer payment details from webhooks.
    """

    def validate(self):
        """Validate transaction data."""
        if self.amount and flt(self.amount) < 0:
            frappe.throw(_("Amount cannot be negative"))

    def update_from_webhook(self, webhook_data: dict):
        """
        Update transaction from Pay.nl webhook data.

        Uses savepoint for atomic updates including Payment Entry creation.

        Args:
            webhook_data: Parsed webhook payload from Pay.nl
        """
        order_object = webhook_data.get("object", {})
        status = order_object.get("status", {})
        status_code = status.get("code", 0)

        # Update status
        new_status = STATUS_MAP.get(status_code, "Pending")
        old_status = self.status

        self.status = new_status

        # Extract customer info from payments
        payments = order_object.get("payments", [])
        if payments:
            customer_method = payments[0].get("customerMethod", {})
            self.customer_name = customer_method.get("name")
            self.customer_iban = customer_method.get("iban")
            self.customer_bic = customer_method.get("bic")

        # Store raw response
        self.raw_response = frappe.as_json(webhook_data)

        # SECURITY JUSTIFICATION: Transaction update from webhook callback.
        # No user session during webhook processing. Audit trail via transaction record.
        self.save(ignore_permissions=True)

        # If paid, create Payment Entry (with savepoint for atomicity)
        if self.status == "Paid" and old_status != "Paid" and not self.payment_entry:
            savepoint_name = f"payment_entry_{self.name}"
            try:
                frappe.db.savepoint(savepoint_name)
                self._create_payment_entry()
            except Exception as e:
                frappe.db.rollback(save_point=savepoint_name)
                frappe.log_error(
                    title="ING Checkout: Payment Entry creation failed",
                    message=f"Transaction: {self.name}\nError: {str(e)}",
                )

    def _create_payment_entry(self):
        """
        Create Payment Entry for paid transaction.

        Requirements:
        - Reference document must exist
        - Bank account must be configured in settings (no fallbacks)
        - Amount must be validated against invoice outstanding
        """
        if self.payment_entry:
            return  # Already created

        if not self.reference_doctype or not self.reference_name:
            frappe.log_error(
                title="ING Checkout: Cannot create Payment Entry",
                message=f"Transaction {self.name} has no reference document",
            )
            return

        # Only handle Sales Invoice for now
        if self.reference_doctype != "Sales Invoice":
            frappe.log_error(
                title="ING Checkout: Unsupported reference type",
                message=f"Cannot create Payment Entry for {self.reference_doctype}",
            )
            return

        # Get the reference document
        if not frappe.db.exists(self.reference_doctype, self.reference_name):
            frappe.log_error(
                title="ING Checkout: Reference document not found",
                message=f"Cannot find {self.reference_doctype} {self.reference_name}",
            )
            return

        ref_doc = frappe.get_doc(self.reference_doctype, self.reference_name)

        # Get bank account from settings - NO FALLBACKS
        from verenigingen.utils.settings_utils import get_payments_settings

        settings = get_payments_settings()
        bank_account = settings.get("ing_checkout_bank_account")

        if not bank_account:
            frappe.log_error(
                title="ING Checkout: Bank account not configured",
                message=(
                    f"Cannot create Payment Entry for transaction {self.name}. "
                    "Configure 'ING Checkout Bank Account' in Verenigingen Payments Settings."
                ),
            )
            return

        # Validate bank account exists
        if not frappe.db.exists("Account", bank_account):
            frappe.log_error(
                title="ING Checkout: Invalid bank account",
                message=f"Bank account {bank_account} does not exist",
            )
            return

        # Validate amounts
        transaction_amount = flt(self.amount)
        outstanding_amount = flt(ref_doc.outstanding_amount)

        if transaction_amount <= 0:
            frappe.log_error(
                title="ING Checkout: Invalid transaction amount",
                message=f"Transaction {self.name} has invalid amount: {transaction_amount}",
            )
            return

        if outstanding_amount <= 0:
            frappe.logger().info(
                f"Sales Invoice {self.reference_name} already paid (outstanding: {outstanding_amount})"
            )
            return

        # Calculate allocation - allocate up to outstanding amount
        allocation_amount = min(transaction_amount, outstanding_amount)

        try:
            # Use ERPNext's get_payment_entry for proper account handling
            from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

            payment_entry = get_payment_entry(
                dt="Sales Invoice",
                dn=self.reference_name,
                party_amount=allocation_amount,
                bank_account=bank_account,
            )

            # Override with ING Checkout specific fields
            payment_entry.posting_date = frappe.utils.today()
            payment_entry.reference_no = self.transaction_id or self.name
            payment_entry.reference_date = frappe.utils.today()
            payment_entry.mode_of_payment = "iDEAL"
            payment_entry.paid_to = bank_account
            payment_entry.remarks = f"ING Checkout payment: {self.transaction_id}"

            # SECURITY JUSTIFICATION: Creating Payment Entry from webhook callback.
            # No user session during webhook processing. Audit trail via Payment Entry.
            payment_entry.insert(ignore_permissions=True)
            payment_entry.submit()

            # Link to transaction
            self.payment_entry = payment_entry.name
            self.db_set("payment_entry", payment_entry.name)

            frappe.logger().info(
                f"Created Payment Entry {payment_entry.name} for ING Checkout transaction {self.name} "
                f"(amount: {allocation_amount}, invoice: {self.reference_name})"
            )

        except Exception as e:
            frappe.log_error(
                title="ING Checkout: Payment Entry creation failed",
                message=f"Transaction: {self.name}\nInvoice: {self.reference_name}\nError: {str(e)}",
            )
            raise


def get_or_create_transaction(
    transaction_id: str,
    reference_doctype: str = None,
    reference_name: str = None,
    amount: float = None,
    payment_method: str = "iDEAL",
) -> INGCheckoutTransaction:
    """
    Get existing transaction or create new one.

    Args:
        transaction_id: Pay.nl order ID
        reference_doctype: Optional reference DocType
        reference_name: Optional reference document name
        amount: Transaction amount
        payment_method: Payment method name

    Returns:
        INGCheckoutTransaction document
    """
    existing = frappe.db.get_value(
        "ING Checkout Transaction",
        {"transaction_id": transaction_id},
        "name",
    )

    if existing:
        return frappe.get_doc("ING Checkout Transaction", existing)

    doc = frappe.new_doc("ING Checkout Transaction")
    doc.transaction_id = transaction_id
    doc.reference_doctype = reference_doctype
    doc.reference_name = reference_name
    doc.amount = flt(amount)
    doc.payment_method = payment_method
    doc.status = "Pending"
    # SECURITY JUSTIFICATION: Transaction creation from webhook callback.
    # No user session during webhook processing. Audit trail via transaction record.
    doc.insert(ignore_permissions=True)

    return doc
