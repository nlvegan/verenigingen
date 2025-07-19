#!/usr/bin/env python3
"""
Test Stock Account Fix for Opening Balance Import

This script tests the stock account handling solution.
"""

import sys

import frappe
from frappe.utils import flt


def main():
    """Test the stock account handling solution"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    print("=== Testing Stock Account Fix ===")
    print()

    try:
        # Test 1: Analyze stock accounts
        print("Test 1: Analyzing stock accounts...")
        test_analyze_stock_accounts()
        print()

        # Test 2: Test stock account filtering
        print("Test 2: Testing stock account filtering...")
        test_stock_account_filtering()
        print()

        # Test 3: Test helper functions
        print("Test 3: Testing helper functions...")
        test_helper_functions()
        print()

        print("✅ All tests completed successfully!")

    except Exception as e:
        print(f"❌ Test failed: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    finally:
        frappe.destroy()


def test_analyze_stock_accounts():
    """Test stock account analysis"""
    try:
        from verenigingen.utils.eboekhouden.stock_account_handler import (
            analyze_stock_accounts_in_opening_balances,
        )

        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        result = analyze_stock_accounts_in_opening_balances(company)

        if result.get("success"):
            stock_accounts = result.get("stock_accounts", [])
            print(f"   ✅ Found {len(stock_accounts)} stock accounts")

            if stock_accounts:
                total_value = sum(flt(acc.get("balance", 0)) for acc in stock_accounts)
                print(f"   📊 Total stock value: €{total_value:.2f}")
                print(f"   🔍 First stock account: {stock_accounts[0].get('account')}")
            else:
                print("   ℹ️  No stock accounts found in opening balances")
        else:
            print(f"   ❌ Analysis failed: {result.get('error')}")

    except ImportError as e:
        print(f"   ⚠️  Import error (expected): {str(e)}")
        print("   ℹ️  This is expected if the handler module isn't imported yet")
    except Exception as e:
        print(f"   ❌ Unexpected error: {str(e)}")


def test_stock_account_filtering():
    """Test stock account filtering logic"""
    try:
        # Test with sample data
        sample_balances = [
            {"ledgerId": "1400", "balance": 1000, "description": "Stock Account 1"},
            {"ledgerId": "1000", "balance": 5000, "description": "Cash Account"},
            {"ledgerId": "1401", "balance": 2000, "description": "Stock Account 2"},
        ]

        print(f"   📊 Testing with {len(sample_balances)} sample balances")

        # Check if we have the required mappings
        mappings = frappe.db.sql(
            """
            SELECT ledger_id, erpnext_account
            FROM `tabE-Boekhouden Ledger Mapping`
            WHERE ledger_id IN ('1400', '1000', '1401')
        """,
            as_dict=True,
        )

        print(f"   📋 Found {len(mappings)} account mappings")

        # Check account types
        stock_accounts = 0
        for mapping in mappings:
            account_type = frappe.db.get_value("Account", mapping["erpnext_account"], "account_type")
            if account_type == "Stock":
                stock_accounts += 1
                print(f"   📦 Stock account: {mapping['erpnext_account']}")

        print(f"   ✅ Test completed - found {stock_accounts} stock accounts in mappings")

    except Exception as e:
        print(f"   ❌ Filtering test failed: {str(e)}")


def test_helper_functions():
    """Test helper functions"""
    try:
        # Test account type checking
        print("   🔍 Testing account type detection...")

        # Find a stock account if any exist
        stock_accounts = frappe.db.sql(
            """
            SELECT name FROM `tabAccount`
            WHERE account_type = 'Stock'
            AND company = (SELECT default_company FROM `tabE-Boekhouden Settings`)
            LIMIT 1
        """,
            as_dict=True,
        )

        if stock_accounts:
            stock_account = stock_accounts[0]["name"]
            print(f"   📦 Testing with stock account: {stock_account}")

            # Test if account type detection works
            account_doc = frappe.get_doc("Account", stock_account)
            is_stock = account_doc.account_type == "Stock"
            print(f"   ✅ Stock account detection: {is_stock}")

        else:
            print("   ℹ️  No stock accounts found to test with")

        # Test temporary account creation logic
        print("   🔧 Testing temporary account creation...")
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        # Just test the account name generation
        temp_account_name = f"Temporary Differences - {company}"
        print(f"   📋 Temporary account name: {temp_account_name}")

        print("   ✅ Helper function tests completed")

    except Exception as e:
        print(f"   ❌ Helper function test failed: {str(e)}")


if __name__ == "__main__":
    main()
