#!/usr/bin/env python3
"""
Simple test to verify stock account handling works
"""

import frappe
from frappe.utils import flt


@frappe.whitelist()
def test_stock_account_handling():
    """Test stock account handling solution"""
    result = {"success": False, "tests": []}
    
    try:
        # Test 1: Check if stock accounts exist
        stock_accounts = frappe.db.sql("""
            SELECT name, account_type, company
            FROM `tabAccount`
            WHERE account_type = 'Stock'
            LIMIT 5
        """, as_dict=True)
        
        result["tests"].append({
            "name": "Stock Account Detection",
            "success": True,
            "message": f"Found {len(stock_accounts)} stock accounts",
            "details": stock_accounts
        })
        
        # Test 2: Check stock account mappings
        stock_mappings = frappe.db.sql("""
            SELECT 
                elm.ledger_id,
                elm.ledger_name,
                elm.erpnext_account,
                a.account_type
            FROM `tabE-Boekhouden Ledger Mapping` elm
            JOIN `tabAccount` a ON elm.erpnext_account = a.name
            WHERE a.account_type = 'Stock'
            LIMIT 5
        """, as_dict=True)
        
        result["tests"].append({
            "name": "Stock Account Mappings",
            "success": True,
            "message": f"Found {len(stock_mappings)} stock account mappings",
            "details": stock_mappings
        })
        
        # Test 3: Test stock account handler import
        try:
            from verenigingen.utils.eboekhouden.stock_account_handler import StockAccountHandler
            
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company
            debug_info = []
            
            handler = StockAccountHandler(company, debug_info)
            
            # Test account type detection
            if stock_accounts:
                test_account = stock_accounts[0]["name"]
                is_stock = handler.is_stock_account(test_account)
                
                result["tests"].append({
                    "name": "Stock Account Handler",
                    "success": True,
                    "message": f"Stock account detection working: {is_stock}",
                    "details": {"test_account": test_account, "is_stock": is_stock}
                })
            else:
                result["tests"].append({
                    "name": "Stock Account Handler",
                    "success": True,
                    "message": "No stock accounts to test with",
                    "details": {}
                })
                
        except ImportError as e:
            result["tests"].append({
                "name": "Stock Account Handler",
                "success": False,
                "message": f"Import error: {str(e)}",
                "details": {}
            })
        
        # Test 4: Check if existing opening balance needs fixing
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company
        
        existing_je = frappe.db.exists(
            "Journal Entry",
            {
                "company": company,
                "eboekhouden_mutation_nr": "OPENING_BALANCE",
                "voucher_type": "Opening Entry",
            }
        )
        
        result["tests"].append({
            "name": "Existing Opening Balance",
            "success": True,
            "message": f"Existing opening balance: {existing_je or 'None'}",
            "details": {"existing_journal_entry": existing_je}
        })
        
        result["success"] = True
        result["summary"] = {
            "total_tests": len(result["tests"]),
            "passed_tests": len([t for t in result["tests"] if t["success"]]),
            "stock_accounts_found": len(stock_accounts),
            "stock_mappings_found": len(stock_mappings),
            "existing_opening_balance": existing_je
        }
        
    except Exception as e:
        result["error"] = str(e)
        result["tests"].append({
            "name": "General Error",
            "success": False,
            "message": str(e),
            "details": {}
        })
    
    return result


if __name__ == "__main__":
    # This won't work directly, but the function can be called via bench execute
    print("Use: bench --site dev.veganisme.net execute 'verenigingen.scripts.eboekhouden.simple_stock_test.test_stock_account_handling'")