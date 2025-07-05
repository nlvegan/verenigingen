"""
Disable perpetual inventory for Ned Ver Vegan
"""

import frappe


@frappe.whitelist()
def disable_perpetual_inventory():
    """Disable perpetual inventory since we don't manage physical stock"""

    try:
        company = frappe.get_doc("Company", "Ned Ver Vegan")

        # Store current setting
        current_setting = company.enable_perpetual_inventory

        # Disable perpetual inventory
        company.enable_perpetual_inventory = 0
        company.save()

        return {
            "success": True,
            "message": f"Perpetual inventory disabled for {company.name}",
            "previous_setting": current_setting,
            "current_setting": 0,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def check_stock_implications():
    """Check if disabling perpetual inventory would have any implications"""

    try:
        # Check for any stock items
        stock_items = frappe.get_all(
            "Item", filters={"is_stock_item": 1}, fields=["name", "item_name"], limit=10
        )

        # Check for any Purchase Invoices that update stock
        stock_pinvs = frappe.get_all(
            "Purchase Invoice",
            filters={"update_stock": 1, "docstatus": ["!=", 2]},
            fields=["name", "supplier", "posting_date"],
            limit=10,
        )

        # Check for any Sales Invoices that update stock
        stock_sinvs = frappe.get_all(
            "Sales Invoice",
            filters={"update_stock": 1, "docstatus": ["!=", 2]},
            fields=["name", "customer", "posting_date"],
            limit=10,
        )

        # Check for stock entries
        stock_entries = frappe.get_all(
            "Stock Entry",
            filters={"docstatus": ["!=", 2]},
            fields=["name", "stock_entry_type", "posting_date"],
            limit=10,
        )

        has_stock_transactions = bool(stock_items or stock_pinvs or stock_sinvs or stock_entries)

        return {
            "success": True,
            "has_stock_transactions": has_stock_transactions,
            "stock_items_count": len(stock_items),
            "stock_purchase_invoices_count": len(stock_pinvs),
            "stock_sales_invoices_count": len(stock_sinvs),
            "stock_entries_count": len(stock_entries),
            "stock_items": stock_items,
            "recommendation": "Safe to disable perpetual inventory"
            if not has_stock_transactions
            else "Review stock transactions before disabling",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
