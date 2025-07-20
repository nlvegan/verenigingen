#!/usr/bin/env python3
"""
Fix Opening Balance Stock Account Issue (EBMIG-2025-00119)

This script analyzes and fixes the stock account issue preventing opening balance import.
It provides multiple solutions based on the user's needs.
"""

import frappe
from frappe.utils import flt
import json


def main():
    """Main function to analyze and fix stock account issues"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    
    print("=== Opening Balance Stock Account Fix (EBMIG-2025-00119) ===")
    print()
    
    try:
        # Step 1: Analyze the issue
        print("1. Analyzing stock accounts in opening balances...")
        analysis_result = analyze_stock_accounts()
        
        if not analysis_result.get("success"):
            print(f"❌ Analysis failed: {analysis_result.get('error')}")
            return
        
        stock_accounts = analysis_result.get("stock_accounts", [])
        
        if not stock_accounts:
            print("✅ No stock accounts found in opening balances - issue may be resolved")
            return
        
        print(f"📊 Found {len(stock_accounts)} stock accounts:")
        for acc in stock_accounts:
            print(f"   - {acc['account']}: €{acc['balance']:.2f}")
        
        print()
        
        # Step 2: Show options
        print("2. Available solutions:")
        print("   a) Skip stock accounts (recommended)")
        print("   b) Analyze stock account mappings")
        print("   c) Import opening balances with stock filtering")
        print("   d) Show detailed stock account report")
        print()
        
        choice = input("Choose an option (a/b/c/d): ").lower().strip()
        
        if choice == "a":
            skip_stock_accounts_solution()
        elif choice == "b":
            analyze_stock_mappings()
        elif choice == "c":
            import_with_stock_filtering()
        elif choice == "d":
            show_detailed_report(stock_accounts)
        else:
            print("Invalid choice. Exiting.")
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        frappe.destroy()


def analyze_stock_accounts():
    """Analyze stock accounts in opening balances"""
    try:
        from verenigingen.utils.eboekhouden.stock_account_handler import analyze_stock_accounts_in_opening_balances
        
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company
        
        result = analyze_stock_accounts_in_opening_balances(company)
        return result
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def skip_stock_accounts_solution():
    """Implement the skip stock accounts solution"""
    print("\n=== Solution A: Skip Stock Accounts ===")
    print("This will import opening balances while skipping stock accounts.")
    print("Stock accounts will be excluded from the opening balance journal entry.")
    print()
    
    confirm = input("Proceed with skipping stock accounts? (y/n): ").lower()
    if confirm != 'y':
        print("Operation cancelled.")
        return
    
    try:
        from verenigingen.utils.eboekhouden.stock_account_handler import import_opening_balances_with_stock_handling
        
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company
        
        print("Importing opening balances with stock account filtering...")
        result = import_opening_balances_with_stock_handling(
            company=company,
            stock_handling_method="skip_stock_accounts"
        )
        
        if result.get("success"):
            print("✅ Opening balances imported successfully!")
            print(f"   - Journal Entry: {result.get('import_result', {}).get('journal_entry')}")
            print(f"   - Stock accounts skipped: {result.get('stock_accounts_skipped', 0)}")
            
            skipped = result.get("skipped_accounts", [])
            if skipped:
                print("\n📋 Skipped stock accounts:")
                for acc in skipped:
                    print(f"   - {acc['account']}: €{acc['balance']:.2f} ({acc['reason']})")
                    
        else:
            print(f"❌ Import failed: {result.get('error')}")
            
    except Exception as e:
        print(f"❌ Error during import: {str(e)}")


def analyze_stock_mappings():
    """Analyze stock account mappings"""
    print("\n=== Solution B: Analyze Stock Account Mappings ===")
    print("This will show which eBoekhouden accounts are mapped to ERPNext stock accounts.")
    print()
    
    try:
        # Get all stock account mappings
        stock_mappings = frappe.db.sql("""
            SELECT 
                elm.ledger_id,
                elm.ledger_name,
                elm.erpnext_account,
                a.account_type,
                a.root_type
            FROM `tabE-Boekhouden Ledger Mapping` elm
            JOIN `tabAccount` a ON elm.erpnext_account = a.name
            WHERE a.account_type = 'Stock'
            ORDER BY elm.ledger_id
        """, as_dict=True)
        
        if not stock_mappings:
            print("✅ No stock account mappings found.")
            return
        
        print(f"📊 Found {len(stock_mappings)} stock account mappings:")
        print()
        
        for mapping in stock_mappings:
            print(f"eBoekhouden Ledger: {mapping['ledger_id']} - {mapping['ledger_name']}")
            print(f"ERPNext Account: {mapping['erpnext_account']}")
            print(f"Account Type: {mapping['account_type']}")
            print("---")
        
        print("\n💡 Recommendations:")
        print("1. If you don't use stock accounting, consider remapping these to Asset accounts")
        print("2. If you do use stock, set up Stock Reconciliation instead of opening balances")
        print("3. For now, skip stock accounts during opening balance import")
        
    except Exception as e:
        print(f"❌ Error analyzing mappings: {str(e)}")


def import_with_stock_filtering():
    """Import opening balances with stock filtering"""
    print("\n=== Solution C: Import with Stock Filtering ===")
    print("This will run the opening balance import with enhanced stock account filtering.")
    print()
    
    # Check if already imported
    settings = frappe.get_single("E-Boekhouden Settings")
    company = settings.default_company
    
    existing = frappe.db.exists(
        "Journal Entry",
        {
            "company": company,
            "eboekhouden_mutation_nr": "OPENING_BALANCE",
            "voucher_type": "Opening Entry",
        }
    )
    
    if existing:
        print(f"⚠️  Opening balances already imported: {existing}")
        overwrite = input("Delete existing and re-import? (y/n): ").lower()
        if overwrite == 'y':
            frappe.delete_doc("Journal Entry", existing)
            frappe.db.commit()
            print("✅ Existing opening balance deleted.")
        else:
            print("Operation cancelled.")
            return
    
    try:
        print("Running opening balance import with stock filtering...")
        
        # Use the enhanced stock handler
        from verenigingen.utils.eboekhouden.stock_account_handler import import_opening_balances_with_stock_handling
        
        result = import_opening_balances_with_stock_handling(
            company=company,
            stock_handling_method="skip_stock_accounts"
        )
        
        if result.get("success"):
            print("✅ Opening balances imported successfully!")
            print(f"   - Journal Entry: {result.get('import_result', {}).get('journal_entry')}")
            print(f"   - Stock accounts skipped: {result.get('stock_accounts_skipped', 0)}")
            
            # Show debug info
            debug_info = result.get("debug_info", [])
            if debug_info:
                print("\n📋 Debug Information:")
                for info in debug_info[-10:]:  # Show last 10 entries
                    print(f"   {info}")
                    
        else:
            print(f"❌ Import failed: {result.get('error')}")
            
    except Exception as e:
        print(f"❌ Error during import: {str(e)}")


def show_detailed_report(stock_accounts):
    """Show detailed stock account report"""
    print("\n=== Solution D: Detailed Stock Account Report ===")
    print()
    
    total_value = sum(flt(acc.get("balance", 0)) for acc in stock_accounts)
    
    print(f"📊 Stock Account Summary:")
    print(f"   Total stock accounts: {len(stock_accounts)}")
    print(f"   Total stock value: €{total_value:.2f}")
    print()
    
    print("📋 Detailed breakdown:")
    for i, acc in enumerate(stock_accounts, 1):
        print(f"{i}. Account: {acc['account']}")
        print(f"   eBoekhouden Ledger: {acc['ledger_id']}")
        print(f"   Balance: €{acc['balance']:.2f}")
        print(f"   Description: {acc.get('description', 'N/A')}")
        print()
    
    print("💡 Why this happens:")
    print("   - ERPNext restricts stock account updates to Stock transactions only")
    print("   - Journal entries cannot directly update stock accounts")
    print("   - Stock balances should be set via Stock Reconciliation")
    print()
    
    print("🔧 Recommended solutions:")
    print("   1. Skip stock accounts during opening balance import (safest)")
    print("   2. Remap stock accounts to generic Asset accounts if not using stock")
    print("   3. Set up Stock Reconciliation for actual stock management")
    print()


if __name__ == "__main__":
    main()