# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Mandate Service for ING Checkout SEPA Direct Debit

Provides high-level operations for mandate lifecycle management:
- Creating mandates for members
- Linking to existing SEPA mandates
- Executing debits on mandates
- Mandate status synchronization
"""

from typing import Optional

import frappe
from frappe import _
from frappe.utils import get_url, today


class MandateService:
    """
    Service for managing ING Checkout SEPA Direct Debit mandates.

    Provides business logic for:
    - Creating mandates from member data
    - Synchronizing mandate status with Pay.nl
    - Executing direct debits
    - Linking to ERPNext SEPA Mandates
    """

    def __init__(self):
        """Initialize the mandate service."""
        self._client = None
        self._settings = None

    @property
    def client(self):
        """Lazy load Pay.nl client."""
        if self._client is None:
            from verenigingen.verenigingen_payments.ing_checkout.client import get_client

            self._client = get_client()
        return self._client

    @property
    def settings(self):
        """Lazy load settings."""
        if self._settings is None:
            from verenigingen.verenigingen_payments.doctype.ing_checkout_settings.ing_checkout_settings import (
                get_ing_checkout_settings,
            )

            self._settings = get_ing_checkout_settings()
        return self._settings

    def create_mandate_for_member(
        self,
        member_name: str,
        mandate_type: str = "flexible",
        amount: float = None,
        description: str = None,
    ) -> dict:
        """
        Create a SEPA Direct Debit mandate for a member.

        Args:
            member_name: Member document name
            mandate_type: Type of mandate (single, recurring, flexible)
            amount: Optional amount for single/recurring mandates
            description: Optional description

        Returns:
            dict with success status and mandate info
        """
        member = frappe.get_doc("Member", member_name)

        # Get member's SEPA details
        sepa_mandate = self._get_member_sepa_mandate(member)
        if not sepa_mandate:
            return {
                "success": False,
                "error": _("Member has no active SEPA mandate with IBAN"),
            }

        # Build mandate data for Pay.nl
        mandate_data = {
            "serviceId": self.settings.service_id,
            "type": mandate_type,
            "description": description or f"Mandate for {member.full_name}"[:30],
            "debtor": {
                "iban": sepa_mandate.iban,
                "name": sepa_mandate.account_holder_name or member.full_name,
                "email": member.email or "",
            },
            "termsAndConditionsUrl": self.settings.terms_and_conditions_url or get_url("/terms"),
            "exchangeUrl": self._get_webhook_url("mandate"),
        }

        if amount:
            mandate_data["amount"] = {
                "value": int(amount * 100),
                "currency": "EUR",
            }

        try:
            # Create mandate via Pay.nl
            result = self.client.create_mandate(mandate_data)
            mandate_id = result.get("mandateId") or result.get("id")

            if not mandate_id:
                return {
                    "success": False,
                    "error": _("No mandate ID returned from Pay.nl"),
                }

            # Create local mandate record
            from verenigingen.verenigingen_payments.doctype.ing_checkout_mandate.ing_checkout_mandate import (
                get_or_create_mandate,
            )

            mandate_doc = get_or_create_mandate(
                mandate_id=mandate_id,
                mandate_type=mandate_type,
                debtor_name=sepa_mandate.account_holder_name or member.full_name,
                debtor_iban=sepa_mandate.iban,
                debtor_email=member.email,
                amount=amount,
                member=member_name,
            )

            # Link to SEPA mandate if exists
            mandate_doc.sepa_mandate = sepa_mandate.name
            mandate_doc.terms_url = mandate_data["termsAndConditionsUrl"]
            mandate_doc.raw_response = frappe.as_json(result)
            # SECURITY JUSTIFICATION: MandateService is a system service called from
            # API endpoints that already validate user permissions. Mandate data comes
            # from Pay.nl API response which was initiated by an authorized user action.
            mandate_doc.save(ignore_permissions=True)

            return {
                "success": True,
                "mandate_id": mandate_id,
                "mandate_name": mandate_doc.name,
                "status": mandate_doc.status,
            }

        except Exception as e:
            frappe.log_error(
                title="ING Checkout: Mandate creation failed",
                message=f"Member: {member_name}\nError: {str(e)}",
            )
            return {
                "success": False,
                "error": str(e),
            }

    def execute_debit_for_invoice(
        self,
        mandate_name: str,
        sales_invoice: str,
        process_date: str = None,
    ) -> dict:
        """
        Execute a direct debit for a Sales Invoice using a mandate.

        Args:
            mandate_name: ING Checkout Mandate document name
            sales_invoice: Sales Invoice document name
            process_date: Optional date to process (YYYY-MM-DD)

        Returns:
            dict with success status and debit reference
        """
        mandate = frappe.get_doc("ING Checkout Mandate", mandate_name)
        invoice = frappe.get_doc("Sales Invoice", sales_invoice)

        if mandate.status != "Active":
            return {
                "success": False,
                "error": _("Mandate is not active"),
            }

        if invoice.outstanding_amount <= 0:
            return {
                "success": False,
                "error": _("Invoice has no outstanding amount"),
            }

        try:
            result = mandate.execute_debit(
                amount=invoice.outstanding_amount,
                description=f"{invoice.name}"[:30],
                process_date=process_date,
            )

            reference_id = result.get("referenceId") or result.get("id")

            # Create transaction record to track this debit
            from verenigingen.verenigingen_payments.doctype.ing_checkout_transaction.ing_checkout_transaction import (
                get_or_create_transaction,
            )

            transaction = get_or_create_transaction(
                transaction_id=reference_id,
                reference_doctype="Sales Invoice",
                reference_name=sales_invoice,
                amount=invoice.outstanding_amount,
                payment_method="Direct Debit",
            )

            return {
                "success": True,
                "reference_id": reference_id,
                "transaction_name": transaction.name,
                "process_date": process_date or today(),
            }

        except Exception as e:
            frappe.log_error(
                title="ING Checkout: Direct debit execution failed",
                message=f"Mandate: {mandate_name}\nInvoice: {sales_invoice}\nError: {str(e)}",
            )
            return {
                "success": False,
                "error": str(e),
            }

    def sync_mandate_status(self, mandate_name: str) -> dict:
        """
        Synchronize mandate status with Pay.nl.

        Args:
            mandate_name: ING Checkout Mandate document name

        Returns:
            dict with updated status
        """
        mandate = frappe.get_doc("ING Checkout Mandate", mandate_name)

        try:
            result = self.client.get_mandate(mandate.mandate_id)

            status = result.get("status", "").lower()
            from verenigingen.verenigingen_payments.doctype.ing_checkout_mandate.ing_checkout_mandate import (
                MANDATE_STATUS_MAP,
            )

            if status in MANDATE_STATUS_MAP:
                old_status = mandate.status
                mandate.status = MANDATE_STATUS_MAP[status]
                mandate.raw_response = frappe.as_json(result)
                # SECURITY JUSTIFICATION: Status sync is a system operation triggered
                # by authorized API call. Status data comes from Pay.nl API which
                # has been validated. Audit trail via mandate document.
                mandate.save(ignore_permissions=True)

                return {
                    "success": True,
                    "old_status": old_status,
                    "new_status": mandate.status,
                    "changed": old_status != mandate.status,
                }

            return {
                "success": True,
                "status": mandate.status,
                "changed": False,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def get_active_mandates_for_member(self, member_name: str) -> list:
        """
        Get all active mandates for a member.

        Args:
            member_name: Member document name

        Returns:
            list of active mandate documents
        """
        return frappe.get_all(
            "ING Checkout Mandate",
            filters={
                "member": member_name,
                "status": "Active",
            },
            fields=["name", "mandate_id", "mandate_type", "debtor_iban", "created_date"],
        )

    def _get_member_sepa_mandate(self, member) -> Optional["SEPAMandate"]:
        """Get the member's active SEPA mandate with IBAN."""
        if not member.sepa_mandate:
            return None

        sepa = frappe.get_doc("SEPA Mandate", member.sepa_mandate)
        if sepa.status != "Active" or not sepa.iban:
            return None

        return sepa

    def _get_webhook_url(self, webhook_type: str) -> str:
        """Get the webhook URL for a specific type."""
        base_url = get_url()
        webhook_methods = {
            "mandate": "verenigingen.verenigingen_payments.ing_checkout.api.webhook.handle_mandate",
            "direct_debit": "verenigingen.verenigingen_payments.ing_checkout.api.webhook.handle_direct_debit",
        }
        method = webhook_methods.get(webhook_type, webhook_methods["mandate"])
        return f"{base_url}/api/method/{method}"


def get_mandate_service() -> MandateService:
    """Get a MandateService instance."""
    return MandateService()
