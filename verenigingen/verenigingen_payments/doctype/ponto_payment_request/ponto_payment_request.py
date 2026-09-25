# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Payment Request DocType Controller

Manages SEPA payment requests initiated through Ponto.

Workflow:
1. Create payment request (Draft)
2. Submit to create payment in Ponto API (Pending)
3. User signs payment in Ponto portal (Signed)
4. Bank executes payment (Executed)

Status Flow:
    Draft -> Pending -> Signed -> Executed
                    -> Rejected (if signing fails)
                    -> Cancelled (if cancelled before signing)
                    -> Failed (if execution fails)
"""

from contextlib import contextmanager
from datetime import date
from typing import Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS, rollback_to_savepoint


class PontoPaymentRequest(Document):
    """Controller for Ponto Payment Request DocType."""

    def validate(self):
        """Validate payment request before save."""
        self.validate_currency()
        self.validate_amount()
        self.validate_iban()
        self.set_ponto_account_name()

    def before_submit(self):
        """Create payment request in Ponto API before submit."""
        self.create_ponto_payment()

    def on_cancel(self):
        """Handle cancellation."""
        if self.status == "Pending" and self.ponto_payment_id:
            self.cancel_ponto_payment()
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

    def validate_iban(self):
        """Basic IBAN validation."""
        if not self.creditor_iban:
            frappe.throw(
                _("Creditor IBAN is required"),
                title=_("Missing IBAN"),
            )

        # Basic format check (should start with 2 letters)
        iban = self.creditor_iban.replace(" ", "").upper()
        if len(iban) < 15 or not iban[:2].isalpha():
            frappe.throw(
                _("Invalid IBAN format: {0}").format(self.creditor_iban),
                title=_("Invalid IBAN"),
            )

        # Store normalized IBAN
        self.creditor_iban = iban

    def set_ponto_account_name(self):
        """Set the Ponto account display name from settings."""
        if self.ponto_account and not self.ponto_account_name:
            settings = frappe.get_single("Ponto Settings")
            for mapping in settings.bank_account_mappings:
                if mapping.ponto_account_id == self.ponto_account:
                    self.ponto_account_name = mapping.ponto_account_name or mapping.ponto_iban
                    break

    def create_ponto_payment(self):
        """
        Create payment request in Ponto API.

        Called during submit. Updates document with Ponto payment ID
        and redirect link for authorization.
        """
        from verenigingen.verenigingen_payments.ponto.clients.payment_client import get_payment_client

        # Build redirect URI for callback
        redirect_uri = self.redirect_uri
        if not redirect_uri:
            redirect_uri = get_url(
                f"/api/method/verenigingen.verenigingen_payments.ponto.api.payment_callback"
                f"?payment_request={self.name}"
            )

        # Parse execution date if set
        exec_date = None
        if self.requested_execution_date:
            exec_date = self.requested_execution_date

        try:
            client = get_payment_client()
            payment = client.create_payment(
                account_id=self.ponto_account,
                amount=float(self.amount),
                currency=self.currency,
                creditor_name=self.creditor_name,
                creditor_iban=self.creditor_iban,
                remittance_info=self.remittance_info,
                redirect_uri=redirect_uri,
                creditor_bic=self.creditor_bic or None,
                requested_execution_date=exec_date,
                end_to_end_id=self.name,
            )

            # Update document with Ponto response
            self.ponto_payment_id = payment.id
            self.redirect_link = payment.redirect_link
            self.status = "Pending"

            frappe.msgprint(
                _("Payment request created in Ponto. " "Click the authorization link to sign the payment."),
                indicator="blue",
                alert=True,
            )

        except Exception as e:
            frappe.log_error(
                title="Ponto payment creation failed",
                message=str(e),
            )
            frappe.throw(
                _("Failed to create payment in Ponto: {0}").format(str(e)),
                title=_("Ponto API Error"),
            )

    def cancel_ponto_payment(self):
        """
        Cancel/delete payment request in Ponto API.

        Only works for unsigned payments.
        """
        if not self.ponto_payment_id:
            return

        from verenigingen.verenigingen_payments.ponto.clients.payment_client import get_payment_client

        try:
            client = get_payment_client()
            client.delete_payment(
                account_id=self.ponto_account,
                payment_id=self.ponto_payment_id,
            )
            frappe.logger().info(f"Cancelled Ponto payment {self.ponto_payment_id}")
        except Exception as e:
            frappe.logger().warning(f"Failed to cancel Ponto payment {self.ponto_payment_id}: {e}")
            # Don't throw - the payment may already be signed or executed

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.FINANCIAL)
    def refresh_status(self):
        """
        Refresh payment status from Ponto API.

        Called from UI button or scheduled job.
        """
        if not self.ponto_payment_id:
            frappe.throw(
                _("No Ponto payment ID to refresh"),
                title=_("Cannot Refresh"),
            )

        from verenigingen.verenigingen_payments.ponto.clients.payment_client import get_payment_client

        try:
            client = get_payment_client()
            payment = client.get_payment(
                account_id=self.ponto_account,
                payment_id=self.ponto_payment_id,
            )

            # Map Ponto status to our status
            status_map = {
                "pending": "Pending",
                "unsigned": "Pending",
                "signed": "Signed",
                "executed": "Executed",
                "rejected": "Rejected",
                "failed": "Failed",
            }

            new_status = status_map.get(payment.status.lower(), self.status)

            if new_status != self.status:
                # Status + Payment Entry are one atomic unit -- #1323 (#1288 class).
                # See _atomic_status_transition() for why.
                with self._atomic_status_transition():
                    self.status = new_status
                    self.save()

                    # If executed, create Payment Entry
                    if new_status == "Executed":
                        self.create_payment_entry()

                frappe.msgprint(
                    _("Status updated to {0}").format(new_status),
                    indicator="green",
                    alert=True,
                )

            return {"status": new_status}

        except Exception as e:
            frappe.log_error(
                title=f"Ponto status refresh failed: {self.name}",
                message=str(e),
            )
            frappe.throw(
                _("Failed to refresh status: {0}").format(str(e)),
                title=_("API Error"),
            )

    @contextmanager
    def _atomic_status_transition(self):
        """
        Scope a status mutation and any Payment Entry it triggers as one atomic
        unit -- #1323, the #1288 class of defect. Both ``refresh_status()`` and
        ``update_status_from_webhook()`` used to persist the new status (e.g.
        "Executed") BEFORE calling ``create_payment_entry()``, which then
        swallowed its own exception (log_error, no re-raise). Any PE failure
        therefore left the request permanently stuck at "Executed" with no
        Payment Entry and no automatic retry -- the status said the money had
        moved when it had not.

        A savepoint scopes the status mutation and the PE creation together: on
        any failure both roll back to how the document was before this call,
        and the exception propagates so the caller (the outer try/except in
        refresh_status(), or the per-row savepoint in
        webhook_handlers.handle_payment_request_closed()) sees the failure and
        can retry. A retry re-enters the same "new_status != self.status" gate
        both callers already use before this transition, and
        create_payment_entry()'s own "already have self.payment_entry" guard
        still applies -- so a retry cannot double-create a Payment Entry for a
        prior COMMITTED success. The rollback here is what guarantees a failed
        attempt never becomes one.
        """
        savepoint = f"ppr_status_pe_{frappe.generate_hash(length=10)}"
        frappe.db.savepoint(savepoint)
        try:
            yield
        except NON_RESUMABLE_DB_ERRORS:
            # A 1213/1205 has already destroyed (1213) or half-applied (1205) the
            # transaction server-side; ROLLBACK TO SAVEPOINT here would raise 1305
            # and replace this error instead of propagating it.
            raise
        except Exception:
            rollback_to_savepoint(savepoint)
            raise
        else:
            frappe.db.release_savepoint(savepoint)

    def create_payment_entry(self):
        """
        Create Payment Entry when payment is executed.

        Links the Payment Entry to this Ponto Payment Request.

        Every guard below RAISES rather than logging-and-returning (#1323
        review finding): each one runs inside the caller's
        _atomic_status_transition() savepoint, and a plain ``return`` exits
        that ``with`` block normally, releasing the savepoint -- so "Executed"
        was committed with no Payment Entry and no error trail for exactly
        the four misconfigurations this method already knew how to detect.
        `frappe.logger().warning()` in particular writes to a rotating file
        handler nothing in CI reads (see CLAUDE.md's "Known traps"), so this
        was invisible even to a diligent operator.

        The one exception is ``if self.payment_entry: return`` immediately
        below -- that is a genuine idempotency no-op (already succeeded),
        not a misconfiguration, and stays a silent return.
        """
        if self.payment_entry:
            return  # Already created

        # Get company and bank account from Ponto settings
        settings = frappe.get_single("Ponto Settings")
        bank_account = None
        for mapping in settings.bank_account_mappings:
            if mapping.ponto_account_id == self.ponto_account:
                bank_account = mapping.bank_account
                break

        if not bank_account:
            frappe.throw(
                _(
                    "No bank account is mapped for Ponto account {0} in Ponto Settings. "
                    "Configure a bank account mapping before this payment can be recorded."
                ).format(self.ponto_account),
                title=_("Ponto Account Not Mapped"),
            )

        # Get company from bank account
        company = frappe.db.get_value("Bank Account", bank_account, "company")
        if not company:
            frappe.throw(
                _(
                    "Bank Account {0} (mapped to Ponto account {1}) has no Company set. "
                    "Cannot create a Payment Entry without a company."
                ).format(bank_account, self.ponto_account),
                title=_("Bank Account Misconfigured"),
            )

        # paid_from: the GL account behind the Ponto-mapped Bank Account this SEPA
        # payment is debited from. `bank_account` above is a reconciliation-only
        # Link(Bank Account) field on Payment Entry -- it is NOT paid_from, which is
        # a Link(Account) -- #1200.
        paid_from = frappe.db.get_value("Bank Account", bank_account, "account")
        if not paid_from:
            frappe.throw(
                _(
                    "Bank Account {0} (mapped to Ponto account {1}) has no linked GL Account. "
                    "Cannot create a Payment Entry without one."
                ).format(bank_account, self.ponto_account),
                title=_("Bank Account Misconfigured"),
            )

        # Determine party type and party from reference
        party_type = None
        party = None

        if self.reference_doctype and self.reference_name:
            if self.reference_doctype == "Supplier":
                party_type = "Supplier"
                party = self.reference_name
            elif self.reference_doctype == "Employee":
                party_type = "Employee"
                party = self.reference_name
            # Could add more mappings as needed

        # paid_to: for payment_type "Pay", ERPNext needs the PARTY's own
        # Payable/Advance account here (Payment Entry.setup_party_account_field:
        # for Pay, party_account = paid_to) -- #1200, the same missing-field shape
        # as #906. Resolved with ERPNext's own get_party_account(), the same
        # resolver its get_payment_entry() factory uses. Without a party there is
        # no established account to post the other side of this SEPA payment to
        # (this construction never set paid_from/paid_to at all before, so no case
        # ever posted correctly) -- refuse rather than guess, matching the
        # no-bank_account / no-company guards already above.
        if not (party_type and party):
            frappe.throw(
                _(
                    "Ponto Payment Request {0} has no reference Supplier or Employee, so no "
                    "payable account can be resolved for the Payment Entry."
                ).format(self.name),
                title=_("No Reference Party"),
            )

        from erpnext.accounts.party import get_party_account

        paid_to = get_party_account(party_type, party, company)

        # Create Payment Entry. Does NOT swallow its own exception (#1323, the
        # #1288 class): a caller (refresh_status(), update_status_from_webhook())
        # must see a failure here so its own savepoint (_atomic_status_transition)
        # can roll back the status mutation it made just before this call --
        # logging and returning silently left the request stuck "Executed" with
        # no Payment Entry and no retry.
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Pay"
        pe.company = company
        pe.party_type = party_type
        pe.party = party
        pe.paid_from = paid_from
        pe.paid_to = paid_to
        pe.mode_of_payment = "Bank Transfer"
        pe.paid_from_account_currency = self.currency
        pe.paid_to_account_currency = self.currency
        pe.paid_amount = self.amount
        pe.received_amount = self.amount
        pe.reference_no = self.name
        pe.reference_date = frappe.utils.today()
        pe.bank_account = bank_account

        pe.insert()
        pe.submit()

        self.payment_entry = pe.name
        self.save()

        frappe.logger().info(f"Created Payment Entry {pe.name} for Ponto payment {self.name}")

    def update_status_from_webhook(self, new_status: str):
        """
        Update status from webhook event.

        Args:
            new_status: New status value
        """
        if new_status != self.status:
            # Status + Payment Entry are one atomic unit -- #1323 (#1288 class).
            # See _atomic_status_transition() for why.
            with self._atomic_status_transition():
                self.status = new_status
                # Security: Webhook callback - status update from verified Ponto event
                self.save(ignore_permissions=True)

                if new_status == "Executed":
                    self.create_payment_entry()

            frappe.logger().info(
                f"Ponto Payment Request {self.name} status updated to {new_status} via webhook"
            )
