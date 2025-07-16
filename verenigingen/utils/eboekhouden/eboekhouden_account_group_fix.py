"""
Fix E-Boekhouden account group settings
Identifies which accounts should be groups based on hierarchy
"""

import json

import frappe


def analyze_account_hierarchy(accounts_data):
    """
    Analyze account hierarchy to determine which accounts should be groups
    UPDATED: Don't use account number hierarchy - only use explicit group indicators

    Args:
        accounts_data: List of account data from E-Boekhouden

    Returns:
        set: Set of account codes that should be groups (very conservative)
    """
    group_accounts = set()

    # Only mark accounts as groups if they have explicit group indicators in the name
    for account in accounts_data:
        code = account.get("code", "")
        name = account.get("description", "").lower()

        # Very conservative indicators of group accounts in Dutch
        # Only mark as group if explicitly named as such
        group_indicators = [
            "totaal",
            "total",
            "subtotaal",
            "subtotal",
            "hoofdgroep",
            "subgroep",
            "categorie groep",
        ]

        # Only mark as group if the name explicitly indicates it's a grouping account
        if any(indicator in name for indicator in group_indicators):
            group_accounts.add(code)
            frappe.logger().info(f"Marking {code} as group due to name indicator: {name}")

    # Log the conservative approach
    frappe.logger().info(f"Conservative group detection: {len(group_accounts)} accounts marked as groups")

    return group_accounts


@frappe.whitelist()
def fix_account_groups():
    """
    Fix existing accounts that should be groups
    """
    try:
        from verenigingen.utils.eboekhouden.eboekhouden_api import EBoekhoudenAPI

        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        # Get chart of accounts
        result = api.get_chart_of_accounts()
        if not result["success"]:
            return {"success": False, "error": "Failed to get chart of accounts"}

        data = json.loads(result["data"])
        accounts_data = data.get("items", [])

        # Analyze which accounts should be groups
        group_accounts = analyze_account_hierarchy(accounts_data)

        # Get company
        company = settings.default_company
        if not company:
            return {"success": False, "error": "No default company set"}

        fixed_accounts = []
        errors = []

        # Fix existing accounts
        for account_code in group_accounts:
            try:
                # Check if account exists
                account_name = frappe.db.get_value(
                    "Account", {"account_number": account_code, "company": company}, "name"
                )

                if account_name:
                    # Check if it's already a group
                    is_group = frappe.db.get_value("Account", account_name, "is_group")

                    if not is_group:
                        # Check if it has any GL entries
                        has_gl_entries = frappe.db.exists("GL Entry", {"account": account_name})

                        if not has_gl_entries:
                            # Safe to convert to group
                            frappe.db.set_value("Account", account_name, "is_group", 1)
                            fixed_accounts.append("{account_code} - {account_name}")
                            frappe.logger().info(f"Converted account {account_code} to group")
                        else:
                            errors.append(f"{account_code} has GL entries, cannot convert to group")

            except Exception as e:
                errors.append(f"Error fixing {account_code}: {str(e)}")

        # Also fix any root accounts (accounts without parent)
        root_accounts = frappe.db.get_all(
            "Account",
            {"company": company, "parent_account": ["in", ["", None]], "is_group": 0},
            ["name", "account_number"],
        )

        for acc in root_accounts:
            try:
                # Check if it has any GL entries
                has_gl_entries = frappe.db.exists("GL Entry", {"account": acc.name})

                if not has_gl_entries:
                    frappe.db.set_value("Account", acc.name, "is_group", 1)
                    fixed_accounts.append("{acc.account_number or 'No number'} - {acc.name} (root account)")
                    frappe.logger().info(f"Converted root account {acc.name} to group")
                else:
                    errors.append(f"Root account {acc.name} has GL entries, cannot convert to group")

            except Exception as e:
                errors.append(f"Error fixing root account {acc.name}: {str(e)}")

        frappe.db.commit()

        return {
            "success": True,
            "fixed": len(fixed_accounts),
            "fixed_accounts": fixed_accounts[:10],  # Show first 10
            "errors": errors,
            "message": "Fixed {len(fixed_accounts)} accounts as groups",
        }

    except Exception as e:
        frappe.log_error(title="Fix Account Groups Error", message=str(e) + "\n" + frappe.get_traceback())
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_problem_accounts():
    """
    Check for the specific problem accounts mentioned
    """
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        if not company:
            return {"success": False, "error": "No default company set"}

        # Problem accounts mentioned
        problem_codes = ["80008", "80006", "83291"]

        results = []

        for code in problem_codes:
            account = frappe.db.get_value(
                "Account",
                {"account_number": code, "company": company},
                ["name", "parent_account", "is_group", "root_type"],
                as_dict=True,
            )

            if account:
                has_gl = frappe.db.exists("GL Entry", {"account": account.name})
                has_children = frappe.db.exists("Account", {"parent_account": account.name})

                results.append(
                    {
                        "code": code,
                        "name": account.name,
                        "parent": account.parent_account or "None (Root Account)",
                        "is_group": "Yes" if account.is_group else "No",
                        "root_type": account.root_type,
                        "has_gl_entries": "Yes" if has_gl else "No",
                        "has_children": "Yes" if has_children else "No",
                        "can_fix": "Yes" if not has_gl and not account.is_group else "No",
                    }
                )
            else:
                results.append({"code": code, "status": "Not found in system"})

        return {"success": True, "accounts": results}

    except Exception as e:
        return {"success": False, "error": str(e)}
