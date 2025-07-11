#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def check_projects_and_cost_centers():
    """Check existing projects and cost centers in the system"""

    result = {}

    # Check projects
    try:
        projects = frappe.get_all("Project", fields=["name", "project_name", "status", "cost_center"])
        result["projects"] = projects
    except Exception as e:
        result["projects"] = f"Error: {e}"

    # Check cost centers
    try:
        cost_centers = frappe.get_all(
            "Cost Center", fields=["name", "cost_center_name", "parent_cost_center", "is_group"]
        )
        result["cost_centers"] = cost_centers
    except Exception as e:
        result["cost_centers"] = f"Error: {e}"

    # Check account groups
    try:
        account_groups = frappe.get_all(
            "Account",
            filters={"is_group": 1, "root_type": ["in", ["Income", "Expense"]]},
            fields=["name", "account_name", "root_type", "parent_account"],
        )
        result["account_groups"] = account_groups
    except Exception as e:
        result["account_groups"] = f"Error: {e}"

    return result
