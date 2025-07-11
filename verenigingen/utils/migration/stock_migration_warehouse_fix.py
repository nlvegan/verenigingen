"""
Fix for E-Boekhouden Migration Warehouse Creation

Handles warehouse name normalization and duplicate prevention
"""

import frappe


def get_or_create_migration_warehouse_fixed(company):
    """
    Get or create a warehouse for e-Boekhouden migration with proper duplicate handling

    This fixes the issue where warehouse names get normalized by ERPNext,
    causing duplicate entry errors.
    """

    try:
        # First, try to find existing warehouse by different name patterns
        # ERPNext normalizes company names in warehouse names

        # Pattern 1: Try exact match with normalized company name
        "e-Boekhouden Migration - {company}"
        existing = frappe.db.get_value(
            "Warehouse", {"warehouse_name": "e-Boekhouden Migration", "company": company}, "name"
        )

        if existing:
            return existing

        # Pattern 2: Try with warehouse name containing company
        existing = frappe.db.get_value(
            "Warehouse", {"warehouse_name": ["like", "%e-Boekhouden Migration%"], "company": company}, "name"
        )

        if existing:
            return existing

        # Pattern 3: Try by name field (which is the primary key)
        # This handles cases where company name gets normalized
        existing = frappe.db.sql(
            """
            SELECT name
            FROM `tabWarehouse`
            WHERE company = %s
            AND (name LIKE %s OR warehouse_name LIKE %s)
            LIMIT 1
        """,
            (company, "%e-Boekhouden Migration%", "%e-Boekhouden Migration%"),
        )

        if existing:
            return existing[0][0]

        # If no existing warehouse found, create a new one
        # But first, generate the name to check if it would cause a duplicate
        test_warehouse = frappe.new_doc("Warehouse")
        test_warehouse.warehouse_name = "e-Boekhouden Migration"
        test_warehouse.company = company

        # Get the name that would be generated
        test_warehouse.set_name()
        potential_name = test_warehouse.name

        # Check if this name already exists
        if frappe.db.exists("Warehouse", potential_name):
            # If it exists, return it
            return potential_name

        # Now create the actual warehouse
        warehouse = frappe.new_doc("Warehouse")
        warehouse.warehouse_name = "e-Boekhouden Migration"
        warehouse.company = company
        warehouse.insert(ignore_permissions=True)

        return warehouse.name

    except Exception:
        # If all else fails, try to find ANY warehouse for the company
        # that looks like a migration warehouse
        emergency_warehouse = frappe.db.sql(
            """
            SELECT name
            FROM `tabWarehouse`
            WHERE company = %s
            AND name LIKE '%Boekhouden%'
            LIMIT 1
        """,
            (company,),
        )

        if emergency_warehouse:
            return emergency_warehouse[0][0]

        # Last resort - return the default warehouse for the company
        default_warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")

        if default_warehouse:
            frappe.log_error(
                f"Using default warehouse {default_warehouse} for e-Boekhouden migration",
                "Migration Warehouse Fallback",
            )
            return default_warehouse

        raise Exception(f"No suitable warehouse found or could be created for company {company}")


def clean_duplicate_migration_warehouses(company):
    """
    Clean up any duplicate migration warehouses
    """

    # Find all migration warehouses for the company
    warehouses = frappe.db.sql(
        """
        SELECT name, warehouse_name, creation
        FROM `tabWarehouse`
        WHERE company = %s
        AND (name LIKE '%e-Boekhouden Migration%'
             OR warehouse_name LIKE '%e-Boekhouden Migration%')
        ORDER BY creation ASC
    """,
        (company,),
        as_dict=True,
    )

    if len(warehouses) <= 1:
        return {"cleaned": 0, "kept": len(warehouses)}

    # Keep the first one, delete the rest
    kept = warehouses[0]
    cleaned = 0

    for warehouse in warehouses[1:]:
        try:
            # Check if warehouse has any stock
            has_stock = frappe.db.exists("Stock Ledger Entry", {"warehouse": warehouse.name})

            if not has_stock:
                frappe.delete_doc("Warehouse", warehouse.name, ignore_permissions=True)
                cleaned += 1
        except Exception as e:
            frappe.log_error(
                f"Could not delete duplicate warehouse {warehouse.name}: {str(e)}", "Warehouse Cleanup Error"
            )

    return {"cleaned": cleaned, "kept": 1, "kept_warehouse": kept.name}
