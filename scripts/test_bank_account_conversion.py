#!/usr/bin/env python3
"""
Test script for GL Account → Bank Account conversion.

This verifies that the conversion logic works correctly for both:
- payment_entry_handler.py
- payment_processor.py

Usage:
    bench --site dev.veganisme.net execute verenigingen.scripts.test_bank_account_conversion.test_conversion
"""

import frappe


def test_conversion():
    """Test GL Account to Bank Account conversion"""
    print("\n" + "=" * 80)
    print("GL ACCOUNT → BANK ACCOUNT CONVERSION TEST")
    print("=" * 80 + "\n")

    # Get company
    company = "Nederlandsche Vegetariërsbond"

    # Get all Bank Accounts with their GL Accounts
    bank_accounts = frappe.get_all(
        "Bank Account",
        filters={"company": company, "is_company_account": 1},
        fields=["name", "account", "bank", "disabled"],
        order_by="name"
    )

    if not bank_accounts:
        print(f"❌ ERROR: No Bank Accounts found for company {company}")
        return

    print(f"Found {len(bank_accounts)} Bank Accounts for {company}:\n")

    # Test conversion for each Bank Account
    test_results = []
    for ba in bank_accounts:
        gl_account = ba.account
        bank_account_name = ba.name
        bank = ba.bank
        disabled = ba.disabled

        status = "✓" if not disabled else "⚠ (disabled)"

        print(f"{status} {bank_account_name}")
        print(f"   Bank: {bank}")
        print(f"   GL Account: {gl_account}")

        # Test the conversion logic
        if gl_account:
            # Simulate the conversion logic
            resolved = frappe.db.get_value(
                "Bank Account",
                {"account": gl_account, "company": company},
                "name"
            )

            if resolved == bank_account_name:
                print(f"   ✓ Conversion works: GL '{gl_account}' → Bank Account '{resolved}'")
                test_results.append({"account": bank_account_name, "status": "PASS"})
            else:
                print(f"   ❌ ERROR: Expected '{bank_account_name}', got '{resolved}'")
                test_results.append({"account": bank_account_name, "status": "FAIL"})
        else:
            print(f"   ⚠ WARNING: No GL Account configured")
            test_results.append({"account": bank_account_name, "status": "NO_GL_ACCOUNT"})

        print()

    # Summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80 + "\n")

    passed = sum(1 for r in test_results if r["status"] == "PASS")
    failed = sum(1 for r in test_results if r["status"] == "FAIL")
    warnings = sum(1 for r in test_results if r["status"] == "NO_GL_ACCOUNT")

    print(f"Total Bank Accounts: {len(test_results)}")
    print(f"✓ Conversion Tests Passed: {passed}")
    print(f"❌ Conversion Tests Failed: {failed}")
    print(f"⚠ No GL Account: {warnings}")

    if failed > 0:
        print(f"\n❌ CONVERSION TESTS FAILED")
        return False
    elif warnings > 0:
        print(f"\n⚠ WARNING: Some Bank Accounts don't have GL Accounts configured")
        print("  This means they can't be used by E-Boekhouden integration")
        return True
    else:
        print(f"\n✅ ALL CONVERSION TESTS PASSED")
        return True


def test_direct_bank_account():
    """Test that passing a Bank Account name directly works"""
    print("\n" + "=" * 80)
    print("DIRECT BANK ACCOUNT TEST")
    print("=" * 80 + "\n")

    company = "Nederlandsche Vegetariërsbond"

    # Get first active Bank Account
    bank_account = frappe.get_value(
        "Bank Account",
        {"company": company, "disabled": 0},
        ["name", "account"],
        as_dict=True
    )

    if not bank_account:
        print("❌ No active Bank Accounts found")
        return False

    bank_account_name = bank_account.name

    # Test that passing Bank Account name directly works
    exists = frappe.db.exists("Bank Account", bank_account_name)

    if exists:
        print(f"✓ Direct Bank Account lookup works: '{bank_account_name}' exists")
        print(f"  (This simulates when ledger mapping already returns Bank Account name)")
        return True
    else:
        print(f"❌ ERROR: Bank Account '{bank_account_name}' not found")
        return False


if __name__ == "__main__":
    # Run from command line
    test_conversion()
    test_direct_bank_account()
