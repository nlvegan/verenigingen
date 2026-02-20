"""
ANBI Account Group Setup

Creates account groups for ANBI-compliant financial reporting:
- Expense groups: Doelstelling, Werving baten, Beheer & administratie
- Income groups: Subsidies (already exists as 8060)
"""
import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, critical_api, standard_api


def get_company():
    """Get company from Verenigingen Settings with proper fallback."""
    company = frappe.db.get_single_value("Verenigingen Settings", "company")
    if not company:
        company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        frappe.throw(_("No company configured in Verenigingen Settings or Global Defaults"))
    return company


@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)
def get_account_groups():
    """Get all Income/Expense account groups in the Chart of Accounts."""
    company = get_company()

    total = frappe.db.count("Account", {"company": company})
    groups = frappe.db.count("Account", {"company": company, "is_group": 1})

    accounts = frappe.db.sql(
        """
        SELECT account_number, name, is_group, root_type, parent_account
        FROM `tabAccount`
        WHERE company = %s
        AND root_type IN ('Income', 'Expense')
        ORDER BY root_type DESC, CAST(account_number AS UNSIGNED), name
        """,
        (company,),
        as_dict=True,
    )

    result = []
    for a in accounts:
        result.append(
            {
                "number": a.account_number or "N/A",
                "name": a.name,
                "root_type": a.root_type,
                "parent": a.parent_account,
                "is_group": a.is_group,
            }
        )

    return {
        "success": True,
        "company": company,
        "total_accounts": total,
        "total_groups": groups,
        "accounts": result,
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_anbi_account_groups():
    """Create ANBI-compliant expense account groups.

    Creates three parent groups under Kosten for ANBI reporting:
    - 61: Besteed aan doelstellingen (program costs)
    - 62: Kosten werving baten (fundraising costs)
    - 63: Beheer en administratie (admin/overhead)
    """
    # Verify permission to create accounts
    if not frappe.has_permission("Account", "create"):
        frappe.throw(_("Insufficient permissions to create accounts"), frappe.PermissionError)

    company = get_company()
    results = {"success": True, "created": [], "existing": [], "errors": []}

    # Find Kosten parent account
    kosten_parent = frappe.db.get_value(
        "Account", {"company": company, "account_number": "6", "is_group": 1}, "name"
    )
    if not kosten_parent:
        # Try by name pattern
        kosten_parent = frappe.db.get_value(
            "Account", {"company": company, "name": ["like", "6 - Kosten%"], "is_group": 1}, "name"
        )

    if not kosten_parent:
        return {"success": False, "error": _("Could not find Kosten (6) parent account")}

    # ANBI Expense Groups
    expense_groups = [
        {
            "account_number": "61",
            "account_name": "Besteed aan doelstellingen",
            "description": "ANBI: Programmakosten, voorlichting, educatie, evenementen",
        },
        {
            "account_number": "62",
            "account_name": "Kosten werving baten",
            "description": "ANBI: Ledenwerving, donateurswerving, fondsenwerving",
        },
        {
            "account_number": "63",
            "account_name": "Beheer en administratie",
            "description": "ANBI: Kantoorkosten, accountancy, bankkosten, overhead",
        },
    ]

    for group_config in expense_groups:
        try:
            # Check if already exists
            existing = frappe.db.get_value(
                "Account", {"company": company, "account_number": group_config["account_number"]}, "name"
            )

            if existing:
                results["existing"].append(existing)
                continue

            # Create account group
            account = frappe.new_doc("Account")
            account.company = company
            account.account_name = group_config["account_name"]
            account.account_number = group_config["account_number"]
            account.parent_account = kosten_parent
            account.root_type = "Expense"
            account.account_type = "Expense Account"
            account.is_group = 1
            account.insert()

            results["created"].append(account.name)

        except Exception as e:
            frappe.log_error(
                message=f"Failed to create ANBI account {group_config['account_name']}: {str(e)}",
                title="ANBI Account Creation Error",
            )
            results["errors"].append(
                {
                    "account": group_config["account_name"],
                    "error": _("Failed to create account. See error log for details."),
                }
            )

    if results["created"] or results["existing"]:
        frappe.db.commit()

    results["summary"] = {
        "created": len(results["created"]),
        "already_existed": len(results["existing"]),
        "errors": len(results["errors"]),
    }

    return results
