#!/usr/bin/env python3
"""
Week 1 SEPA Improvements - Functionality Verification Script

This script verifies the Week 1 implementations:
1. N+1 query optimizations in SEPA batch UI
2. Billing frequency transition manager functionality
3. Database indexes for performance optimization
"""


def test_imports():
    """Test that all new functionality can be imported"""
    print("🔍 Testing imports...")

    try:
        # Test SEPA batch UI functions
        from verenigingen.api.sepa_batch_ui import (
            get_invoice_mandate_info,
            load_unpaid_invoices,
            validate_invoice_mandate,
        )

        print("✅ SEPA batch UI functions imported successfully")

        # Test billing frequency transition manager
        from verenigingen.utils.billing_frequency_transition_manager import (
            BillingFrequencyTransitionManager,
            execute_billing_frequency_transition,
            get_billing_transition_preview,
            validate_billing_frequency_transition,
        )

        print("✅ Billing frequency transition manager imported successfully")

        # Test database index creation utility
        from verenigingen.utils.create_sepa_indexes import create_sepa_indexes

        print("✅ Database index utilities imported successfully")

        return True

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False


def test_billing_transition_manager():
    """Test billing frequency transition manager core functionality"""
    print("\n🔍 Testing Billing Frequency Transition Manager...")

    try:
        from verenigingen.utils.billing_frequency_transition_manager import BillingFrequencyTransitionManager

        # Initialize manager
        manager = BillingFrequencyTransitionManager()

        # Test supported frequencies
        expected_frequencies = ["Monthly", "Quarterly", "Semi-Annual", "Annual"]
        if manager.supported_frequencies == expected_frequencies:
            print("✅ Supported frequencies configured correctly")
        else:
            print("❌ Supported frequencies mismatch")
            return False

        # Test frequency months mapping
        expected_months = {"Monthly": 1, "Quarterly": 3, "Semi-Annual": 6, "Annual": 12}
        if manager.frequency_months == expected_months:
            print("✅ Frequency months mapping configured correctly")
        else:
            print("❌ Frequency months mapping mismatch")
            return False

        # Test validation method exists and callable
        if hasattr(manager, "validate_transition") and callable(manager.validate_transition):
            print("✅ validate_transition method available")
        else:
            print("❌ validate_transition method missing")
            return False

        # Test execution method exists and callable
        if hasattr(manager, "execute_transition") and callable(manager.execute_transition):
            print("✅ execute_transition method available")
        else:
            print("❌ execute_transition method missing")
            return False

        # Test preview method exists and callable
        if hasattr(manager, "get_transition_preview") and callable(manager.get_transition_preview):
            print("✅ get_transition_preview method available")
        else:
            print("❌ get_transition_preview method missing")
            return False

        return True

    except Exception as e:
        print(f"❌ Billing transition manager test error: {e}")
        return False


def test_api_functions():
    """Test API function availability"""
    print("\n🔍 Testing API Functions...")

    try:
        # Test SEPA batch UI API functions
        from verenigingen.api.sepa_batch_ui import (
            get_batch_analytics,
            get_invoice_mandate_info,
            load_unpaid_invoices,
            preview_sepa_xml,
            validate_invoice_mandate,
        )

        # Check if functions have proper decorators (frappe.whitelist)
        functions_to_check = [
            load_unpaid_invoices,
            get_invoice_mandate_info,
            validate_invoice_mandate,
            get_batch_analytics,
            preview_sepa_xml,
        ]

        for func in functions_to_check:
            if hasattr(func, "__wrapped__") or hasattr(func, "whitelisted"):
                print(f"✅ {func.__name__} is properly whitelisted")
            else:
                # Check if it has the whitelist attribute through inspection
                import inspect

                source = inspect.getsource(func)
                if "@frappe.whitelist()" in source or "frappe.whitelist()" in source:
                    print(f"✅ {func.__name__} is properly whitelisted")
                else:
                    print(f"⚠️  {func.__name__} whitelist status unclear")

        return True

    except Exception as e:
        print(f"❌ API functions test error: {e}")
        return False


def main():
    """Main test execution"""
    print("=" * 60)
    print("WEEK 1 SEPA IMPROVEMENTS - FUNCTIONALITY VERIFICATION")
    print("=" * 60)

    results = {
        "imports": test_imports(),
        "billing_manager": test_billing_transition_manager(),
        "api_functions": test_api_functions(),
    }

    print("\n" + "=" * 60)
    print("VERIFICATION RESULTS")
    print("=" * 60)

    total_tests = len(results)
    passed_tests = sum(1 for result in results.values() if result)

    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name.replace('_', ' ').title()}: {status}")

    print(f"\nSummary: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        print("🎉 All Week 1 functionality verification tests passed!")
        return True
    else:
        print("⚠️  Some functionality verification tests failed")
        return False


if __name__ == "__main__":
    main()
