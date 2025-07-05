# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from payments.utils import get_payment_gateway_controller


class VerenigingenSettings(Document):
    def validate(self):
        self.validate_donation_accounts()

    def validate_donation_accounts(self):
        """Validate donation account configuration"""
        if self.automate_donation_payment_entries:
            if not self.donation_payment_account:
                frappe.throw(
                    _("Donation Payment Account is required when automating donation payment entries")
                )
            if not self.donation_debit_account:
                frappe.throw(_("Donation Debit Account is required when automating donation payment entries"))

        # Validate that earmarked accounts are different from main donation account
        if self.campaign_donation_account and self.campaign_donation_account == self.donation_payment_account:
            frappe.msgprint(
                _(
                    "Campaign Donation Account should be different from main Donation Payment Account for proper fund segregation"
                ),
                indicator="yellow",
            )

        if (
            self.restricted_donation_account
            and self.restricted_donation_account == self.donation_payment_account
        ):
            frappe.msgprint(
                _(
                    "Restricted Donation Account should be different from main Donation Payment Account for proper fund segregation"
                ),
                indicator="yellow",
            )

    @frappe.whitelist()
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
    def revoke_key(self, key):
        self.set(key, None)
        self.save()

    def get_webhook_secret(self, endpoint="Membership"):
        fieldname = "membership_webhook_secret"
        return self.get_password(fieldname=fieldname, raise_exception=False)


@frappe.whitelist()
def get_plans_for_membership(*args, **kwargs):
    controller = get_payment_gateway_controller("Razorpay")
    plans = controller.get_plans()
    return [plan.get("item") for plan in plans.get("items")]


# Add this function to verenigingen/verenigingen/doctype/verenigingen_settings/verenigingen_settings.py


@frappe.whitelist()
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
def get_organization_email_domain():
    """Get organization email domain setting for user creation"""
    settings = frappe.get_single("Verenigingen Settings")
    return {"organization_email_domain": getattr(settings, "organization_email_domain", None)}


@frappe.whitelist()
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
        if not settings.donation_payment_account:
            validation_results["errors"].append("Donation Payment Account is not configured")
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
