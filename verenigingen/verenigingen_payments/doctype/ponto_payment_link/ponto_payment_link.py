# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Payment Link DocType Controller

Manages incoming payment requests (betaalverzoek) initiated through Ponto.
These are payment requests where customers authorize payments FROM their
bank account TO your organization's account.

Supports:
- One-time payment requests

NOTE: Periodic payment requests (standing orders) are NOT supported by Ponto Connect.
      For recurring payments, use SEPA Direct Debit or Mollie subscriptions.

Workflow:
1. Create payment link (Draft)
2. Submit to create payment initiation request in Ponto API (Pending Authorization)
3. Customer clicks redirect_link and authorizes at their bank (Authorized)
4. Bank executes payment (Executed)

Status Flow:
    Draft -> Pending Authorization -> Authorized -> Executed
                                   -> Rejected (if customer declines)
                                   -> Cancelled (if cancelled before authorization)
                                   -> Expired (if authorization times out)
                                   -> Failed (if execution fails)
"""

from typing import Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url

from verenigingen.utils.settings_utils import get_payments_settings


class PontoPaymentLink(Document):
    """Controller for Ponto Payment Link DocType."""

    def validate(self):
        """Validate payment link before save."""
        self.validate_currency()
        self.validate_amount()
        self.validate_creditor()
        self.validate_periodic_settings()
        self.set_defaults_from_settings()

    def before_submit(self):
        """Create payment initiation request in Ponto API before submit."""
        self.create_ponto_payment_request()

    def on_cancel(self):
        """Handle cancellation."""
        if self.status == "Pending Authorization" and self.ponto_request_id:
            self.cancel_ponto_request()
        self.status = "Cancelled"

    def validate_currency(self):
        """Ensure currency is EUR for SEPA payments."""
        if self.currency != "EUR":
            frappe.throw(
                _("Only EUR currency is supported for SEPA payments"),
                title=_("Invalid Currency"),
            )

    def validate_amount(self):
        """Ensure amount is positive."""
        if self.amount <= 0:
            frappe.throw(
                _("Payment amount must be greater than zero"),
                title=_("Invalid Amount"),
            )

    def validate_creditor(self):
        """Validate creditor (receiver) details."""
        if not self.creditor_name:
            frappe.throw(
                _("Creditor name is required"),
                title=_("Missing Creditor Name"),
            )

        if not self.creditor_iban:
            frappe.throw(
                _("Creditor IBAN is required"),
                title=_("Missing IBAN"),
            )

        # Basic IBAN format check
        iban = self.creditor_iban.replace(" ", "").upper()
        if len(iban) < 15 or not iban[:2].isalpha():
            frappe.throw(
                _("Invalid IBAN format: {0}").format(self.creditor_iban),
                title=_("Invalid IBAN"),
            )

        # Store normalized IBAN
        self.creditor_iban = iban

    def validate_periodic_settings(self):
        """Block periodic payment settings - not supported by Ponto Connect."""
        if self.payment_type == "Periodic":
            frappe.throw(
                _(
                    "Periodic payments are not supported by Ponto Connect. "
                    "For recurring payments, use SEPA Direct Debit or Mollie subscriptions."
                ),
                title=_("Feature Not Supported"),
            )

    def set_defaults_from_settings(self):
        """Set default values from Verenigingen Payments Settings."""
        if not self.creditor_name or not self.creditor_iban:
            payments_settings = get_payments_settings()

            if not self.creditor_name and payments_settings.company_account_holder:
                self.creditor_name = payments_settings.company_account_holder

            if not self.creditor_iban and payments_settings.company_iban:
                self.creditor_iban = payments_settings.company_iban.replace(" ", "").upper()

    def format_description(self, template: str = None) -> str:
        """
        Format description using template placeholders.

        Available placeholders:
        - MEMBER_ID: Member ID number
        - MEMBER_NAME: Member full name
        - COVERAGE_START: Coverage period start date
        - COVERAGE_END: Coverage period end date

        Args:
            template: Description template (uses settings default if not provided)

        Returns:
            Formatted description string
        """
        if not template:
            settings = frappe.get_single("Verenigingen Settings")
            template = (
                settings.ponto_payment_description_template
                or "Membership dues MEMBER_NAME (MEMBER_ID) - COVERAGE_START to COVERAGE_END"
            )

        result = template

        # Replace MEMBER_ID placeholder
        member_id = ""
        if self.member:
            member_id = frappe.db.get_value("Member", self.member, "member_id") or self.member
        result = result.replace("MEMBER_ID", str(member_id))

        # Replace MEMBER_NAME placeholder
        member_name = ""
        if self.member:
            member_doc = frappe.db.get_value(
                "Member",
                self.member,
                ["first_name", "tussenvoegsel", "last_name"],
                as_dict=True,
            )
            if member_doc:
                parts = [member_doc.first_name]
                if member_doc.tussenvoegsel:
                    parts.append(member_doc.tussenvoegsel)
                parts.append(member_doc.last_name)
                member_name = " ".join(filter(None, parts))
        result = result.replace("MEMBER_NAME", member_name)

        # Replace coverage date placeholders from Sales Invoice
        coverage_start = ""
        coverage_end = ""
        if self.sales_invoice:
            invoice_data = frappe.db.get_value(
                "Sales Invoice",
                self.sales_invoice,
                ["from_date", "to_date"],
                as_dict=True,
            )
            if invoice_data:
                if invoice_data.from_date:
                    coverage_start = frappe.utils.formatdate(invoice_data.from_date, "dd-MM-yyyy")
                if invoice_data.to_date:
                    coverage_end = frappe.utils.formatdate(invoice_data.to_date, "dd-MM-yyyy")

        result = result.replace("COVERAGE_START", coverage_start)
        result = result.replace("COVERAGE_END", coverage_end)

        return result.strip()

    def create_ponto_payment_request(self):
        """
        Create payment initiation request in Ponto API.

        Called during submit. Updates document with Ponto request ID
        and redirect link for customer authorization.
        """
        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            get_betaalverzoek_client,
        )

        # Format description using template
        formatted_description = self.description
        if self.member or self.sales_invoice:
            formatted_description = self.format_description(self.description)

        # Build redirect URI for callback
        callback_url = get_url(
            f"/api/method/verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback.payment_link_callback"
            f"?payment_link={self.name}"
        )

        try:
            client = get_betaalverzoek_client()

            # Create one-time payment request (periodic not supported by Ponto Connect)
            result = client.create_payment_request(
                amount=float(self.amount),
                creditor_name=self.creditor_name,
                creditor_iban=self.creditor_iban,
                remittance_info=formatted_description,
                redirect_uri=callback_url,
                end_to_end_id=self.name,
            )

            # Update document with Ponto response
            self.ponto_request_id = result.id
            self.redirect_link = result.redirect_link
            self.status = "Pending Authorization"

            frappe.msgprint(
                _(
                    "Payment link created. Share the authorization link with the customer, "
                    "or use the payment link page."
                ),
                indicator="blue",
                alert=True,
            )

        except Exception as e:
            frappe.log_error(
                title="Ponto payment link creation failed",
                message=str(e),
            )
            frappe.throw(
                _("Failed to create payment link in Ponto: {0}").format(str(e)),
                title=_("Ponto API Error"),
            )

    def cancel_ponto_request(self):
        """
        Cancel/delete payment request in Ponto API.

        Only works for unauthorized requests.
        """
        if not self.ponto_request_id:
            return

        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            get_betaalverzoek_client,
        )

        try:
            client = get_betaalverzoek_client()
            client.delete_payment_request(self.ponto_request_id)
            frappe.logger().info(f"Cancelled Ponto payment request {self.ponto_request_id}")
        except Exception as e:
            frappe.logger().warning(f"Failed to cancel Ponto payment request {self.ponto_request_id}: {e}")
            # Don't throw - the request may already be authorized or executed

    @frappe.whitelist()
    def refresh_status(self):
        """
        Refresh payment link status from Ponto API.

        Called from UI button or scheduled job.
        """
        if not self.ponto_request_id:
            frappe.throw(
                _("No Ponto request ID to refresh"),
                title=_("Cannot Refresh"),
            )

        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            get_betaalverzoek_client,
        )

        try:
            client = get_betaalverzoek_client()
            request = client.get_payment_request(self.ponto_request_id)

            # Map Ponto status to our status
            # Note: Ponto API doesn't return a 'status' field - we infer it from
            # signedAt/closedAt timestamps in betaalverzoek_client.from_api_response()
            status_map = {
                "pending": "Pending Authorization",
                "unsigned": "Pending Authorization",
                "signed": "Authorized",
                "authorized": "Authorized",
                "closed": "Executed",  # closedAt is set when payment reaches final state
                "executed": "Executed",
                "rejected": "Rejected",
                "failed": "Failed",
                "expired": "Expired",
            }

            new_status = status_map.get(request.status.lower(), self.status)

            if new_status != self.status:
                self.status = new_status
                self.save()
                frappe.msgprint(
                    _("Status updated to {0}").format(new_status),
                    indicator="green",
                    alert=True,
                )

                # If executed, create Payment Entry
                if new_status == "Executed":
                    self.process_payment_received()

            # Update debtor info if available
            if hasattr(request, "debtor_name") and request.debtor_name:
                self.debtor_name = request.debtor_name
            if hasattr(request, "debtor_iban") and request.debtor_iban:
                self.debtor_iban = request.debtor_iban
            if hasattr(request, "debtor_bank") and request.debtor_bank:
                self.debtor_bank = request.debtor_bank

            self.save()

            return {"status": new_status}

        except Exception as e:
            frappe.log_error(
                title=f"Ponto payment link status refresh failed: {self.name}",
                message=str(e),
            )
            frappe.throw(
                _("Failed to refresh status: {0}").format(str(e)),
                title=_("API Error"),
            )

    def process_payment_received(self):
        """
        Process received payment.

        Creates Payment Entry and marks linked Sales Invoice as paid.
        """
        if self.payment_entry:
            return  # Already processed

        # Determine company
        settings = frappe.get_single("Verenigingen Settings")
        company = settings.company

        # Get bank account from creditor_account or settings
        bank_account = self.creditor_account
        if not bank_account:
            # Try to find from Ponto Settings
            ponto_settings = frappe.get_single("Ponto Settings")
            for mapping in ponto_settings.bank_account_mappings:
                if mapping.enabled:
                    bank_account = mapping.bank_account
                    break

        # Determine party from member or reference
        party_type = "Customer"
        party = None

        if self.member:
            # Get customer linked to member
            party = frappe.db.get_value("Member", self.member, "customer")

        if not party and self.reference_doctype == "Customer":
            party = self.reference_name

        if not party and self.sales_invoice:
            party = frappe.db.get_value("Sales Invoice", self.sales_invoice, "customer")

        if not party:
            frappe.logger().warning(f"Cannot determine party for Ponto Payment Link {self.name}")
            return

        # Create Payment Entry
        try:
            pe = frappe.new_doc("Payment Entry")
            pe.payment_type = "Receive"
            pe.company = company
            pe.mode_of_payment = "Bank Transfer"
            pe.party_type = party_type
            pe.party = party
            pe.paid_from_account_currency = self.currency
            pe.paid_to_account_currency = self.currency
            pe.paid_amount = self.amount
            pe.received_amount = self.amount
            pe.reference_no = self.name
            pe.reference_date = frappe.utils.today()

            if bank_account:
                pe.bank_account = bank_account

            # Link to Sales Invoice if available
            if self.sales_invoice:
                pe.append(
                    "references",
                    {
                        "reference_doctype": "Sales Invoice",
                        "reference_name": self.sales_invoice,
                        "total_amount": frappe.db.get_value(
                            "Sales Invoice", self.sales_invoice, "grand_total"
                        ),
                        "allocated_amount": self.amount,
                    },
                )

            pe.insert()
            pe.submit()

            self.payment_entry = pe.name
            self.save()

            frappe.logger().info(f"Created Payment Entry {pe.name} for Ponto Payment Link {self.name}")

        except Exception as e:
            frappe.log_error(
                title=f"Failed to create Payment Entry for {self.name}",
                message=str(e),
            )

    def update_status_from_webhook(self, new_status: str, debtor_info: dict = None):
        """
        Update status from webhook event.

        Args:
            new_status: New status value
            debtor_info: Optional dict with debtor details from webhook
        """
        if new_status != self.status:
            self.status = new_status

            # Update debtor info if provided
            if debtor_info:
                if debtor_info.get("name"):
                    self.debtor_name = debtor_info["name"]
                if debtor_info.get("iban"):
                    self.debtor_iban = debtor_info["iban"]
                if debtor_info.get("bank"):
                    self.debtor_bank = debtor_info["bank"]

            # SECURITY JUSTIFICATION: Webhook callbacks execute in a system context without
            # user session. Permission bypass is acceptable because:
            # 1. Webhook signature is verified before this method is called
            # 2. This only updates status/debtor info on a document already created by user
            # 3. Full audit trail is logged below
            frappe.logger("security").info(
                f"Webhook status update: Ponto Payment Link {self.name} "
                f"status changed from {frappe.db.get_value('Ponto Payment Link', self.name, 'status')} "
                f"to {new_status} (debtor: {debtor_info.get('name') if debtor_info else 'N/A'})"
            )
            self.save(ignore_permissions=True)

            if new_status == "Executed":
                self.process_payment_received()

            frappe.logger().info(f"Ponto Payment Link {self.name} status updated to {new_status} via webhook")

    def increment_payment_count(self):
        """Increment total payments collected for periodic payments."""
        if self.payment_type == "Periodic":
            self.total_payments_collected = (self.total_payments_collected or 0) + 1
            self.save(ignore_permissions=True)

    @frappe.whitelist()
    def get_payment_url(self):
        """
        Get the customer-facing payment URL.

        Returns a URL that can be shared with the customer to initiate payment.
        """
        return get_url(f"/ponto-pay/{self.name}")

    @frappe.whitelist()
    def send_payment_link(self, email: str = None):
        """
        Send the payment link to the customer via email.

        Args:
            email: Email address to send to (uses member email if not provided)
        """
        if not email and self.member:
            email = frappe.db.get_value("Member", self.member, "email_id")

        if not email:
            frappe.throw(
                _("No email address provided"),
                title=_("Cannot Send"),
            )

        payment_url = self.redirect_link or self.get_payment_url()

        # Send email using EmailService for UI-controllable notifications
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()
        context = {
            "member_name": "Dear Customer",
            "notification_message": f"You have received a payment request for {self.amount} EUR.",
            "payment_reference": self.name,
            "amount": f"€{self.amount}",
            "payment_date": str(frappe.utils.today()),
            "payment_method": "Ponto Payment Link",
            "action_required": f"Description: {self.description}\n\nPlease click the following link to authorize the payment:\n{payment_url}",
            "next_steps": f"This payment request was created by {self.creditor_name}.",
            "company": self.creditor_name,
        }

        email_service.send_templated_email(
            template_name="payment_notification",
            recipients=[email],
            context=context,
            subject_override=_("Payment Request - {0}").format(self.creditor_name),
            reference_doctype=self.doctype,
            reference_name=self.name,
            notification_key="ponto_payment_link_request",
        )

        frappe.msgprint(
            _("Payment link sent to {0}").format(email),
            indicator="green",
            alert=True,
        )
