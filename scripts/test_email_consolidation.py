#!/usr/bin/env python3
"""
Test script to validate the unified EmailService consolidation.

This script tests that:
1. EmailService can be imported and instantiated
2. Template loading works correctly
3. Compatibility layer works

Run with: python scripts/test_email_consolidation.py
"""

import sys


def test_email_service_imports():
    """Test that all EmailService components can be imported."""
    print("Testing EmailService imports...")

    try:
        from verenigingen.services.communication.email_service import EmailService, get_email_service
        from verenigingen.services.communication.compatibility import (
            send_member_notification,
            send_sepa_email,
            send_chapter_email
        )
        print("✅ All EmailService imports successful")
        return True
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False

def test_email_service_instantiation():
    """Test that EmailService can be instantiated."""
    print("Testing EmailService instantiation...")

    try:
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        if email_service is not None:
            print("✅ EmailService instantiation successful")
            return True
        else:
            print("❌ EmailService instantiation returned None")
            return False
    except Exception as e:
        print(f"❌ EmailService instantiation failed: {e}")
        return False

def test_template_loading():
    """Test that EmailService can load templates from Email Template DocType."""
    print("Testing template loading...")

    try:
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        # Test that a nonexistent template returns None
        template = email_service._get_template("nonexistent_template_xyz")

        if template is None:
            print("✅ Template loading correctly returns None for missing templates")
            return True
        else:
            print(f"❌ Expected None for missing template, got: {template}")
            return False
    except Exception as e:
        print(f"❌ Template loading test failed: {e}")
        return False

def test_compatibility_layer():
    """Test that compatibility layer functions exist and are callable."""
    print("Testing compatibility layer...")

    try:
        from verenigingen.services.communication.compatibility import (
            send_member_notification,
            send_sepa_email,
            send_chapter_email
        )

        # Test that functions are callable (not actually calling them)
        if callable(send_member_notification) and callable(send_sepa_email) and callable(send_chapter_email):
            print("✅ Compatibility layer functions are callable")
            return True
        else:
            print("❌ Compatibility layer functions are not callable")
            return False
    except Exception as e:
        print(f"❌ Compatibility layer test failed: {e}")
        return False

def run_all_tests():
    """Run all email consolidation tests."""
    print("🧪 Running Email Consolidation Validation Tests")
    print("=" * 50)

    tests = [
        test_email_service_imports,
        test_email_service_instantiation,
        test_template_loading,
        test_compatibility_layer
    ]

    passed = 0
    total = len(tests)

    for test in tests:
        if test():
            passed += 1
        print()  # Empty line between tests

    print("=" * 50)
    print(f"Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All email consolidation tests PASSED!")
        return True
    else:
        print("⚠️  Some email consolidation tests FAILED!")
        return False

if __name__ == "__main__":
    # Set up the environment to import Frappe modules
    try:
        import frappe

        # Initialize Frappe if needed
        if not getattr(frappe.local, 'site', None):
            # Try to initialize with a site if available
            sites = frappe.utils.get_sites()
            if sites:
                frappe.init(site=sites[0])
                frappe.connect()

        success = run_all_tests()
        sys.exit(0 if success else 1)

    except ImportError:
        print("❌ Could not import frappe. Make sure you're running this from the frappe-bench directory.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error setting up test environment: {e}")
        sys.exit(1)
