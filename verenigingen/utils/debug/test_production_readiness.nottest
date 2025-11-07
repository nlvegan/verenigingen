#!/usr/bin/env python3
"""
Test production readiness of E-Boekhouden import system
Ensures strict account mapping validation is enforced
"""

import frappe


def test_production_readiness():
    """Test that the system properly enforces account mapping in production mode"""

    print("=== Testing Production Readiness ===")

    # Test 1: Verify development mode detection
    print("\n--- Test 1: Development Mode Detection ---")

    developer_mode = frappe.conf.get("developer_mode", False)
    print(f"Current developer_mode: {developer_mode}")

    if developer_mode:
        print("✅ Running in development mode - fallbacks allowed for testing")
    else:
        print("✅ Running in production mode - strict account mapping enforced")

    # Test 2: Test strict account mapping behavior
    print("\n--- Test 2: Account Mapping Validation ---")

    try:
        from verenigingen.e_boekhouden.utils.invoice_helpers import map_grootboek_to_erpnext_account

        debug_info = []

        # Test with missing account code and allow_fallback=False (production behavior)
        try:
            account = map_grootboek_to_erpnext_account(
                grootboek_nummer=None, transaction_type="sales", debug_info=debug_info, allow_fallback=False
            )
            print(f"❌ ISSUE: Should have failed but returned: {account}")
            return False
        except Exception as e:
            if "proper account mapping required" in str(e).lower():
                print("✅ Correctly rejects missing account mapping when allow_fallback=False")
            else:
                print(f"❌ Wrong error type: {str(e)}")
                return False

        # Test with missing account code and allow_fallback=True (development behavior)
        debug_info = []
        try:
            account = map_grootboek_to_erpnext_account(
                grootboek_nummer=None, transaction_type="sales", debug_info=debug_info, allow_fallback=True
            )
            if "E-Boekhouden Import" in account:
                print(f"✅ Development fallback uses safe import account: {account}")
            else:
                print(f"❌ DANGER: Development fallback uses business account: {account}")
                return False
        except Exception as e:
            print(f"❌ Development fallback failed: {str(e)}")
            return False

    except Exception as e:
        print(f"❌ Account mapping test failed: {str(e)}")
        return False

    # Test 3: Verify invoice processing behavior based on mode
    print("\n--- Test 3: Invoice Processing Mode Behavior ---")

    try:
        from verenigingen.e_boekhouden.utils.invoice_helpers import process_line_items

        # Create test invoice
        company = frappe.db.get_single_value("Global Defaults", "default_company")
        if not company:
            company = frappe.db.get_value("Company", {}, "name")

        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

        mock_invoice = frappe.new_doc("Sales Invoice")
        mock_invoice.company = company
        mock_invoice.customer = frappe.db.get_value("Customer", {}, "name")

        if not mock_invoice.customer:
            print("❌ No customer found for testing")
            return False

        # Test data with non-existent account code
        test_data = [
            {
                "description": "Test production readiness",
                "quantity": 1,
                "amount": 100.0,
                "vatCode": "HOOG",
                "ledgerId": "99999",  # Non-existent account
            }
        ]

        debug_info = []

        # This should work in development mode (uses fallback) but fail in production mode
        if developer_mode:
            # Development mode - should use fallback
            try:
                success = process_line_items(mock_invoice, test_data, "sales", cost_center, debug_info)
                if success:
                    print("✅ Development mode: Successfully processed with fallback")
                    # Check that fallback account was used
                    fallback_used = any("fallback" in msg.lower() for msg in debug_info)
                    if fallback_used:
                        print("✅ Development mode: Fallback account properly used")
                    else:
                        print("⚠️  Development mode: No fallback detected in debug info")
                else:
                    print("❌ Development mode: Processing failed unexpectedly")
                    return False
            except Exception as e:
                print(f"❌ Development mode: Processing failed: {str(e)}")
                return False
        else:
            # Production mode - should fail with proper error
            try:
                success = process_line_items(mock_invoice, test_data, "sales", cost_center, debug_info)
                print(f"❌ ISSUE: Production mode should have failed but succeeded: {success}")
                print(f"Debug info: {debug_info}")
                return False
            except Exception as e:
                if "account mapping required" in str(e).lower() or "account mapping" in str(e).lower():
                    print("✅ Production mode: Correctly fails with missing account mapping")
                else:
                    print(f"❌ Production mode: Wrong error type: {str(e)}")
                    return False

    except Exception as e:
        print(f"❌ Invoice processing test failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return False

    # Test 4: Verify dedicated import accounts are properly set up
    print("\n--- Test 4: Import Account Verification ---")

    expected_import_accounts = [
        ("89999 - E-Boekhouden Import Income - NVV", "Income Account"),
        ("59999 - E-Boekhouden Import Expense - NVV", "Expense Account"),
        ("19999 - E-Boekhouden Import Payable - NVV", "Payable"),
        ("13999 - E-Boekhouden Import Receivable - NVV", "Receivable"),
    ]

    all_correct = True
    for account_name, expected_type in expected_import_accounts:
        if frappe.db.exists("Account", account_name):
            account_type = frappe.db.get_value("Account", account_name, "account_type")
            if account_type == expected_type:
                print(f"✅ {account_name} exists with correct type: {account_type}")
            else:
                print(f"❌ {account_name} has wrong type: {account_type} (expected: {expected_type})")
                all_correct = False
        else:
            print(f"❌ Missing import account: {account_name}")
            all_correct = False

    if not all_correct:
        return False

    print("\n✅ Production readiness tests passed!")
    print("\nSUMMARY:")
    if developer_mode:
        print("- Running in DEVELOPMENT mode:")
        print("  • Fallbacks allowed for missing account mappings")
        print("  • Uses dedicated import accounts only (safe)")
        print("  • Good for testing and configuration")
    else:
        print("- Running in PRODUCTION mode:")
        print("  • Strict account mapping validation enforced")
        print("  • Missing mappings cause import failures (safe)")
        print("  • Requires proper account configuration")
    print("- Dedicated import accounts properly configured")
    print("- Business account protection working")
    print("- System ready for safe E-Boekhouden imports")

    return True


if __name__ == "__main__":
    try:
        frappe.init()
        frappe.connect()

        success = test_production_readiness()

        if success:
            print("\n🎉 E-Boekhouden system is production-ready!")
        else:
            print("\n❌ Production readiness issues found")

    except Exception as e:
        print(f"Test error: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
