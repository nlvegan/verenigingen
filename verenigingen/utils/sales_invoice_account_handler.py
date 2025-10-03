"""
Sales Invoice Account Handler
=============================

This module ensures that Sales Invoices created for membership dues use the
correct receivable account from Verenigingen Settings instead of the Company default.

The issue:
- Verenigingen Settings has 'dues_payments_receivable_account' for membership dues
- Company has default_receivable_account set to a general receivables account
- Sales Invoices should use the specific dues receivable account for membership invoices

The solution:
- Hook into Sales Invoice validation to set the correct debit_to account
- Check if the invoice is for membership (based on item or customer type)
- Use Verenigingen Settings dues_payments_receivable_account if applicable
"""

import frappe
from frappe import _


def set_membership_receivable_account(doc, method=None):
    """
    Set the correct receivable account for membership-related Sales Invoices.

    This function is called during Sales Invoice validation to ensure
    membership dues invoices use the dues_payments_receivable_account specified
    in Verenigingen Settings rather than the Company default.

    Args:
        doc: Sales Invoice document
        method: Event method (validate, before_insert, etc.)
    """
    # Skip if debit_to is already manually set to something other than company default
    if not doc.debit_to:
        return

    # Get Verenigingen Settings
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if not settings.dues_payments_receivable_account:
            return
    except frappe.DoesNotExistError:
        frappe.log_error("Verenigingen Settings not found", "Sales Invoice Account Handler")
        return
    except AttributeError as e:
        frappe.log_error(
            f"Field dues_payments_receivable_account missing: {str(e)}", "Sales Invoice Account Handler"
        )
        return
    except frappe.ValidationError as e:
        frappe.log_error(f"Verenigingen Settings validation error: {str(e)}", "Sales Invoice Account Handler")
        return

    # Get Company default to check if we need to override
    try:
        company_doc = frappe.get_cached_doc("Company", doc.company)
        company_default = company_doc.default_receivable_account
        if not company_default:
            frappe.log_error(
                f"Company {doc.company} has no default_receivable_account set",
                "Sales Invoice Account Handler",
            )
            return
    except frappe.DoesNotExistError:
        frappe.log_error(f"Company {doc.company} not found", "Sales Invoice Account Handler")
        return

    # Only proceed if current debit_to is the company default
    if doc.debit_to != company_default:
        return

    # Check if this is a membership-related invoice
    is_membership_invoice = False

    # Method 1: Check if any items are membership-related
    membership_item_groups = ["Membership", "Contributie", "Lidmaatschap"]
    for item in doc.items:
        if item.item_group in membership_item_groups:
            is_membership_invoice = True
            break

        # Check item name patterns
        item_name_lower = (item.item_name or "").lower()
        if any(
            keyword in item_name_lower for keyword in ["membership", "contributie", "lidmaatschap", "dues"]
        ):
            is_membership_invoice = True
            break

    # Method 2: Check if customer is a Member (has associated Member record)
    if not is_membership_invoice and doc.customer:
        member_exists = frappe.db.exists("Member", {"customer": doc.customer})
        if member_exists:
            is_membership_invoice = True

    # Method 3: Check if invoice remarks mention membership
    if not is_membership_invoice and doc.remarks:
        remarks_lower = doc.remarks.lower()
        if any(keyword in remarks_lower for keyword in ["membership", "contributie", "lidmaatschap", "dues"]):
            is_membership_invoice = True

    # Set the correct account if this is a membership invoice
    if is_membership_invoice:
        doc.debit_to = settings.dues_payments_receivable_account
        # Log for debugging but don't show popup during bulk operations
        frappe.logger().info(
            f"Using membership dues receivable account: {settings.dues_payments_receivable_account}"
        )
