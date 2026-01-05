# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.utils.security.api_security_framework import OperationType, critical_api
from verenigingen.utils.validation.iban_validator import validate_iban


class VerenigingenPaymentsSettings(Document):
    def validate(self):
        """Validate payment settings configuration"""
        self._validate_webhook_user()
        self._validate_sepa_configuration()
        self._validate_ing_checkout_configuration()

    def _validate_webhook_user(self):
        """Validate webhook user has appropriate role and security requirements"""
        if not self.webhook_user:
            return

        # Check if user exists
        if not frappe.db.exists("User", self.webhook_user):
            frappe.throw(_("User {0} does not exist").format(self.webhook_user))

        user_doc = frappe.get_doc("User", self.webhook_user)

        # Check if user has required role
        webhook_role_assigned = any(role.role == "Verenigingen Webhook User" for role in user_doc.roles)

        if not webhook_role_assigned:
            frappe.throw(
                _(
                    "User {0} must have the 'Verenigingen Webhook User' role assigned. "
                    "This role is required for webhook operations and provides minimal security permissions."
                ).format(self.webhook_user)
            )

        # Security validation: ensure webhook user is not Administrator
        if self.webhook_user == "Administrator":
            frappe.throw(
                _(
                    "Administrator account cannot be used as webhook user. "
                    "Please create a dedicated webhook user account with 'Verenigingen Webhook User' role for security."
                )
            )

        # Ensure user doesn't have excessive permissions
        user_roles = [role.role for role in user_doc.roles]
        dangerous_roles = ["System Manager", "Administrator", "All"]
        has_dangerous_roles = any(role in dangerous_roles for role in user_roles)

        if has_dangerous_roles:
            frappe.throw(
                _(
                    "Security violation: Webhook user {0} has excessive permissions ({1}). "
                    "Webhook users should only have the 'Verenigingen Webhook User' role for security."
                ).format(self.webhook_user, ", ".join([r for r in user_roles if r in dangerous_roles]))
            )

    def _validate_sepa_configuration(self):
        """Validate SEPA Direct Debit configuration"""
        if self.enable_sepa_direct_debit:
            if not self.company_iban:
                frappe.throw(_("Company IBAN is required when SEPA Direct Debit is enabled"))
            if not self.creditor_id:
                frappe.throw(_("SEPA Creditor ID is required when SEPA Direct Debit is enabled"))

        # Validate creditor ID format if provided
        if self.creditor_id:
            creditor_id = self.creditor_id.replace(" ", "").upper()
            if len(creditor_id) < 8 or len(creditor_id) > 35:
                frappe.msgprint(
                    _(
                        "SEPA Creditor ID should be between 8 and 35 characters. "
                        "Dutch format: NL + 2 check digits + ZZZ + up to 11 alphanumeric chars."
                    ),
                    indicator="yellow",
                )

        # Validate IBAN format if provided (uses comprehensive mod-97 checksum validation)
        if self.company_iban:
            result = validate_iban(self.company_iban)
            if not result.get("valid"):
                frappe.throw(_("Invalid Company IBAN: {0}").format(result.get("message")))

    def _validate_ing_checkout_configuration(self):
        """Validate ING Checkout (Pay.nl) configuration"""
        # Check if ING Checkout is enabled (via ING Checkout Settings)
        ing_checkout_enabled = False
        try:
            ing_settings = frappe.get_single("ING Checkout Settings")
            ing_checkout_enabled = ing_settings.enabled
        except Exception:
            pass

        if not ing_checkout_enabled:
            return

        # Validate bank account is configured when ING Checkout is enabled
        if not self.ing_checkout_bank_account:
            frappe.msgprint(
                _(
                    "Warning: ING Checkout Bank Account is not configured. "
                    "Payment Entry creation will fail until this is set."
                ),
                indicator="orange",
            )
            return

        # Validate bank account exists
        if not frappe.db.exists("Account", self.ing_checkout_bank_account):
            frappe.throw(
                _("ING Checkout Bank Account '{0}' does not exist").format(self.ing_checkout_bank_account)
            )

        # Validate it's a bank-type account
        account_type = frappe.db.get_value("Account", self.ing_checkout_bank_account, "account_type")
        if account_type != "Bank":
            frappe.throw(
                _("ING Checkout Bank Account must be a Bank type account. " "'{0}' is type '{1}'.").format(
                    self.ing_checkout_bank_account, account_type
                )
            )

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def generate_webhook_secret(self, field="membership_webhook_secret"):
        """Generate a new webhook secret for API authentication"""
        key = frappe.generate_hash(length=20)
        self.set(field, key)
        self.save()

        frappe.msgprint(
            _("Here is your webhook secret for Membership API. This will be shown to you only once.")
            + "<br><br>"
            + key,
            _("Webhook Secret"),
        )

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def revoke_key(self, key):
        """Revoke a webhook secret"""
        self.set(key, None)
        self.save()

    def get_webhook_secret(self, endpoint="Membership"):
        """Get the webhook secret for API authentication"""
        fieldname = "membership_webhook_secret"
        return self.get_password(fieldname=fieldname, raise_exception=False)
