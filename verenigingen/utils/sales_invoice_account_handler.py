"""
Sales Invoice Account Handler
=============================

This module ensures that Sales Invoices created for membership dues use the
correct receivable account from Verenigingen Settings instead of the Company default.

The issue:
- Verenigingen Settings has 'default_receivable_account' set to "13500 - Te ontvangen contributies"
- Company has default_receivable_account set to "13900 - Te ontvangen bedragen"
- Sales Invoices are using Company default instead of Verenigingen Settings

The solution:
- Hook into Sales Invoice validation to set the correct debit_to account
- Check if the invoice is for membership (based on item or customer type)
- Use Verenigingen Settings default_receivable_account if applicable

Note: The redundant 'membership_debit_account' field has been removed from Verenigingen Settings
as it was identical to 'default_receivable_account' and not used anywhere.
"""

import frappe
from frappe import _


def set_membership_receivable_account(doc, method=None):
    """
    Set the correct receivable account for membership-related Sales Invoices.

    This function is called during Sales Invoice validation to ensure
    membership dues invoices use the account specified in Verenigingen Settings
    rather than the Company default.

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
        if not settings.default_receivable_account:
            return
    except Exception:
        # Verenigingen Settings doesn't exist or is not configured
        return

    # Get Company default to check if we need to override
    company_doc = frappe.get_cached_doc("Company", doc.company)
    company_default = company_doc.default_receivable_account

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
        doc.debit_to = settings.default_receivable_account
        frappe.msgprint(
            _("Using membership receivable account: {0}").format(settings.default_receivable_account),
            indicator="blue",
            alert=True,
        )
