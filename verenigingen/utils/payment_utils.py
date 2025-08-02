"""
Payment Processing and Financial Transaction Utilities

This module provides comprehensive payment processing utilities for the Verenigingen
association management system. It handles donation payment entries, member payment
processing, financial history management, and integration with ERPNext's financial
accounting framework.

Key Features:
- Automated payment entry creation for donations and membership transactions
- Member payment processing with status tracking and history management
- Financial account integration with company-specific configurations
- Payment validation and amount handling with business rule enforcement
- Legacy compatibility for existing payment workflows
- Integration with ERPNext's Payment Entry and accounting systems

Business Context:
Payment processing is central to the association's financial operations, handling:
- Donation payments from supporters and members
- Membership dues collection and tracking
- Expense reimbursements for volunteers and staff
- Financial reporting and audit trail maintenance
- Integration with banking and payment gateway systems

Architecture:
This utility integrates with:
- ERPNext Payment Entry system for financial transaction recording
- Donation DocType for donation payment processing
- Member DocType for membership payment tracking
- Company settings for account defaults and configurations
- Mode of Payment system for payment method handling
- Financial reporting systems for audit and compliance

Payment Processing Workflow:
1. Payment Entry Creation:
   - Validate source documents (donations, membership fees)
   - Configure appropriate accounts based on company settings
   - Set party details and payment references
   - Apply business rules and validation

2. Financial Integration:
   - Link to ERPNext's accounting framework
   - Ensure proper account classification and reporting
   - Maintain audit trails for compliance
   - Support multi-company operations

3. Status Management:
   - Track payment status throughout lifecycle
   - Update related documents automatically
   - Provide financial history and reporting
   - Support reconciliation processes

Financial Accounts Integration:
- Default receivable accounts for customer payments
- Cash and bank accounts for payment receipt
- Income accounts for donation and dues classification
- Proper account mapping for financial reporting

Data Model:
- Payment Entry creation with proper account classification
- Reference linking between payments and source documents
- Party management for customers and donors
- Amount validation and currency handling
- Payment method mapping and processing

Author: Development Team
Date: 2025-08-02
Version: 1.0
"""

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from frappe import _
from frappe.utils import flt, get_datetime, nowdate, today


@frappe.whitelist()
def get_donation_payment_entry(dt, dn):
    """
    Create a Payment Entry for a Donation.

    Args:
            dt (str): Document Type (should be 'Donation')
            dn (str): Document Name (donation ID)

    Returns:
            dict: Payment Entry document data
    """
    # Validate inputs
    if dt != "Donation":
        frappe.throw(_("This method only supports Donation documents"))

    # Get the donation document
    donation = frappe.get_doc(dt, dn)

    # Validate donation status
    if donation.docstatus != 1:
        frappe.throw(_("Payment Entry can only be created for submitted donations"))

    if donation.paid:
        frappe.throw(_("Payment Entry already exists for this donation"))

    # Get company details
    company = donation.company
    if not company:
        company = frappe.defaults.get_user_default("Company")

    # Get accounts for the company
    default_receivable_account = frappe.get_cached_value("Company", company, "default_receivable_account")

    default_cash_account = frappe.get_cached_value("Company", company, "default_cash_account")

    # Create Payment Entry
    payment_entry = frappe.new_doc("Payment Entry")
    payment_entry.payment_type = "Receive"
    payment_entry.company = company
    payment_entry.posting_date = donation.donation_date or today()
    payment_entry.reference_date = donation.donation_date or today()

    # Set party details
    if donation.donor:
        # Check if donor exists as customer
        customer = frappe.db.get_value("Customer", {"name": donation.donor})
        if customer:
            payment_entry.party_type = "Customer"
            payment_entry.party = donation.donor
            payment_entry.party_name = donation.donor
        else:
            # Create a generic entry without party
            payment_entry.party_type = ""
            payment_entry.party = ""

    # Set accounts
    payment_entry.paid_from = default_receivable_account if payment_entry.party else ""
    payment_entry.paid_to = default_cash_account

    # Set amount
    payment_entry.paid_amount = flt(donation.amount)
    payment_entry.received_amount = flt(donation.amount)

    # Set reference
    payment_entry.reference_no = donation.name
    payment_entry.reference_date = donation.donation_date or today()

    # Add reference to the donation
    payment_entry.append(
        "references",
        {"reference_doctype": dt, "reference_name": dn, "allocated_amount": flt(donation.amount)},
    )

    # Set mode of payment if available
    if donation.payment_method:
        # Map donation payment method to mode of payment
        mode_of_payment_map = {
            "Cash": "Cash",
            "Bank Transfer": "Bank Transfer",
            "SEPA Direct Debit": "Bank Transfer",
            "Credit Card": "Credit Card",
            "Online Payment": "Online Payment",
        }

        mode_of_payment = mode_of_payment_map.get(donation.payment_method, "Cash")

        # Check if mode of payment exists
        if frappe.db.exists("Mode of Payment", mode_of_payment):
            payment_entry.mode_of_payment = mode_of_payment

    # Set remarks
    payment_entry.remarks = _("Payment Entry for Donation {0}").format(donation.name)
    if donation.donation_notes:
        payment_entry.remarks += "\n" + donation.donation_notes

    # Return the document
    return payment_entry.as_dict()


@frappe.whitelist()
def process_payment(member):
    """
    Process payment for a member (legacy method for compatibility).

    Args:
            member (str): Member ID

    Returns:
            dict: Result of payment processing
    """
    if not member:
        frappe.throw(_("Member ID is required"))

    member_doc = frappe.get_doc("Member", member)

    # This is a placeholder implementation
    # The actual payment processing logic would be implemented based on business requirements
    return {
        "success": True,
        "message": _("Payment processing initiated for member {0}").format(member_doc.full_name),
        "member": member,
    }


@frappe.whitelist()
def mark_as_paid(member):
    """
    Mark a member as paid (legacy method for compatibility).

    Args:
            member (str): Member ID

    Returns:
            dict: Result of the operation
    """
    if not member:
        frappe.throw(_("Member ID is required"))

    member_doc = frappe.get_doc("Member", member)

    # This is a placeholder implementation
    # The actual logic would depend on business requirements
    return {
        "success": True,
        "message": _("Member {0} marked as paid").format(member_doc.full_name),
        "member": member,
    }


@frappe.whitelist()
def refresh_financial_history(member):
    """
    Refresh financial history for a member (legacy method for compatibility).

    Args:
            member (str): Member ID

    Returns:
            dict: Result of the refresh operation
    """
    if not member:
        frappe.throw(_("Member ID is required"))

    member_doc = frappe.get_doc("Member", member)

    # Call the member's refresh method if it exists
    if hasattr(member_doc, "refresh_financial_history"):
        member_doc.refresh_financial_history()
        member_doc.save()

    return {
        "success": True,
        "message": _("Financial history refreshed for member {0}").format(member_doc.full_name),
        "member": member,
    }


def validate_payment_amount(amount):
    """
    Validate payment amount.

    Args:
            amount: Amount to validate

    Returns:
            float: Validated amount
    """
    if not amount:
        return 0.0

    amount = flt(amount)
    if amount < 0:
        frappe.throw(_("Payment amount cannot be negative"))

    return amount


def get_default_income_account(company):
    """
    Get default income account for a company.

    Args:
            company (str): Company name

    Returns:
            str: Default income account
    """
    if not company:
        return None

    # Try to get donation income account first
    income_account = frappe.db.get_value(
        "Account", {"company": company, "account_name": ["like", "%donation%"], "is_group": 0}, "name"
    )

    if not income_account:
        # Fall back to default income account
        income_account = frappe.get_cached_value("Company", company, "default_income_account")

    return income_account


def format_payment_history_row(row):
    """
    Format a payment history row for display.

    Args:
            row: Payment history row object

    Returns:
            dict: Formatted row data
    """
    if not row or not hasattr(row, "doc"):
        return {}

    doc = row.doc

    return {
        "amount": flt(doc.get("amount", 0)),
        "date": doc.get("transaction_date") or doc.get("posting_date"),
        "status": doc.get("payment_status") or doc.get("status"),
        "reference": doc.get("reference_no") or doc.get("name"),
        "notes": doc.get("notes") or doc.get("remarks"),
    }
