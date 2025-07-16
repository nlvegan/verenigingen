"""
Patch to fix E-Boekhouden migration cost center issue

This patch modifies the create_cost_center method to ensure
root cost center exists before trying to create child cost centers
"""

import frappe


def execute():
    """
    Fix the cost center creation in E-Boekhouden migration
    """

    # Import the fix
    from verenigingen.utils.eboekhouden.eboekhouden_cost_center_fix import ensure_root_cost_center

    # Get all companies that might need fixing
    companies = frappe.get_all("Company", fields=["name"])

    fixed_count = 0

    for company in companies:
        # Check if company has root cost center
        root_cc = frappe.db.get_value(
            "Cost Center", {"company": company.name, "is_group": 1, "parent_cost_center": ""}, "name"
        )

        if not root_cc:
            # Create root cost center
            root_cc = ensure_root_cost_center(company.name)
            if root_cc:
                fixed_count += 1
                frappe.db.commit()
                print(f"Created root cost center for {company.name}")

    if fixed_count > 0:
        print(f"Fixed {fixed_count} companies with missing root cost centers")
    else:
        print("All companies already have root cost centers")
