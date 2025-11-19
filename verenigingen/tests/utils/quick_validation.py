#!/usr/bin/env python3
"""
Quick validation tests for pre-commit hooks
Simple tests that don't require complex imports
"""

import frappe


def run_quick_tests():
    """Run quick validation tests"""
    print("🚀 Running Quick Validation Tests")
    print("=" * 50)
    
    tests_passed = 0
    tests_total = 0
    
    # Test 1: Check critical doctypes exist
    tests_total += 1
    try:
        member_doctype = frappe.get_meta("Member")
        if member_doctype:
            print("✅ Member doctype accessible")
            tests_passed += 1
        else:
            print("❌ Member doctype not found")
    except Exception as e:
        print(f"❌ Member doctype check failed: {e}")
    
    # Test 2: Check application validators work
    tests_total += 1
    try:
        from verenigingen.utils.validation.application_validators import validate_postal_code
        result = validate_postal_code("1234AB")
        if result.get("valid"):
            print("✅ Application validators work")
            tests_passed += 1
        else:
            print("❌ Application validator failed")
    except Exception as e:
        print(f"❌ Application validator check failed: {e}")
    
    # Test 3: Check IBAN validator
    tests_total += 1
    try:
        from verenigingen.utils.validation.iban_validator import validate_iban
        if validate_iban("NL91ABNA0417164300"):
            print("✅ IBAN validator works")
            tests_passed += 1
        else:
            print("❌ IBAN validator failed")
    except Exception as e:
        print(f"❌ IBAN validator check failed: {e}")
    
    # Test 4: Check boolean utils
    tests_total += 1
    try:
        from verenigingen.utils.boolean_utils import cbool
        if cbool("true") == 1 and cbool("false") == 0:
            print("✅ Boolean utils work")
            tests_passed += 1
        else:
            print("❌ Boolean utils failed")
    except Exception as e:
        print(f"❌ Boolean utils check failed: {e}")
    
    # Summary
    print(f"\n📊 Quick Tests Summary: {tests_passed}/{tests_total} passed")
    
    if tests_passed == tests_total:
        print("✅ All quick tests passed!")
        return True
    else:
        print("⚠️ Some quick tests failed")
        return False


if __name__ == "__main__":
    # Initialize frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    
    success = run_quick_tests()
    exit(0 if success else 1)