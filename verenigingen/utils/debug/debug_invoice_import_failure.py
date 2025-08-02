#!/usr/bin/env python3
"""
Debug the Sales Invoice import failure issue
"""

import json

import frappe


def analyze_invoice_import_failure():
    """Analyze why Sales Invoice imports are failing"""

    print("=== Analyzing Sales Invoice Import Failure ===")

    # Check if we can find some E-Boekhouden mutation data
    print("\n--- Checking for E-Boekhouden mutation data ---")

    # Try to find mutation data (check different possible sources)
    # Method 1: Check if there's a REST cache table
    try:
        cache_exists = frappe.db.sql("SHOW TABLES LIKE '%mutation%'")
        print(f"Tables with 'mutation': {cache_exists}")
    except Exception as e:
        print(f"Error checking tables: {str(e)}")

    # Method 2: Check for any E-Boekhouden related doctypes
    try:
        doctypes = frappe.db.sql(
            """
            SELECT name FROM `tabDocType`
            WHERE name LIKE '%boekhouden%' OR name LIKE '%EBH%'
        """,
            as_dict=True,
        )
        print(f"E-Boekhouden related doctypes: {[d['name'] for d in doctypes]}")
    except Exception as e:
        print(f"Error checking doctypes: {str(e)}")

    print("\n--- Testing Account Mapping Function ---")

    # Test the problematic function directly
    try:
        from verenigingen.e_boekhouden.utils.invoice_helpers import map_grootboek_to_erpnext_account

        # Test with None/empty grootboek_nummer (this should be causing the error)
        print("Testing with None grootboek_nummer:")
        try:
            result = map_grootboek_to_erpnext_account(None, "sales", [])
            print(f"Result: {result}")
        except Exception as e:
            print(f"❌ Error (expected): {str(e)}")

        # Test with empty string
        print("Testing with empty grootboek_nummer:")
        try:
            result = map_grootboek_to_erpnext_account("", "sales", [])
            print(f"Result: {result}")
        except Exception as e:
            print(f"❌ Error (expected): {str(e)}")

        # Test with a sample account number
        print("Testing with sample grootboek_nummer '8000':")
        try:
            debug_info = []
            result = map_grootboek_to_erpnext_account("8000", "sales", debug_info)
            print(f"Result: {result}")
            print(f"Debug info: {debug_info}")
        except Exception as e:
            print(f"❌ Error: {str(e)}")

    except ImportError as e:
        print(f"❌ Could not import function: {str(e)}")

    print("\n--- Checking Available Accounts ---")

    # Check what accounts are available in the system
    try:
        company = frappe.db.get_single_value("Global Defaults", "default_company")
        if not company:
            company = frappe.db.get_value("Company", {}, "name")

        print(f"Using company: {company}")

        # Check for income accounts
        income_accounts = frappe.db.sql(
            """
            SELECT name, account_name, account_type
            FROM `tabAccount`
            WHERE company = %s AND account_type = 'Income Account'
            LIMIT 10
        """,
            company,
            as_dict=True,
        )

        print(f"Available Income Accounts ({len(income_accounts)}):")
        for acc in income_accounts:
            print(f"  - {acc.name}: {acc.account_name}")

        # Check for expense accounts
        expense_accounts = frappe.db.sql(
            """
            SELECT name, account_name, account_type
            FROM `tabAccount`
            WHERE company = %s AND account_type = 'Expense Account'
            LIMIT 10
        """,
            company,
            as_dict=True,
        )

        print(f"\nAvailable Expense Accounts ({len(expense_accounts)}):")
        for acc in expense_accounts:
            print(f"  - {acc.name}: {acc.account_name}")

    except Exception as e:
        print(f"❌ Error checking accounts: {str(e)}")


def test_smart_tegenrekening_mapper():
    """Test if the smart tegenrekening mapper can provide fallback accounts"""

    print("\n=== Testing Smart Tegenrekening Mapper ===")

    try:
        from verenigingen.utils.smart_tegenrekening_mapper import create_invoice_line_for_tegenrekening

        # Test creating an invoice line without a specific tegenrekening
        print("Testing tegenrekening mapper for fallback account:")

        try:
            line_dict = create_invoice_line_for_tegenrekening(
                tegenrekening_code=None,  # No specific code
                amount=100.0,
                description="Test service",
                transaction_type="sales",
            )
            print(f"✓ Success: {line_dict}")

            if "income_account" in line_dict:
                print(f"✓ Income account provided: {line_dict['income_account']}")
            elif "expense_account" in line_dict:
                print(f"✓ Expense account provided: {line_dict['expense_account']}")
            else:
                print("❌ No account provided in line_dict")

        except Exception as e:
            print(f"❌ Tegenrekening mapper error: {str(e)}")

    except ImportError as e:
        print(f"❌ Could not import tegenrekening mapper: {str(e)}")


def propose_solution():
    """Propose a solution for the invoice import issue"""

    print("\n=== Proposed Solution ===")

    print("The issue is that map_grootboek_to_erpnext_account() calls get_default_account() when")
    print("no grootboek_nummer is provided, but get_default_account() is designed to fail.")
    print()
    print("Solutions:")
    print("1. IMMEDIATE FIX: Modify map_grootboek_to_erpnext_account() to provide a real fallback")
    print("2. PROPER FIX: Ensure E-Boekhouden data includes proper GrootboekNummer values")
    print("3. FALLBACK: Use smart tegenrekening mapper for missing account mappings")
    print()
    print("The immediate fix would be to replace the get_default_account() call with:")
    print("- A real default income/expense account based on transaction_type")
    print("- Integration with the smart tegenrekening mapper")
    print("- A configuration setting for fallback accounts")


if __name__ == "__main__":
    try:
        frappe.init()
        frappe.connect()

        analyze_invoice_import_failure()
        test_smart_tegenrekening_mapper()
        propose_solution()

    except Exception as e:
        print(f"Analysis error: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
