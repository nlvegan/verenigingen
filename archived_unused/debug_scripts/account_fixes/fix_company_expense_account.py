"""
Fix the company's default expense account
"""

import frappe


@frappe.whitelist()
def fix_company_default_expense_account():
    """Fix the non-existent default expense account in company settings"""

    try:
        company = "Ned Ver Vegan"

        # Check current setting
        current_account = frappe.db.get_value("Company", company, "default_expense_account")

        result = {"current_default_expense_account": current_account, "account_exists": False, "action": None}

        # Check if it exists
        if current_account:
            result["account_exists"] = frappe.db.exists("Account", current_account)

        if not result["account_exists"]:
            # Find a suitable expense account
            expense_account = frappe.db.get_value(
                "Account",
                {
                    "company": company,
                    "account_type": "Expense Account",
                    "is_group": 0,
                    "name": ["like", "%Onvoorziene kosten%"],  # Unforeseen expenses
                },
                "name",
            )

            if not expense_account:
                # Fallback to any expense account
                expense_account = frappe.db.get_value(
                    "Account", {"company": company, "account_type": "Expense Account", "is_group": 0}, "name"
                )

            if expense_account:
                # Update the company
                frappe.db.set_value("Company", company, "default_expense_account", expense_account)
                frappe.db.commit()

                result["action"] = "updated"
                result["new_default_expense_account"] = expense_account
                result[
                    "message"
                ] = "Updated default expense account from '{current_account}' to '{expense_account}'"
            else:
                result["action"] = "no_expense_account_found"
                result["message"] = "Could not find any expense account to set as default"
        else:
            result["action"] = "no_change_needed"
            result["message"] = "Current default expense account '{current_account}' exists"

        # Skip COGS account check as field doesn't exist in this version

        return result

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def list_expense_accounts():
    """List available expense accounts"""

    accounts = frappe.db.sql(
        """
        SELECT name, account_name, account_number
        FROM `tabAccount`
        WHERE company = 'Ned Ver Vegan'
          AND account_type = 'Expense Account'
          AND is_group = 0
        ORDER BY account_number, name
        LIMIT 20
    """,
        as_dict=True,
    )

    return accounts
