#!/usr/bin/env python
"""Test nested account cleanup"""

import frappe
from frappe import _


@frappe.whitelist()
def test_nested_cleanup():
    """Test the updated cleanup_chart_of_accounts function with nested accounts"""

    # Get default company
    settings = frappe.get_single("E-Boekhouden Settings")
    company = settings.default_company if settings else None

    if not company:
        return {"error": "No default company configured"}

    results = {"company": company}

    # First, check what E-Boekhouden accounts exist
    eb_accounts = frappe.get_all(
        "Account",
        filters={"company": company, "eboekhouden_grootboek_nummer": ["is", "set"]},
        fields=["name", "account_name", "is_group", "parent_account", "lft", "rgt"],
        order_by="lft",
    )

    results["before_cleanup"] = {
        "total_accounts": len(eb_accounts),
        "group_accounts": [acc for acc in eb_accounts if acc.is_group],
        "leaf_accounts": [acc for acc in eb_accounts if not acc.is_group],
    }

    # Check specific problematic account
    problem_account = frappe.db.get_value(
        "Account",
        {"account_name": "EIGEN VERMOGEN - NVV", "company": company},
        ["name", "lft", "rgt", "is_group"],
        as_dict=True,
    )

    if problem_account:
        # Get its children
        children = frappe.get_all(
            "Account",
            filters={
                "lft": [">", problem_account.lft],
                "rgt": ["<", problem_account.rgt],
                "company": company,
            },
            fields=["name", "account_name", "is_group"],
            order_by="lft",
        )
        results["problem_account"] = {
            "account": problem_account,
            "children": children,
            "child_count": len(children),
        }

    # Now test the cleanup
    from verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration import (
        cleanup_chart_of_accounts,
    )

    try:
        cleanup_result = cleanup_chart_of_accounts(company)
        results["cleanup_result"] = cleanup_result
        results["cleanup_success"] = True
    except Exception as e:
        results["cleanup_error"] = str(e)
        results["cleanup_success"] = False
        import traceback

        results["cleanup_traceback"] = traceback.format_exc()

    # Check what's left after cleanup
    remaining_accounts = frappe.get_all(
        "Account",
        filters={"company": company, "eboekhouden_grootboek_nummer": ["is", "set"]},
        fields=["name", "account_name"],
        order_by="name",
    )

    results["after_cleanup"] = {
        "total_accounts": len(remaining_accounts),
        "remaining_accounts": remaining_accounts,
    }

    return results


@frappe.whitelist()
def check_account_hierarchy():
    """Check the account hierarchy for debugging"""

    settings = frappe.get_single("E-Boekhouden Settings")
    company = settings.default_company if settings else None

    if not company:
        return {"error": "No default company configured"}

    # Get all E-Boekhouden accounts with hierarchy info
    accounts = frappe.db.sql(
        """
        SELECT
            name, account_name, parent_account, is_group,
            lft, rgt, (rgt - lft - 1) / 2 as child_count
        FROM tabAccount
        WHERE company = %s
        AND eboekhouden_grootboek_nummer IS NOT NULL
        ORDER BY lft
    """,
        company,
        as_dict=True,
    )

    # Build hierarchy
    hierarchy = []
    for acc in accounts:
        level = len([a for a in accounts if a.lft < acc.lft and a.rgt > acc.rgt])
        hierarchy.append(
            {
                "name": acc.name,
                "account_name": acc.account_name,
                "level": level,
                "is_group": acc.is_group,
                "child_count": int(acc.child_count),
                "parent": acc.parent_account,
            }
        )

    return {"total_accounts": len(accounts), "hierarchy": hierarchy}


if __name__ == "__main__":
    result = test_nested_cleanup()
    print(f"Result: {result}")
