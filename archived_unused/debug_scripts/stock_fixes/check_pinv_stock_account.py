"""
Check Purchase Invoices and Stock Account Usage
"""

import frappe


@frappe.whitelist()
def check_purchase_invoice_details():
    """Check recent Purchase Invoices to understand stock account usage"""

    try:
        # Get recent Purchase Invoices
        purchase_invoices = frappe.get_all(
            "Purchase Invoice",
            filters={"docstatus": ["!=", 2], "creation": [">", "2024-01-01"]},  # Not cancelled
            fields=["name", "supplier", "posting_date", "total", "docstatus"],
            order_by="creation desc",
            limit=5,
        )

        results = []

        for pinv in purchase_invoices:
            # Get the full document
            doc = frappe.get_doc("Purchase Invoice", pinv.name)

            pinv_details = {
                "name": doc.name,
                "supplier": doc.supplier,
                "posting_date": str(doc.posting_date),
                "total": doc.total,
                "docstatus": doc.docstatus,
                "update_stock": doc.update_stock,
                "items": [],
            }

            # Check each item
            for item in doc.items:
                item_details = {
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "qty": item.qty,
                    "rate": item.rate,
                    "expense_account": item.expense_account,
                    "is_stock_item": False,
                    "item_group": None,
                }

                # Get item details
                if frappe.db.exists("Item", item.item_code):
                    item_doc = frappe.get_doc("Item", item.item_code)
                    item_details["is_stock_item"] = item_doc.is_stock_item
                    item_details["item_group"] = item_doc.item_group
                    item_details["maintain_stock"] = item_doc.is_stock_item

                pinv_details["items"].append(item_details)

            results.append(pinv_details)

        return {"success": True, "purchase_invoices": results, "count": len(results)}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def check_company_stock_settings():
    """Check company settings related to stock accounting"""

    try:
        company = frappe.get_doc("Company", "Ned Ver Vegan")

        settings = {
            "enable_perpetual_inventory": company.enable_perpetual_inventory,
            "stock_received_but_not_billed": company.stock_received_but_not_billed,
            "stock_adjustment_account": company.stock_adjustment_account,
            "default_inventory_account": company.default_inventory_account,
            "default_expense_account": company.default_expense_account,
            "expense_account": company.expense_account if hasattr(company, "expense_account") else None,
        }

        # Check if accounts exist (create a copy to avoid modifying dict during iteration)
        account_details = {}
        for key, account in list(settings.items()):
            if account and frappe.db.exists("Account", account):
                acc_doc = frappe.get_doc("Account", account)
                account_details["{key}_details"] = {
                    "account_name": acc_doc.account_name,
                    "account_type": acc_doc.account_type,
                    "exists": True,
                }
            elif account:
                account_details["{key}_details"] = {"exists": False, "value": account}

        # Merge the details back
        settings.update(account_details)

        return {"success": True, "company_settings": settings}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def check_eboekhouden_items():
    """Check items created by E-Boekhouden migration"""

    try:
        # Get items used in E-Boekhouden migration
        items = frappe.get_all(
            "Item",
            filters=[
                [
                    "item_code",
                    "in",
                    [
                        "EB-GENERIC-EXPENSE",
                        "EB-GENERIC-INCOME",
                        "E-Boekhouden-Generic",
                        "E-Boekhouden Import Item",
                    ],
                ]
            ],
            fields=["name", "item_name", "item_group", "is_stock_item"],
            limit=10,
        )

        item_details = []

        for item in items:
            item_doc = frappe.get_doc("Item", item.name)

            details = {
                "item_code": item_doc.item_code,
                "item_name": item_doc.item_name,
                "item_group": item_doc.item_group,
                "is_stock_item": item_doc.is_stock_item,
                "is_purchase_item": item_doc.is_purchase_item,
                "is_sales_item": item_doc.is_sales_item,
                "stock_uom": item_doc.stock_uom,
                "has_variants": item_doc.has_variants,
                "maintain_stock": item_doc.is_stock_item,
            }

            # Check item defaults
            if item_doc.item_defaults:
                details["defaults"] = []
                for default in item_doc.item_defaults:
                    details["defaults"].append(
                        {
                            "company": default.company,
                            "expense_account": default.expense_account,
                            "income_account": default.income_account,
                        }
                    )

            item_details.append(details)

        return {"success": True, "items": item_details, "count": len(item_details)}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
