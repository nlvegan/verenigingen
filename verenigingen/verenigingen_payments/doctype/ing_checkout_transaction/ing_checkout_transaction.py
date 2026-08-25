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

Note: Business logic for Payment Entry creation has been extracted to
TransactionService for better separation of concerns.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS, rollback_to_savepoint

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
            self._create_payment_entry_with_savepoint()

    def _create_payment_entry_with_savepoint(self):
        """Create Payment Entry with savepoint for atomicity."""
        from verenigingen.verenigingen_payments.ing_checkout.services import get_transaction_service

        service = get_transaction_service()
        savepoint_name = f"payment_entry_{self.name}"

        try:
            frappe.db.savepoint(savepoint_name)

            result = service.create_payment_entry_for_transaction(
                transaction_name=self.name,
                transaction_id=self.transaction_id,
                reference_doctype=self.reference_doctype,
                reference_name=self.reference_name,
                amount=flt(self.amount),
            )

            if result["success"]:
                # Link Payment Entry to transaction
                self.payment_entry = result["payment_entry"]
                self.db_set("payment_entry", result["payment_entry"])

                # Handle overpayment if detected
                if result.get("overpayment"):
                    ref_doc = frappe.get_doc(self.reference_doctype, self.reference_name)
                    service.handle_overpayment(
                        transaction_name=self.name,
                        reference_name=self.reference_name,
                        transaction_amount=flt(self.amount),
                        outstanding_amount=flt(ref_doc.outstanding_amount),
                    )
            elif result.get("error"):
                # Log but don't fail - transaction is still paid
                frappe.logger().warning(
                    f"ING Checkout transaction {self.name} paid but Payment Entry not created: {result['error']}"
                )

        except NON_RESUMABLE_DB_ERRORS:
            # The db_set and add_comment below are writes, and on a 1205/1213 they land on
            # a transaction the server has discarded or half-applied -- so the "Paid -
            # Payment Entry Failed" marker that exists to make this visible is itself the
            # thing most likely to vanish. This runs synchronously inside the webhook, so
            # propagating reaches ing_checkout/api/webhook.py, which sets HTTP 500 -- what
            # the gateway retries on. (Whether Pay.nl in fact retries a 500 is the gateway's
            # policy and is NOT verified here.)
            raise
        except Exception as e:
            rollback_to_savepoint(savepoint_name)

            # Mark transaction with failure status for visibility
            self.db_set("status", "Paid - Payment Entry Failed")
            self.add_comment(
                "Comment",
                f"Payment Entry creation failed: {str(e)}\n\n"
                "Manual intervention required to create Payment Entry.",
            )

            frappe.log_error(
                title="ING Checkout: Payment Entry creation failed",
                message=f"Transaction: {self.name}\nError: {str(e)}",
            )

            # Alert system managers about failed payment entry
            service.send_payment_entry_failure_alert(
                transaction_name=self.name,
                reference_name=self.reference_name,
                amount=flt(self.amount),
                error_message=str(e),
            )


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
