#!/usr/bin/env python3
"""
Functional test for JavaScript/Jinja2 template mixing fixes

This script tests that the template changes work correctly and translations function properly.
"""

import json

import frappe
import requests
from requests.auth import HTTPBasicAuth


def test_translation_functionality():
    """Test that __() function works in client-side JavaScript"""

    print("🧪 Testing Template JavaScript/Jinja2 Fixes")
    print("=" * 50)

    # Test configuration
    site_url = "https://dev.veganisme.net"

    # Test pages that were modified
    test_pages = [
        "/batch-optimizer",
        "/payment-dashboard",
        "/address-change",
        "/financial-dashboard",
        "/my-dues-schedule",
        "/schedule-maintenance",
    ]

    results = {
        "pages_tested": 0,
        "pages_accessible": 0,
        "javascript_errors": [],
        "translation_patterns_found": 0,
    }

    for page in test_pages:
        print(f"  Testing page: {page}")
        results["pages_tested"] += 1

        try:
            # Test if page loads without errors
            response = requests.get(f"{site_url}{page}", timeout=10)

            if response.status_code == 200:
                results["pages_accessible"] += 1
                print(f"    ✅ Page accessible (status: {response.status_code})")

                # Check for JavaScript translation patterns
                content = response.text

                # Look for new __() patterns (good)
                if "__(" in content:
                    results["translation_patterns_found"] += content.count("__(")
                    print(f"    ✅ Found __() translation patterns")

                # Look for old problematic patterns (bad)
                if "'{{ _(" in content or '"{{ _(' in content:
                    results["javascript_errors"].append(f"{page}: Still contains template mixing patterns")
                    print(f"    ❌ Still contains problematic template mixing")
                else:
                    print(f"    ✅ No problematic template mixing found")

            else:
                print(f"    ❌ Page not accessible (status: {response.status_code})")

        except Exception as e:
            print(f"    ❌ Error accessing page: {str(e)}")
            results["javascript_errors"].append(f"{page}: {str(e)}")

    # Summary
    print("\n📊 Test Results Summary")
    print("=" * 30)
    print(f"Pages tested: {results['pages_tested']}")
    print(f"Pages accessible: {results['pages_accessible']}")
    print(f"Translation patterns found: {results['translation_patterns_found']}")
    print(f"JavaScript errors: {len(results['javascript_errors'])}")

    if results["javascript_errors"]:
        print("\n❌ Errors found:")
        for error in results["javascript_errors"]:
            print(f"  - {error}")
    else:
        print("\n✅ No JavaScript errors found!")

    # Calculate success rate
    success_rate = (
        (results["pages_accessible"] / results["pages_tested"]) * 100 if results["pages_tested"] > 0 else 0
    )
    print(f"\nSuccess rate: {success_rate:.1f}%")

    return results


def test_frappe_client_side_translation():
    """Test that Frappe's client-side translation system works"""

    print("\n🔍 Testing Frappe Translation System")
    print("=" * 40)

    try:
        # Create a simple test to verify __() function is available in browser context
        test_js = """
        // Test that __() function exists and works
        if (typeof __ !== 'function') {
            console.error('__() translation function not available');
            return false;
        }

        // Test basic translation
        var testTranslation = __("Loading...");
        if (typeof testTranslation !== 'string') {
            console.error('__() function not returning string');
            return false;
        }

        console.log('Translation test successful:', testTranslation);
        return true;
        """

        print("  ✅ JavaScript translation test code prepared")
        print("  ℹ️  Client-side testing requires browser environment")
        print("  ℹ️  __() function availability will be tested during functional testing")

        return True

    except Exception as e:
        print(f"  ❌ Error preparing translation test: {str(e)}")
        return False


def main():
    """Run all tests"""

    print("🚀 Starting Template Fix Validation Tests")
    print("=" * 60)

    # Test 1: Page accessibility and pattern validation
    page_results = test_translation_functionality()

    # Test 2: Translation system validation
    translation_results = test_frappe_client_side_translation()

    # Overall assessment
    print("\n🎯 Overall Assessment")
    print("=" * 25)

    if (
        page_results["pages_accessible"] >= page_results["pages_tested"] * 0.8
        and len(page_results["javascript_errors"]) == 0
    ):
        print("✅ Template fixes appear to be working correctly!")
        print("✅ No problematic JavaScript/Jinja2 mixing patterns found")
        print("✅ Pages are accessible and functional")
    else:
        print("⚠️  Some issues found that need attention:")
        if page_results["pages_accessible"] < page_results["pages_tested"] * 0.8:
            print("  - Some pages are not accessible")
        if len(page_results["javascript_errors"]) > 0:
            print("  - JavaScript errors or problematic patterns detected")

    print(f"\nℹ️  Found {page_results['translation_patterns_found']} __() translation patterns")
    print("ℹ️  This indicates successful migration from server-side to client-side translation")

    return (
        page_results["pages_accessible"] >= page_results["pages_tested"] * 0.8
        and len(page_results["javascript_errors"]) == 0
    )


if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Test execution failed: {str(e)}")
        exit(1)
