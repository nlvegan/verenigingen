"""
Payment Entry Repair Utility

Administrative utility for repairing missing or corrupted Payment Entries
associated with donation records. Provides functions to create missing
Payment Entries and fix data integrity issues.

Usage: Call functions via bench console or admin interface
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_missing_payment_entry(payment_id):
    """
    Administrative function to create missing Payment Entry for a donation
    that was processed via webhook but didn't get a Payment Entry due to errors.

    Args:
        payment_id: Mollie payment ID to create Payment Entry for
    """

    # Ensure admin permissions for this administrative function
    if not frappe.has_permission("Payment Entry", "write"):
        frappe.throw("Insufficient permissions for Payment Entry repair operations")

    try:
        # Find donation by payment_id
        donations = frappe.get_all("Donation", filters={"payment_id": payment_id}, fields=["name"])
        if not donations:
            return {"status": "error", "message": f"No donation found for payment {payment_id}"}

        donation = frappe.get_doc("Donation", donations[0]["name"])

        # Check if Payment Entry already exists for this donation
        existing_payment_entries = frappe.get_all(
            "Payment Entry", filters={"reference_no": payment_id, "docstatus": 1}, fields=["name"]
        )
        if existing_payment_entries:
            return {
                "status": "ignored",
                "message": f"Payment Entry already exists: {existing_payment_entries[0]['name']}",
            }

        # Create Journal Entry (simpler for donations without customer records)
        journal_entry = frappe.new_doc("Journal Entry")
        journal_entry.title = f"Donation Payment - {payment_id}"
        journal_entry.voucher_type = "Journal Entry"
        journal_entry.company = donation.company
        journal_entry.posting_date = donation.donation_date
        journal_entry.reference_no = payment_id
        journal_entry.reference_date = donation.donation_date

        # Get accounts
        cash_account = frappe.get_value("Company", donation.company, "default_cash_account")
        if not cash_account:
            cash_accounts = frappe.db.sql(
                """
                SELECT name FROM `tabAccount`
                WHERE company = %s AND account_type = 'Cash'
                AND is_group = 0
                LIMIT 1
            """,
                (donation.company,),
            )
            if cash_accounts:
                cash_account = cash_accounts[0][0]

        # Get income account for donations - try multiple approaches
        income_account = None

        # Try to find income account
        income_accounts = frappe.db.sql(
            """
            SELECT name FROM `tabAccount`
            WHERE company = %s AND account_type = 'Income'
            AND is_group = 0
            LIMIT 1
        """,
            (donation.company,),
        )
        if income_accounts:
            income_account = income_accounts[0][0]

        # Fallback to any income account
        if not income_account:
            income_accounts = frappe.db.sql(
                """
                SELECT name FROM `tabAccount`
                WHERE company = %s AND name LIKE '%income%'
                AND is_group = 0
                LIMIT 1
            """,
                (donation.company,),
            )
            if income_accounts:
                income_account = income_accounts[0][0]

        # Final fallback - use default income account from company
        if not income_account:
            income_account = frappe.get_value("Company", donation.company, "default_income_account")

        if not cash_account or not income_account:
            return {
                "status": "error",
                "message": "Missing accounts - Cash: "
                + str(cash_account)
                + ", Income: "
                + str(income_account),
            }

        # Add journal entry accounts
        journal_entry.append(
            "accounts",
            {
                "account": cash_account,
                "debit_in_account_currency": donation.amount,
                "credit_in_account_currency": 0,
            },
        )

        journal_entry.append(
            "accounts",
            {
                "account": income_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": donation.amount,
            },
        )

        journal_entry.insert()
        journal_entry.submit()

        return {
            "status": "success",
            "message": f"Journal Entry {journal_entry.name} created for donation {donation.name}",
            "journal_entry": journal_entry.name,
            "donation": donation.name,
        }

    except Exception as e:
        frappe.log_error(
            f"Failed to create Payment Entry for {payment_id}: {str(e)}", "Payment Entry Fixer Error"
        )
        return {"status": "error", "message": str(e)}
