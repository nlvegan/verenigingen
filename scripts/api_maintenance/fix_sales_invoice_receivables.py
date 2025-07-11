"""
Fix Sales Invoice Receivable Account Mapping

This script fixes the issue where sales invoices imported from E-boekhouden
are incorrectly assigned to "Te ontvangen contributies" (13500) instead of
"Te ontvangen bedragen" (13900).
"""

import frappe


@frappe.whitelist()
def fix_existing_sales_invoice_receivables(company=None):
    """
    Fix existing sales invoices that have wrong receivable account assignment
    """
    if not company:
        # Get the default company from E-Boekhouden settings
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

    if not company:
        return {"success": False, "error": "No company specified"}

    try:
        # Get the correct receivable accounts
        wrong_account = frappe.db.get_value(
            "Account", {"account_number": "13500", "company": company}, "name"
        )  # Te ontvangen contributies
        correct_account = frappe.db.get_value(
            "Account", {"account_number": "13900", "company": company}, "name"
        )  # Te ontvangen bedragen

        if not wrong_account or not correct_account:
            return {
                "success": False,
                "error": f"Could not find accounts 13500 or 13900 for company {company}",
            }

        # Find sales invoices using the wrong receivable account
        wrong_invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "company": company,
                "debit_to": wrong_account,
                "docstatus": 1,  # Only submitted invoices
            },
            fields=["name", "posting_date", "grand_total"],
        )

        fixed_count = 0
        errors = []

        for invoice in wrong_invoices:
            try:
                # Update the debit_to field
                frappe.db.set_value("Sales Invoice", invoice.name, "debit_to", correct_account)

                # Also update related GL entries
                frappe.db.sql(
                    """
                    UPDATE `tabGL Entry`
                    SET account = %s
                    WHERE voucher_type = 'Sales Invoice'
                      AND voucher_no = %s
                      AND account = %s
                """,
                    (correct_account, invoice.name, wrong_account),
                )

                fixed_count += 1

            except Exception as e:
                errors.append(f"Failed to fix {invoice.name}: {str(e)}")

        frappe.db.commit()

        return {
            "success": True,
            "fixed_count": fixed_count,
            "total_found": len(wrong_invoices),
            "errors": errors,
            "message": f"Fixed {fixed_count} out of {len(wrong_invoices)} sales invoices",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_receivable_account_mapping(company=None):
    """
    Get the correct receivable account for sales invoices
    """
    if not company:
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

    if not company:
        return None

    # Return the correct receivable account (13900 - Te ontvangen bedragen)
    return frappe.db.get_value("Account", {"account_number": "13900", "company": company}, "name")


@frappe.whitelist()
def check_sales_invoice_receivables(company=None):
    """
    Check how many sales invoices are using the wrong receivable account
    """
    if not company:
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

    if not company:
        return {"success": False, "error": "No company specified"}

    try:
        # Get account names
        contrib_account = frappe.db.get_value(
            "Account", {"account_number": "13500", "company": company}, ["name", "account_name"], as_dict=True
        )
        amounts_account = frappe.db.get_value(
            "Account", {"account_number": "13900", "company": company}, ["name", "account_name"], as_dict=True
        )

        # Count sales invoices by receivable account
        contrib_count = frappe.db.count(
            "Sales Invoice",
            {"company": company, "debit_to": contrib_account.name if contrib_account else "", "docstatus": 1},
        )

        amounts_count = frappe.db.count(
            "Sales Invoice",
            {"company": company, "debit_to": amounts_account.name if amounts_account else "", "docstatus": 1},
        )

        total_invoices = frappe.db.count("Sales Invoice", {"company": company, "docstatus": 1})

        return {
            "success": True,
            "company": company,
            "accounts": {"contributions": contrib_account, "amounts": amounts_account},
            "invoice_counts": {
                "using_contributions_account": contrib_count,
                "using_amounts_account": amounts_count,
                "total_invoices": total_invoices,
                "other_accounts": total_invoices - contrib_count - amounts_count,
            },
            "needs_fixing": contrib_count > 0,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
