import sys
from pathlib import Path

import frappe
from frappe import _
from frappe.utils import flt

utils_dir = str(Path(__file__).parent)
if utils_dir not in sys.path:
    sys.path.append(utils_dir)


# Jinja methods
def jinja_methods():
    """
    Methods available in jinja templates
    """
    return {
        "format_address": format_address,
        "get_membership_status": get_membership_status,
        "format_date_range": format_date_range,
    }


# Jinja filters
def jinja_filters():
    """
    Filters available in jinja templates
    """
    return {"format_currency": format_currency, "status_color": status_color}


# Helper functions for jinja methods


def format_address(address_dict):
    """Format an address dictionary for display"""
    if not address_dict:
        return ""

    address_parts = []
    if address_dict.get("address_line1"):
        address_parts.append(address_dict.get("address_line1"))
    if address_dict.get("address_line2"):
        address_parts.append(address_dict.get("address_line2"))

    city_state = []
    if address_dict.get("city"):
        city_state.append(address_dict.get("city"))
    if address_dict.get("state"):
        city_state.append(address_dict.get("state"))
    if city_state:
        address_parts.append(", ".join(city_state))

    if address_dict.get("postal_code"):
        address_parts.append(address_dict.get("postal_code"))
    if address_dict.get("country"):
        address_parts.append(address_dict.get("country"))

    return "<br>".join(address_parts)


def get_membership_status(member_name):
    """Get the current membership status for a member"""
    if not member_name:
        return "Unknown"

    memberships = frappe.get_all(
        "Membership",
        filters={"member": member_name, "status": "Active", "docstatus": 1},
        fields=["status"],
        order_by="start_date desc",
        limit=1,
    )

    if memberships:
        return memberships[0].status
    else:
        return "Inactive"


def format_date_range(start_date, end_date):
    """Format a date range for display"""
    if not start_date:
        return ""

    from frappe.utils import format_date

    if end_date:
        return f"{format_date(start_date)} - {format_date(end_date)}"
    else:
        return f"{format_date(start_date)} - Indefinite"


# Helper functions for jinja filters


def format_currency(value, currency="EUR"):
    """Format a number as currency"""
    from frappe.utils import fmt_money

    if not value:
        return fmt_money(0, currency=currency)

    return fmt_money(value, currency=currency)


def status_color(status):
    """Get color class for a status value"""
    status_colors = {
        "Active": "green",
        "Pending": "orange",
        "Expired": "red",
        "Cancelled": "grey",
        "Draft": "blue",
    }

    return status_colors.get(status, "grey")


# verenigingen/verenigingen/utils/dutch_tax_handler.py

# Constants for Dutch BTW Codes
BTW_CODES = {
    "EXEMPT_NONPROFIT": "BTW Vrijgesteld - Art. 11-1-f Wet OB",  # Cultural/social services
    "EXEMPT_MEMBERSHIP": "BTW Vrijgesteld - Art. 11-1-l Wet OB",  # Membership fees
    "EXEMPT_FUNDRAISING": "BTW Vrijgesteld - Art. 11-1-v Wet OB",  # Fundraising
    "EXEMPT_SMALL_BUSINESS": "BTW Vrijgesteld - KOR",  # Small Business Scheme
    "OUTSIDE_SCOPE": "Buiten reikwijdte BTW",  # Outside VAT scope
    "EXEMPT_WITH_INPUT": "BTW Vrijgesteld met recht op aftrek",  # Exempt with input VAT recovery
    "EXEMPT_NO_INPUT": "BTW Vrijgesteld zonder recht op aftrek",  # Exempt without input VAT recovery
}

# BTW Return Reporting Categories
BTW_REPORTING_CATEGORIES = {
    "EXEMPT_NONPROFIT": "1a",  # Report in box 1a of BTW return
    "EXEMPT_MEMBERSHIP": "1a",
    "EXEMPT_FUNDRAISING": "1a",
    "EXEMPT_SMALL_BUSINESS": "1a",
    "OUTSIDE_SCOPE": "None",  # Not reported in BTW return
    "EXEMPT_WITH_INPUT": "3",  # Report in box 3 of BTW return
    "EXEMPT_NO_INPUT": "1a",
}


class DutchTaxExemptionHandler:
    """
    Handles Dutch-specific VAT (BTW) exemption rules for non-profit organizations
    """

    def __init__(self):
        self.settings = frappe.get_single("Verenigingen Settings")
        self.company = self.settings.company or frappe.defaults.get_global_default("company")

    def setup_tax_exemption(self):
        """
        Set up Dutch VAT exemption templates and accounts
        """
        if not self.settings.get("tax_exempt_for_contributions"):
            return

        # Create tax templates for different exemption types
        self.create_dutch_tax_templates()

        # Set up BTW codes in Chart of Accounts
        self.setup_btw_codes_in_accounts()

        # Set up custom fields for tax exemption documentation
        self.create_custom_fields()

        frappe.msgprint(_("Dutch BTW exemption templates and settings have been created"))

    # Replace the create_dutch_tax_templates function in your utils.py with this fixed version:

    # Replace the create_dutch_tax_templates function in your utils.py with this fixed version:

    def create_dutch_tax_templates(self):
        """
        Create tax templates for different Dutch BTW exemption scenarios
        """
        # Create templates for different exemption types
        for exemption_type, description in BTW_CODES.items():
            template_name = f"BTW {exemption_type}"

            # Check for existing template with company abbreviation
            company_doc = frappe.get_doc("Company", self.company)
            full_template_name = f"{template_name} - {company_doc.abbr}"

            # Check if template already exists (with or without company abbr)
            if frappe.db.exists("Sales Taxes and Charges Template", template_name) or frappe.db.exists(
                "Sales Taxes and Charges Template", full_template_name
            ):
                continue

            # Create template
            tax_template = frappe.new_doc("Sales Taxes and Charges Template")
            tax_template.title = template_name  # Let ERPNext auto-generate the name
            # DON'T set tax_template.name - let ERPNext handle it
            tax_template.is_default = 0
            tax_template.company = self.company

            # Add documentation
            tax_template.description = description

            # Add 0% tax row with correct Dutch reporting code
            tax_template.append(
                "taxes",
                {
                    "charge_type": "On Net Total",
                    "account_head": self.get_tax_account(exemption_type),
                    "description": description,
                    "rate": 0,
                    "tax_code": exemption_type,
                    "reporting_category": BTW_REPORTING_CATEGORIES.get(exemption_type, "None"),
                },
            )

            try:
                tax_template.save()
                frappe.logger().info(f"Created BTW tax template: {tax_template.name}")
            except frappe.exceptions.DuplicateEntryError:
                # Template already exists, skip
                frappe.logger().info(f"BTW tax template {template_name} already exists, skipping")
                continue

            # Set specific template as default for contributions if it's the membership template
            if exemption_type == "EXEMPT_MEMBERSHIP" and not frappe.db.get_single_value(
                "Verenigingen Settings", "default_tax_template"
            ):
                # Use the actual created template name
                self.settings.default_tax_template = tax_template.name
                self.settings.save()

    def setup_btw_codes_in_accounts(self):
        """
        Set up BTW codes in the Chart of Accounts for proper tax reporting
        """
        # Get or create tax-related accounts
        for exemption_type, description in BTW_CODES.items():
            account_name = f"BTW {exemption_type}"

            # Check if account exists
            existing_account = frappe.db.get_value(
                "Account", {"account_name": account_name, "company": self.company}
            )

            if not existing_account:
                # Create account
                parent_account = self.get_btw_parent_account()

                if not parent_account:
                    frappe.msgprint(
                        _("Could not find or create BTW parent account. Please create it manually.")
                    )
                    continue

                account = frappe.new_doc("Account")
                account.account_name = account_name
                account.parent_account = parent_account
                account.account_type = "Tax"
                account.company = self.company
                account.account_currency = "EUR"
                account.is_group = 0

                # Add BTW specific details
                account.tax_rate = 0
                account.tax_category = "BTW Vrijgesteld"
                account.description = description

                account.insert()

    def get_btw_parent_account(self):
        """Get or create parent BTW account"""
        # Look for existing BTW/VAT account group
        btw_accounts = frappe.db.get_value(
            "Account",
            {
                "account_name": ["in", ["BTW", "VAT", "BTW Rekeningen", "VAT Accounts"]],
                "company": self.company,
                "is_group": 1,
            },
            "name",
        )

        if btw_accounts:
            return btw_accounts

        # Look for any Tax account group
        tax_account = frappe.db.get_value(
            "Account", {"account_type": "Tax", "company": self.company, "is_group": 1}, "name"
        )

        if tax_account:
            return tax_account

        # Look for parent liability account
        liability_account = frappe.db.get_value(
            "Account",
            {
                "root_type": "Liability",
                "is_group": 1,
                "company": self.company,
                "parent_account": ["is", "not set"],
            },
            "name",
        )

        if liability_account:
            # Create BTW account group
            btw_group = frappe.new_doc("Account")
            btw_group.account_name = "BTW Rekeningen"
            btw_group.parent_account = liability_account
            btw_group.is_group = 1
            btw_group.company = self.company
            btw_group.account_type = "Tax"
            btw_group.insert()

            return btw_group.name

        return None

    def get_tax_account(self, exemption_type):
        """Get the appropriate tax account for the exemption type"""
        account_name = f"BTW {exemption_type}"

        account = frappe.db.get_value(
            "Account", {"account_name": account_name, "company": self.company}, "name"
        )

        if account:
            return account

        # Fallback to any tax account
        tax_account = frappe.db.get_value(
            "Account", {"account_type": "Tax", "company": self.company, "is_group": 0}, "name"
        )

        if tax_account:
            return tax_account

        # If still no account, create a message and return a placeholder
        frappe.msgprint(_("Could not find appropriate BTW account. Please create it manually."))
        return "Placeholder - Create BTW Account"

    def create_custom_fields(self):
        """Create custom fields for tax exemption documentation"""
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

        custom_fields = {
            "Sales Invoice": [
                {
                    "fieldname": "btw_exemption_type",
                    "label": "BTW Exemption Type",
                    "fieldtype": "Select",
                    "options": "\n" + "\n".join(BTW_CODES.keys()),
                    "insert_after": "tax_category",
                    "translatable": 0,
                },
                {
                    "fieldname": "btw_exemption_reason",
                    "label": "BTW Exemption Reason",
                    "fieldtype": "Small Text",
                    "insert_after": "btw_exemption_type",
                    "translatable": 0,
                    "depends_on": "eval:doc.btw_exemption_type",
                },
                {
                    "fieldname": "btw_reporting_category",
                    "label": "BTW Reporting Category",
                    "fieldtype": "Data",
                    "insert_after": "btw_exemption_reason",
                    "translatable": 0,
                    "read_only": 1,
                    "depends_on": "eval:doc.btw_exemption_type",
                },
            ],
            "Membership": [
                {
                    "fieldname": "btw_exemption_type",
                    "label": "BTW Exemption Type",
                    "fieldtype": "Select",
                    "options": "\n" + "\n".join(BTW_CODES.keys()),
                    "insert_after": "tax_category",
                    "default": "EXEMPT_MEMBERSHIP",
                    "translatable": 0,
                }
            ],
            "Donation": [
                {
                    "fieldname": "btw_exemption_type",
                    "label": "BTW Exemption Type",
                    "fieldtype": "Select",
                    "options": "\n" + "\n".join(BTW_CODES.keys()),
                    "insert_after": "donation_category",
                    "default": "EXEMPT_FUNDRAISING",
                    "translatable": 0,
                }
            ],
        }

        create_custom_fields(custom_fields)

    def apply_exemption_to_invoice(self, invoice, exemption_type=None):
        """
        Apply the appropriate BTW exemption to an invoice
        Args:
            invoice: Sales Invoice document
            exemption_type: BTW exemption type (use default if None)
        """
        if not exemption_type:
            # Get default from related document or use membership exemption
            if invoice.membership:
                exemption_type = frappe.db.get_value("Membership", invoice.membership, "btw_exemption_type")
            elif invoice.donation:
                exemption_type = frappe.db.get_value("Donation", invoice.donation, "btw_exemption_type")
            else:
                exemption_type = "EXEMPT_MEMBERSHIP"  # Default

        # Set BTW exemption fields
        invoice.btw_exemption_type = exemption_type
        invoice.btw_reporting_category = BTW_REPORTING_CATEGORIES.get(exemption_type, "None")

        # Set default reason based on type
        if not invoice.btw_exemption_reason:
            invoice.btw_exemption_reason = BTW_CODES.get(exemption_type, "")

        # Apply the correct tax template
        tax_template = f"BTW {exemption_type}"
        if frappe.db.exists("Sales Taxes and Charges Template", tax_template):
            invoice.taxes_and_charges = tax_template
            invoice.set_taxes()

        return invoice


def setup_dutch_tax_exemption(doc=None, method=None):
    """
    Main function to set up Dutch tax exemption
    Called from hooks when Verenigingen Settings is updated
    """
    handler = DutchTaxExemptionHandler()
    handler.setup_tax_exemption()


@frappe.whitelist()
def apply_btw_exemption(docname, doctype="Sales Invoice", exemption_type=None):
    """
    Apply BTW exemption to a document
    """
    doc = frappe.get_doc(doctype, docname)

    handler = DutchTaxExemptionHandler()
    handler.apply_exemption_to_invoice(doc, exemption_type)

    doc.save()
    frappe.msgprint(_("BTW exemption applied to {0}").format(docname))

    return doc


def on_update_verenigingen_settings(doc, method=None):
    """
    Hook function called when Verenigingen Settings is updated
    Only runs tax setup when tax exemption setting is actually changed
    """
    try:
        # Only run tax setup if the doc is a Verenigingen Settings doc
        # and tax exemption is enabled
        if hasattr(doc, "doctype") and doc.doctype == "Verenigingen Settings":
            if doc.get("tax_exempt_for_contributions"):
                frappe.logger().info("Tax exemption enabled, setting up tax templates")
                setup_dutch_tax_exemption(doc, method)
            else:
                frappe.logger().info("Tax exemption disabled, skipping tax template setup")
        else:
            # This is just a member ID counter update, don't run tax setup
            frappe.logger().debug("Settings update from member creation, skipping tax setup")

    except Exception as e:
        # Log error but don't fail the settings update or member creation
        frappe.log_error(f"Error in tax exemption setup: {str(e)}", "Tax Exemption Setup Error")
        frappe.logger().warning(f"Tax exemption setup failed but continuing: {str(e)}")
        # Don't re-raise the error so member creation can continue


def generate_btw_report(start_date, end_date):
    """
    Generate Dutch BTW (VAT) report for the specified period
    """
    # Get all invoices in the period
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "posting_date": ["between", [start_date, end_date]],
            "docstatus": 1,
            "company": frappe.defaults.get_global_default("company"),
        },
        fields=["name", "posting_date", "btw_exemption_type", "btw_reporting_category", "base_grand_total"],
    )

    # Initialize report categories
    report_data = {
        "1a": 0,  # Leveringen/diensten belast met hoog tarief
        "1b": 0,  # Leveringen/diensten belast met laag tarief
        "1c": 0,  # Leveringen/diensten belast met overige tarieven
        "1d": 0,  # Privégebruik
        "1e": 0,  # BTW-belaste leveringen/diensten - Invoerdrempel
        "2a": 0,  # BTW hoog tarief
        "2b": 0,  # BTW laag tarief
        "2c": 0,  # BTW overige tarieven
        "2d": 0,  # BTW privégebruik
        "2e": 0,  # BTW Invoerdrempel
        "3": 0,  # Leveringen/diensten naar het buitenland
        "4a": 0,  # Leveringen naar landen binnen de EU
        "4b": 0,  # Leveringen naar landen buiten de EU
        "5a": 0,  # Voorbelasting
        "5b": 0,  # BTW verlegd naar u
        "5c": 0,  # Invoer
        "5d": 0,  # Kleine ondernemersregeling (KOR)
        "total": 0,  # Total amount
    }

    # Categorize invoices
    for invoice in invoices:
        category = invoice.btw_reporting_category or "1a"  # Default to 1a if not specified

        if category != "None":
            report_data[category] += flt(invoice.base_grand_total)
            report_data["total"] += flt(invoice.base_grand_total)

    return report_data


# Add this function to your verenigingen/utils.py (replace the existing one)


def apply_tax_exemption_from_source(doc, method=None):
    """
    Automatically apply tax exemption based on the source document
    Updated with error handling for missing BTW custom fields
    """
    # Check if the attribute exists before using it
    if hasattr(doc, "exempt_from_tax") and doc.exempt_from_tax:
        return

    # Skip if taxes already applied and not a new document
    if doc.taxes and not doc.is_new():
        return

    # Check if BTW custom fields exist before trying to use them
    has_btw_fields = (
        hasattr(doc, "btw_exemption_type")
        and hasattr(doc, "btw_exemption_reason")
        and hasattr(doc, "btw_reporting_category")
    )

    if not has_btw_fields:
        # Fallback to simple tax exemption without BTW fields
        frappe.logger().warning("BTW custom fields missing on Sales Invoice. Using simple tax exemption.")

        # Apply simple tax exemption
        settings = frappe.get_single("Verenigingen Settings")
        if settings.get("tax_exempt_for_contributions"):
            # Set the basic exempt_from_tax flag
            doc.exempt_from_tax = 1

            # Try to apply a basic tax template if available
            if settings.get("default_tax_template"):
                if frappe.db.exists("Sales Taxes and Charges Template", settings.default_tax_template):
                    doc.taxes_and_charges = settings.default_tax_template
                    try:
                        doc.set_taxes()
                    except Exception as e:
                        frappe.logger().error(f"Error setting taxes: {str(e)}")
        return

    # If BTW fields exist, use the full Dutch tax handler
    try:
        handler = DutchTaxExemptionHandler()

        # For membership-related invoices
        if hasattr(doc, "membership") and doc.membership:
            exemption_type = (
                frappe.db.get_value("Membership", doc.membership, "btw_exemption_type") or "EXEMPT_MEMBERSHIP"
            )
            handler.apply_exemption_to_invoice(doc, exemption_type)

        # For donation-related invoices
        elif hasattr(doc, "donation") and doc.donation:
            exemption_type = (
                frappe.db.get_value("Donation", doc.donation, "btw_exemption_type") or "EXEMPT_FUNDRAISING"
            )
            handler.apply_exemption_to_invoice(doc, exemption_type)

        # Use default exemption for verenigingen-created invoices if tax exempt is enabled
        elif frappe.db.get_single_value("Verenigingen Settings", "tax_exempt_for_contributions"):
            default_exemption = (
                frappe.db.get_single_value("Verenigingen Settings", "default_tax_exemption_type")
                or "EXEMPT_MEMBERSHIP"
            )
            handler.apply_exemption_to_invoice(doc, default_exemption)

    except Exception as e:
        # Log error but don't fail invoice creation
        frappe.log_error(f"Error in BTW tax exemption for {doc.name}: {str(e)}", "BTW Tax Exemption Error")

        # Fallback to simple exemption
        settings = frappe.get_single("Verenigingen Settings")
        if settings.get("tax_exempt_for_contributions"):
            doc.exempt_from_tax = 1


@frappe.whitelist()
def debug_workspace_breadcrumb():
    """Debug workspace breadcrumb issue"""

    # Get all workspaces for Verenigingen module
    workspaces = frappe.get_all(
        "Workspace",
        filters={"module": "E-Boekhouden"},
        fields=["name", "label", "module", "sequence_id", "is_hidden", "public"],
        order_by="sequence_id",
    )

    result = {"workspaces": workspaces}

    # Check which workspace would be loaded first
    first_workspace = frappe.db.get_value(
        "Workspace",
        {"module": "E-Boekhouden", "is_hidden": 0, "public": 1},
        "name",
        order_by="sequence_id asc",
    )
    result["first_workspace"] = first_workspace

    # Check for any workspace in URL or context
    if hasattr(frappe.local, "request") and frappe.local.request:
        result["current_path"] = frappe.local.request.path
        result["request_workspace"] = frappe.form_dict.get("workspace")

    return result


@frappe.whitelist()
def debug_breadcrumb_detailed():
    """More detailed breadcrumb debugging"""
    result = {}

    # Check module default workspace
    module_workspace = frappe.db.sql(
        """
        SELECT w.name, w.label, w.sequence_id
        FROM tabWorkspace w
        WHERE w.module = 'Verenigingen'
        AND w.is_hidden = 0
        AND w.public = 1
        ORDER BY w.sequence_id ASC
        LIMIT 1
    """,
        as_dict=True,
    )

    result["module_default_workspace"] = module_workspace[0] if module_workspace else None

    # Check if SEPA Management has any special flags
    sepa_ws = frappe.get_doc("Workspace", "SEPA Management")
    result["sepa_workspace_details"] = {
        "name": sepa_ws.name,
        "label": sepa_ws.label,
        "title": sepa_ws.title,
        "module": sepa_ws.module,
        "sequence_id": sepa_ws.sequence_id,
        "is_hidden": sepa_ws.is_hidden,
        "public": sepa_ws.public,
        "roles": [r.role for r in sepa_ws.roles],
    }

    # Check doctype assignments
    doctypes = frappe.get_all("DocType", filters={"module": "E-Boekhouden"}, fields=["name"], limit=5)
    result["sample_doctypes"] = doctypes

    return result


@frappe.whitelist()
def fix_workspace_order():
    """Fix workspace ordering to ensure Verenigingen is the primary workspace"""

    # Update sequence IDs to ensure proper ordering
    updates = [
        ("Verenigingen", 1.0),  # Make it first
        ("E-Boekhouden", 50.0),  # Secondary
        ("SEPA Management", 100.0),  # Tertiary
    ]

    for workspace_name, new_sequence in updates:
        frappe.db.set_value("Workspace", workspace_name, "sequence_id", new_sequence)

    frappe.db.commit()

    # Clear cache to ensure changes take effect
    frappe.clear_cache()

    return {
        "success": True,
        "message": "Workspace order fixed. Verenigingen should now be the primary workspace.",
    }


@frappe.whitelist()
def debug_workspace_doctype_mapping():
    """Debug how doctypes are mapped to workspaces"""

    # Get all workspace links
    workspace_links = frappe.db.sql(
        """
        SELECT
            w.name as workspace,
            wl.link_to,
            wl.link_name,
            wl.link_type
        FROM `tabWorkspace` w
        JOIN `tabWorkspace Link` wl ON wl.parent = w.name
        WHERE w.module = 'Verenigingen'
        AND wl.link_type = 'DocType'
        ORDER BY w.name, wl.idx
    """,
        as_dict=True,
    )

    # Group by workspace
    workspace_doctypes = {}
    for link in workspace_links:
        workspace = link["workspace"]
        if workspace not in workspace_doctypes:
            workspace_doctypes[workspace] = []

        doctype = link["link_to"] or link["link_name"]
        if doctype:
            workspace_doctypes[workspace].append(doctype)

    # Check which workspace Member belongs to
    member_workspaces = []
    for workspace, doctypes in workspace_doctypes.items():
        if "Member" in doctypes:
            member_workspaces.append(workspace)

    return {
        "workspace_doctypes": workspace_doctypes,
        "member_found_in": member_workspaces,
        "total_links": len(workspace_links),
    }
