# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, getdate, today

# Mandate status mapping from Pay.nl
MANDATE_STATUS_MAP = {
    "pending": "Pending",
    "active": "Active",
    "used": "Used",  # For single mandates after use
    "cancelled": "Cancelled",
    "expired": "Expired",
    "failed": "Failed",
}


class INGCheckoutMandate(Document):
    """
    Tracks ING Checkout (Pay.nl) SEPA Direct Debit mandates.

    Mandates authorize the collection of payments from a debtor's bank account.
    Types:
    - single: One-time collection
    - recurring: Regular fixed-interval collections
    - flexible: Variable amount/timing collections (recommended for associations)
    """

    def validate(self):
        """Validate mandate data."""
        self._validate_iban()
        self._validate_type()
        self._set_expiry_date()

    def _validate_iban(self):
        """Validate IBAN format."""
        if self.debtor_iban:
            iban = self.debtor_iban.replace(" ", "").upper()
            if len(iban) < 15 or len(iban) > 34:
                frappe.throw(_("Invalid IBAN length"))
            self.debtor_iban = iban

    def _validate_type(self):
        """Validate mandate type requirements."""
        if self.mandate_type == "single" and not self.amount:
            frappe.throw(_("Amount is required for single-use mandates"))

    def _set_expiry_date(self):
        """Set expiry date based on SEPA rules (36 months from creation)."""
        if not self.expiry_date and self.created_date:
            self.expiry_date = add_months(getdate(self.created_date), 36)
        elif not self.expiry_date:
            self.expiry_date = add_months(getdate(today()), 36)

    def update_from_webhook(self, webhook_data: dict):
        """
        Update mandate from Pay.nl webhook data.

        Args:
            webhook_data: Parsed webhook payload from Pay.nl
        """
        mandate_object = webhook_data.get("object", {})
        status = mandate_object.get("status", "").lower()

        # Update status
        if status in MANDATE_STATUS_MAP:
            self.status = MANDATE_STATUS_MAP[status]

        # Update dates if provided
        if mandate_object.get("firstCollectionDate"):
            self.first_collection_date = mandate_object["firstCollectionDate"]
        if mandate_object.get("lastCollectionDate"):
            self.last_collection_date = mandate_object["lastCollectionDate"]

        # Store raw response
        self.raw_response = frappe.as_json(webhook_data)

        self.save(ignore_permissions=True)

    def execute_debit(self, amount: float, description: str, process_date: str = None):
        """
        Execute a direct debit collection on this mandate.

        Args:
            amount: Amount to collect in EUR
            description: Description for the collection
            process_date: Optional date to process (YYYY-MM-DD)

        Returns:
            dict with debit reference ID
        """
        if self.status != "Active":
            frappe.throw(_("Cannot execute debit on mandate with status: {0}").format(self.status))

        if self.mandate_type == "single":
            frappe.throw(_("Single-use mandates are processed automatically"))

        from verenigingen.verenigingen_payments.ing_checkout.client import get_client

        client = get_client()
        debit_data = {
            "mandateId": self.mandate_id,
            "amount": {
                "value": int(amount * 100),  # Convert to cents
                "currency": "EUR",
            },
            "description": description[:30] if description else "",  # Max 30 chars
        }
        if process_date:
            debit_data["processDate"] = process_date

        result = client.create_direct_debit(debit_data)

        # Update last collection date
        self.last_collection_date = process_date or today()
        self.save(ignore_permissions=True)

        return result

    def cancel(self):
        """Cancel this mandate."""
        if self.status in ["Cancelled", "Expired", "Used"]:
            frappe.throw(_("Cannot cancel mandate with status: {0}").format(self.status))

        from verenigingen.verenigingen_payments.ing_checkout.client import get_client

        try:
            client = get_client()
            client.cancel_mandate(self.mandate_id)
        except Exception as e:
            frappe.log_error(
                title="ING Checkout: Mandate cancellation failed",
                message=f"Mandate: {self.name}\nError: {str(e)}",
            )
            # Still mark as cancelled locally even if API fails
            # (mandate may already be cancelled on Pay.nl side)

        self.status = "Cancelled"
        self.save(ignore_permissions=True)


def get_or_create_mandate(
    mandate_id: str,
    mandate_type: str = "flexible",
    debtor_name: str = None,
    debtor_iban: str = None,
    debtor_email: str = None,
    amount: float = None,
    member: str = None,
) -> "INGCheckoutMandate":
    """
    Get existing mandate or create new one.

    Args:
        mandate_id: Pay.nl mandate ID
        mandate_type: Type of mandate (single, recurring, flexible)
        debtor_name: Name of the debtor
        debtor_iban: IBAN of the debtor
        debtor_email: Email of the debtor
        amount: Amount for the mandate
        member: Optional member reference

    Returns:
        INGCheckoutMandate document
    """
    if frappe.db.exists("ING Checkout Mandate", {"mandate_id": mandate_id}):
        return frappe.get_doc("ING Checkout Mandate", {"mandate_id": mandate_id})

    doc = frappe.new_doc("ING Checkout Mandate")
    doc.mandate_id = mandate_id
    doc.mandate_type = mandate_type
    doc.debtor_name = debtor_name
    doc.debtor_iban = debtor_iban
    doc.debtor_email = debtor_email
    doc.amount = amount
    doc.member = member
    doc.status = "Pending"
    doc.created_date = today()
    doc.insert(ignore_permissions=True)

    return doc
