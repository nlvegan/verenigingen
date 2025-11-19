#!/usr/bin/env python3
"""
Debug opening balance import to see what's actually happening
"""
import frappe
import json

def debug_opening_balances():
    from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI
    
    api = EBoekhoudenAPI()
    result = api.make_request("v1/mutation", method="GET", params={"type": 0})
    
    if not result or not result.get("success"):
        print(f"API call failed: {result}")
        return
    
    mutations_data = json.loads(result.get("data", "[]"))
    
    if isinstance(mutations_data, dict):
        if "items" in mutations_data:
            mutations_data = mutations_data["items"]
        else:
            mutations_data = list(mutations_data.values())
    
    print(f"\nTotal opening balance mutations: {len(mutations_data)}\n")
    print("=" * 100)
    
    for i, mut in enumerate(mutations_data, 1):
        ledger_id = mut.get("ledgerId")
        amount = mut.get("amount", mut.get("balance", 0))
        desc = mut.get("description", "")
        
        # Check if mapping exists
        mapping = frappe.db.sql("""
            SELECT erpnext_account, ledger_code, ledger_name
            FROM `tabE-Boekhouden Ledger Mapping`
            WHERE ledger_id = %s
        """, ledger_id, as_dict=True)
        
        if mapping:
            account_name = mapping[0].get("erpnext_account")
            ledger_code = mapping[0].get("ledger_code")
            ledger_name = mapping[0].get("ledger_name")
            
            # Check if account exists
            if frappe.db.exists("Account", account_name):
                account = frappe.db.get_value("Account", account_name,
                    ["root_type", "account_type"], as_dict=True)
                status = f"✓ {account.root_type}"
                if account.account_type:
                    status += f" ({account.account_type})"
            else:
                status = "✗ ACCOUNT NOT FOUND"
        else:
            ledger_code = "?"
            ledger_name = "NO MAPPING"
            account_name = "N/A"
            status = "✗ NO MAPPING"
        
        print(f"{i:2}. Ledger {ledger_id} | Code: {ledger_code:6} | {ledger_name:40} | Amount: {amount:12.2f}")
        print(f"    → {account_name}")
        print(f"    → {status}")
        print()

if __name__ == "__main__":
    debug_opening_balances()
