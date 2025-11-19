# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from payments.utils import get_payment_gateway_controller

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


class VerenigingenSettings(Document):
    def validate(self):
        self.validate_donation_accounts()
        self.validate_grace_period_settings()  # Moved from hooks.py
        self.validate_chapter_dues_accounts()

    def validate_donation_accounts(self):
        """Validate donation account configuration"""
        if self.automate_donation_payment_entries:
            if not self.donations_gl_account:
                frappe.throw(_("Donations GL Account is required when automating donation payment entries"))
            if not self.donation_debit_account:
                frappe.throw(_("Donation Debit Account is required when automating donation payment entries"))

        # Validate that earmarked accounts are different from main donation account
        if self.campaign_donation_account and self.campaign_donation_account == self.donations_gl_account:
            frappe.msgprint(
                _(
                    "Campaign Donation Account should be different from main Donations GL Account for proper fund segregation"
                ),
                indicator="yellow",
            )

        if self.restricted_donation_account and self.restricted_donation_account == self.donations_gl_account:
            frappe.msgprint(
                _(
                    "Restricted Donation Account should be different from main Donations GL Account for proper fund segregation"
                ),
                indicator="yellow",
            )

    def validate_grace_period_settings(self):
        """Validation for grace period settings (moved from hooks.py)"""
        # Validate grace period settings
        if self.default_grace_period_days:
            if self.default_grace_period_days < 1 or self.default_grace_period_days > 180:
                frappe.throw(_("Default grace period days must be between 1 and 180 days"))

        if self.grace_period_notification_days:
            if self.grace_period_notification_days < 1 or self.grace_period_notification_days > 30:
                frappe.throw(_("Grace period notification days must be between 1 and 30 days"))

    def validate_chapter_dues_accounts(self):
        """Validate chapter dues allocation account configuration"""
        # Check if any allocation accounts are configured
        has_chapter_account = getattr(self, "chapter_dues_income_account", None)
        has_national_account = getattr(self, "national_dues_income_account", None)
        has_source_account = getattr(self, "dues_income_account", None)

        # Source account is always required for dues functionality
        if not has_source_account:
            frappe.throw(_("Dues Income Account (source) is required"))

        # Chapter and national accounts are optional - if not set, dues_income_account is used
        # No validation needed for optional accounts

        # Validate accounts are different if both optional accounts are configured
        if has_chapter_account and has_national_account:
            # Check that chapter and national accounts are different
            if has_chapter_account == has_national_account:
                frappe.throw(
                    _(
                        "Chapter Dues Income Account and National Dues Income Account "
                        "cannot be the same account ({0})"
                    ).format(has_chapter_account)
                )

        # Validate default split percentage if configured
        if getattr(self, "default_chapter_split_percentage", None):
            default_pct = float(self.default_chapter_split_percentage)
            if default_pct < 0 or default_pct > 100:
                frappe.throw(_("Default Chapter Split Percentage must be between 0 and 100"))

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def generate_webhook_secret(self, field="membership_webhook_secret"):
        key = frappe.generate_hash(length=20)
        self.set(field, key)
        self.save()

        secret_for = "Membership"

        frappe.msgprint(
            _("Here is your webhook secret for {0} API, this will be shown to you only once.").format(
                secret_for
            )
            + "<br><br>"
            + key,
            _("Webhook Secret"),
        )

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def revoke_key(self, key):
        self.set(key, None)
        self.save()

    def get_webhook_secret(self, endpoint="Membership"):
        fieldname = "membership_webhook_secret"
        return self.get_password(fieldname=fieldname, raise_exception=False)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_plans_for_membership(*args, **kwargs):
    controller = get_payment_gateway_controller("Razorpay")
    plans = controller.get_plans()
    return [plan.get("item") for plan in plans.get("items")]


# Add this function to verenigingen/verenigingen/doctype/verenigingen_settings/verenigingen_settings.py


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_income_account_query(doctype, txt, searchfield, start, page_len, filters):
    """Filter for income accounts only"""
    company = filters.get("company") or frappe.defaults.get_global_default("company")

    return frappe.db.sql(
        """
        SELECT name, account_name
        FROM `tabAccount`
        WHERE company = %s
        AND account_type = 'Income Account'
        AND is_group = 0
        AND (name LIKE %s OR account_name LIKE %s)
        ORDER BY name
        LIMIT %s OFFSET %s
    """,
        (company, "%" + txt + "%", "%" + txt + "%", page_len, start),
    )


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_organization_email_domain():
    """Get organization email domain setting for user creation"""
    settings = frappe.get_single("Verenigingen Settings")
    return {"organization_email_domain": getattr(settings, "organization_email_domain", None)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def validate_donation_configuration():
    """Validate donation system configuration"""
    settings = frappe.get_single("Verenigingen Settings")
    validation_results = {"status": "success", "warnings": [], "errors": [], "configuration": {}}

    # Check basic donation settings
    validation_results["configuration"][
        "automate_donation_payment_entries"
    ] = settings.automate_donation_payment_entries
    validation_results["configuration"]["default_donation_type"] = settings.default_donation_type
    validation_results["configuration"]["default_donor_type"] = getattr(settings, "default_donor_type", None)

    # Check account configuration
    if settings.automate_donation_payment_entries:
        if not settings.donations_gl_account:
            validation_results["errors"].append("Donations GL Account is not configured")
        if not settings.donation_debit_account:
            validation_results["errors"].append("Donation Debit Account is not configured")

    # Check ANBI configuration
    anbi_amount = getattr(settings, "anbi_minimum_reportable_amount", None)
    if not anbi_amount:
        validation_results["warnings"].append("ANBI minimum reportable amount is not configured")

    # Check earmarked accounts
    if not getattr(settings, "campaign_donation_account", None):
        validation_results["warnings"].append(
            "Campaign Donation Account not configured - campaign earmarking will not create separate GL entries"
        )

    if not getattr(settings, "restricted_donation_account", None):
        validation_results["warnings"].append(
            "Restricted Donation Account not configured - specific goal earmarking will not create separate GL entries"
        )

    # Check Donation Type doctype exists and has records
    donation_types = frappe.get_all("Donation Type", limit=1)
    if not donation_types:
        validation_results["warnings"].append(
            "No Donation Types configured - create some donation types for better categorization"
        )

    # Check Donor Type exists
    if not getattr(settings, "default_donor_type", None):
        donor_types = frappe.get_all("Donor Type", limit=1)
        if donor_types:
            validation_results["warnings"].append(
                "Default Donor Type not set - new donors will need manual type assignment"
            )
        else:
            validation_results["errors"].append(
                "No Donor Types exist - create donor types before accepting donations"
            )

    if validation_results["errors"]:
        validation_results["status"] = "error"
    elif validation_results["warnings"]:
        validation_results["status"] = "warning"

    return validation_results
