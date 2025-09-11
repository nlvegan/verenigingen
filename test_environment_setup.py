#!/usr/bin/env python3
"""
Simple Test Environment Setup Validation

Quick script to validate that Enhanced Test Factory fixture loading is working
and test environment has essential master data.
"""

import frappe


def validate_test_environment():
    """Validate test environment setup"""
    print("🔧 Validating Verenigingen Test Environment...")
    print("=" * 50)

    checks = [
        ("Verenigingen Settings", "Verenigingen Settings", "Verenigingen Settings"),
        ("Team Role fixtures", "Team Role", None),
        ("Membership Type fixtures", "Membership Type", None),
        ("Company exists", "Company", None),
        ("Users exist", "User", None),
    ]

    passed = failed = 0

    for check_name, doctype, specific_name in checks:
        try:
            if specific_name:
                exists = frappe.db.exists(doctype, specific_name)
                status = "✅" if exists else "❌"
                result = f"exists" if exists else "missing"
            else:
                count = frappe.db.count(doctype)
                status = "✅" if count > 0 else "❌"
                result = f"{count} records"

            print(f"   {status} {check_name}: {result}")

            if status == "✅":
                passed += 1
            else:
                failed += 1

        except Exception as e:
            print(f"   ❌ {check_name}: Error - {str(e)}")
            failed += 1

    print(f"\n📊 Summary: {passed} passed, {failed} failed")

    if failed == 0:
        print("🚀 Test environment is properly configured!")
    else:
        print("⚠️  Test environment needs additional setup")

    print("=" * 50)


if __name__ == "__main__":
    frappe.connect()
    frappe.set_user("Administrator")
    validate_test_environment()
