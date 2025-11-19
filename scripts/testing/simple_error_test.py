#!/usr/bin/env python3
"""
Simple test script for improved API error handling
"""

import frappe


def test_suspension_api():
    """Test suspension API error handling"""
    print("Testing Suspension API...")

    try:
        from verenigingen.api.suspension_api import suspend_member

        # Test 1: Missing member
        result = suspend_member("", "test reason")
        print(f"Test 1 - Empty member: {result}")

        # Test 2: Missing reason
        result = suspend_member("test-member", "")
        print(f"Test 2 - Empty reason: {result}")

        # Test 3: Non-existent member
        result = suspend_member("NON_EXISTENT_MEMBER", "test reason")
        print(f"Test 3 - Non-existent member: {result}")

        print("✅ Suspension API tests completed")
        return True

    except Exception as e:
        print(f"❌ Suspension API test failed: {e}")
        return False


def test_dd_batch_api():
    """Test DD batch scheduler API error handling"""
    print("\nTesting DD Batch Scheduler API...")

    try:
        from verenigingen.api.dd_batch_scheduler import run_batch_creation_now

        # Test without admin permissions
        original_user = frappe.session.user
        frappe.session.user = "test@example.com"

        result = run_batch_creation_now()
        print(f"Test - Non-admin user: {result}")

        # Restore user
        frappe.session.user = original_user

        print("✅ DD Batch Scheduler API tests completed")
        return True

    except Exception as e:
        print(f"❌ DD Batch Scheduler API test failed: {e}")
        return False


def run_simple_tests():
    """Run simple error handling tests"""
    print("🧪 Simple Error Handling Tests")
    print("=" * 40)

    # Initialize frappe context
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    results = []

    # Test suspension API
    results.append(test_suspension_api())

    # Test DD batch API
    results.append(test_dd_batch_api())

    # Summary
    passed = sum(results)
    total = len(results)

    print(f"\n📊 Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed!")
    else:
        print(f"⚠️  {total - passed} tests failed")

    return passed == total


if __name__ == "__main__":
    run_simple_tests()
