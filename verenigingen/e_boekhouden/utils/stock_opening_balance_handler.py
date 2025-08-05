"""
Stock Opening Balance Handler for E-Boekhouden imports

Handles stock account opening balances by creating Stock Reconciliation entries
instead of trying to update stock accounts directly via Journal Entries.
"""

import frappe
from frappe.utils import flt, getdate


def create_stock_reconciliation_for_opening_balance(stock_accounts_data, company, debug_info):
    """
    Create Stock Reconciliation entries for stock account opening balances.

    Args:
        stock_accounts_data: List of dicts with 'account' and 'balance' keys
        company: Company name
        debug_info: List to append debug messages

    Returns:
        dict: Success status and created document names
    """
    if not stock_accounts_data:
        return {"success": True, "message": "No stock accounts to process"}

    try:
        # Get default warehouse - needed for Stock Reconciliation
        warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")

        if not warehouse:
            # Create a default warehouse if none exists
            warehouse_doc = frappe.new_doc("Warehouse")
            warehouse_doc.warehouse_name = "Main Warehouse"
            warehouse_doc.company = company
            warehouse_doc.save()
            warehouse = warehouse_doc.name
            debug_info.append(f"Created default warehouse: {warehouse}")

        created_reconciliations = []

        for stock_data in stock_accounts_data:
            account = stock_data["account"]
            balance = flt(stock_data["balance"])

            if abs(balance) < 0.01:
                debug_info.append(f"Skipping stock account {account} - zero balance")
                continue

            # Create or find a default item for this stock account
            item_code = _get_or_create_stock_item_for_account(account, company, debug_info)

            if not item_code:
                debug_info.append(f"Could not create/find item for stock account {account}")
                continue

            # Create Stock Reconciliation
            stock_reco = frappe.new_doc("Stock Reconciliation")
            stock_reco.company = company
            stock_reco.posting_date = "2018-01-01"  # Opening balance date
            stock_reco.posting_time = "00:00:00"
            stock_reco.purpose = "Opening Stock"
            stock_reco.expense_account = account  # Use the stock account from E-Boekhouden

            # Calculate quantity based on balance
            # For opening balances, we'll assume a standard rate of €1.00 per unit
            # This means quantity = balance amount
            qty = abs(balance)
            rate = 1.00

            stock_reco.append(
                "items",
                {
                    "item_code": item_code,
                    "warehouse": warehouse,
                    "qty": qty,
                    "valuation_rate": rate,
                    "amount": balance,
                },
            )

            try:
                stock_reco.save()
                stock_reco.submit()
                created_reconciliations.append(stock_reco.name)
                debug_info.append(
                    f"Created Stock Reconciliation {stock_reco.name} for {account}: "
                    f"Qty={qty}, Rate={rate}, Amount={balance}"
                )

            except Exception as e:
                debug_info.append(f"Error creating Stock Reconciliation for {account}: {str(e)}")
                continue

        return {
            "success": True,
            "created_reconciliations": created_reconciliations,
            "message": f"Created {len(created_reconciliations)} Stock Reconciliation entries",
        }

    except Exception as e:
        debug_info.append(f"Error in stock reconciliation process: {str(e)}")
        return {"success": False, "error": str(e)}


def _get_or_create_stock_item_for_account(account, company, debug_info):
    """
    Get or create a stock item for the given stock account.

    Args:
        account: Stock account name
        company: Company name
        debug_info: List to append debug messages

    Returns:
        str: Item code or None if failed
    """
    try:
        # Extract account name for item naming
        account_parts = account.split(" - ")
        if len(account_parts) > 1:
            account_name = account_parts[1]  # e.g., "Voorraden" from "30000 - Voorraden - NVV"
        else:
            account_name = account.replace(" ", "_")

        # Create item code based on account
        item_code = f"STOCK_{account_name.upper().replace(' ', '_')}"

        # Check if item already exists
        if frappe.db.exists("Item", item_code):
            debug_info.append(f"Using existing item: {item_code}")
            return item_code

        # Create new stock item
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = f"Stock Item for {account_name}"
        item.item_group = "Raw Material"  # Default item group
        item.stock_uom = "Nos"  # Default UOM
        item.is_stock_item = 1
        item.include_item_in_manufacturing = 0
        item.valuation_method = "FIFO"

        item.save()
        debug_info.append(f"Created stock item: {item_code} for account {account}")
        return item_code

    except Exception as e:
        debug_info.append(f"Error creating stock item for {account}: {str(e)}")
        return None


@frappe.whitelist()
def test_stock_reconciliation():
    """Test function to verify stock reconciliation creation"""
    debug_info = []

    # Test data
    stock_accounts_data = [{"account": "30000 - Voorraden - NVV", "balance": 1057.06}]

    result = create_stock_reconciliation_for_opening_balance(stock_accounts_data, "Ned Ver Vegan", debug_info)

    return {"result": result, "debug_info": debug_info}
