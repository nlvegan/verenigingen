#!/usr/bin/env python3
"""
Test the invoice import fix for REST API English field names
"""

import frappe


def test_invoice_import_fix():
    """Test that the invoice import fix works with REST API data"""

    print("=== Testing Invoice Import Fix ===")

    # Test 1: Test the fixed get_default_account function
    print("\n--- Test 1: get_default_account Function ---")

    try:
        from verenigingen.e_boekhouden.utils.invoice_helpers import get_default_account

        # Test sales account
        sales_account = get_default_account("sales")
        print(f"✓ Sales fallback account: {sales_account}")

        # Test purchase account
        purchase_account = get_default_account("purchase")
        print(f"✓ Purchase fallback account: {purchase_account}")

    except Exception as e:
        print(f"❌ get_default_account error: {str(e)}")
        return False

    # Test 2: Test the fixed field name mapping
    print("\n--- Test 2: Field Name Mapping ---")

    # Create sample REST API data (English field names)
    rest_api_row = {
        "description": "Test service from REST API",
        "quantity": 2,
        "amount": 50.0,
        "vatCode": "HOOG",
        "ledgerId": "8000",
    }

    # Create sample SOAP API data (Dutch field names) for comparison
    soap_api_row = {
        "Omschrijving": "Test service from SOAP API",
        "Aantal": 1,
        "Prijs": 25.0,
        "BTWCode": "LAAG",
        "GrootboekNummer": "8100",
    }

    try:
        from verenigingen.e_boekhouden.utils.invoice_helpers import process_line_items

        company = frappe.db.get_single_value("Global Defaults", "default_company")
        if not company:
            company = frappe.db.get_value("Company", {}, "name")

        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

        # Test with a mock invoice document
        mock_invoice = frappe.new_doc("Sales Invoice")
        mock_invoice.company = company
        mock_invoice.customer = frappe.db.get_value("Customer", {}, "name")  # Get any customer

        if not mock_invoice.customer:
            print("❌ No customer found for testing")
            return False

        # Test processing REST API data (English field names)
        print("Testing REST API data (English field names):")
        debug_info_rest = []
        success_rest = process_line_items(mock_invoice, [rest_api_row], "sales", cost_center, debug_info_rest)

        print(f"REST API processing success: {success_rest}")
        for info in debug_info_rest:
            print(f"  - {info}")

        # Test processing SOAP API data (Dutch field names)
        print("\nTesting SOAP API data (Dutch field names):")
        debug_info_soap = []
        success_soap = process_line_items(mock_invoice, [soap_api_row], "sales", cost_center, debug_info_soap)

        print(f"SOAP API processing success: {success_soap}")
        for info in debug_info_soap:
            print(f"  - {info}")

        if success_rest and success_soap:
            print("✅ Both REST and SOAP API field formats work correctly")
            return True
        else:
            print("❌ Field format processing failed")
            return False

    except Exception as e:
        print(f"❌ Field mapping test error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def test_account_mapping_with_fallbacks():
    """Test account mapping with the new fallback system"""

    print("\n--- Test 3: Account Mapping with Fallbacks ---")

    try:
        from verenigingen.e_boekhouden.utils.invoice_helpers import map_grootboek_to_erpnext_account

        debug_info = []

        # Test with None (should use fallback)
        print("Testing with None account code:")
        account_none = map_grootboek_to_erpnext_account(None, "sales", debug_info)
        print(f"Result: {account_none}")
        print(f"Debug: {debug_info}")

        # Test with empty string (should use fallback)
        debug_info = []
        print("\nTesting with empty account code:")
        account_empty = map_grootboek_to_erpnext_account("", "sales", debug_info)
        print(f"Result: {account_empty}")
        print(f"Debug: {debug_info}")

        # Test with non-existent account code (should try mapping then fallback)
        debug_info = []
        print("\nTesting with non-existent account code:")
        account_missing = map_grootboek_to_erpnext_account("99999", "sales", debug_info)
        print(f"Result: {account_missing}")
        print(f"Debug: {debug_info}")

        if account_none and account_empty:
            print("✅ Account mapping fallbacks working correctly")
            return True
        else:
            print("❌ Account mapping fallbacks failed")
            return False

    except Exception as e:
        print(f"❌ Account mapping test error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    try:
        frappe.init()
        frappe.connect()

        result1 = test_invoice_import_fix()
        result2 = test_account_mapping_with_fallbacks()

        if result1 and result2:
            print("\n✅ All invoice import fixes working correctly!")
            print(
                "The system should now be able to import Sales and Purchase Invoices from E-Boekhouden REST API"
            )
        else:
            print("\n❌ Some issues found with the invoice import fixes")

    except Exception as e:
        print(f"Test error: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
