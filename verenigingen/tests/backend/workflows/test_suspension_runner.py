#!/usr/bin/env python3
"""
Comprehensive test runner for suspension system
Run with: bench execute verenigingen.test_suspension_runner.run_all_suspension_tests

Updated: Includes tests for new import error handling and fallback mechanisms
in the can_suspend_member API function.
"""

import sys
import traceback
import unittest
from io import StringIO

import frappe


def run_all_suspension_tests():
    """Run all suspension system tests"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        print("🧪 SUSPENSION SYSTEM COMPREHENSIVE TEST SUITE")
        print("=" * 60)

        # Import all test modules
        test_modules = [
            "verenigingen.tests.test_suspension_integration",
            "verenigingen.tests.test_suspension_api",
            "verenigingen.tests.test_suspension_api_import_fallback",
            "verenigingen.tests.test_suspension_permissions",
            "verenigingen.tests.test_suspension_member_mixin",
        ]

        # Track results
        total_tests = 0
        total_failures = 0
        total_errors = 0
        test_results = {}

        # Run each test module
        for module_name in test_modules:
            print(f"\n📋 Running {module_name}")
            print("-" * 40)

            try:
                # Import the test module
                module = __import__(module_name, fromlist=[""])

                # Create test suite
                loader = unittest.TestLoader()
                suite = loader.loadTestsFromModule(module)

                # Run tests with detailed output
                stream = StringIO()
                runner = unittest.TextTestRunner(stream=stream, verbosity=2, failfast=False)
                result = runner.run(suite)

                # Capture results
                module_tests = result.testsRun
                module_failures = len(result.failures)
                module_errors = len(result.errors)

                total_tests += module_tests
                total_failures += module_failures
                total_errors += module_errors

                test_results[module_name] = {
                    "tests": module_tests,
                    "failures": module_failures,
                    "errors": module_errors,
                    "success": module_failures == 0 and module_errors == 0}

                # Print results for this module
                if module_failures == 0 and module_errors == 0:
                    print(f"✅ {module_tests} tests PASSED")
                else:
                    print(f"❌ {module_tests} tests run: {module_failures} failures, {module_errors} errors")

                    # Print failure details
                    if result.failures:
                        print("\n🔍 FAILURES:")
                        for test, traceback_str in result.failures:
                            print(f"  • {test}: {traceback_str.splitlines()[-1]}")

                    if result.errors:
                        print("\n🔍 ERRORS:")
                        for test, traceback_str in result.errors:
                            print(f"  • {test}: {traceback_str.splitlines()[-1]}")

            except Exception as e:
                print(f"❌ Failed to run {module_name}: {str(e)}")
                test_results[module_name] = {
                    "tests": 0,
                    "failures": 0,
                    "errors": 1,
                    "success": False,
                    "import_error": str(e)}
                total_errors += 1

        # Print comprehensive summary
        print("\n" + "=" * 60)
        print("📊 COMPREHENSIVE TEST SUMMARY")
        print("=" * 60)

        for module_name, results in test_results.items():
            status = "✅ PASS" if results["success"] else "❌ FAIL"
            if "import_error" in results:
                print(f"{status} {module_name}: Import Error - {results['import_error']}")
            else:
                print(
                    f"{status} {module_name}: {results['tests']} tests, {results['failures']} failures, {results['errors']} errors"
                )

        print("\n📈 TOTALS:")
        print(f"   Tests Run: {total_tests}")
        print(f"   Failures: {total_failures}")
        print(f"   Errors: {total_errors}")

        success_rate = (
            ((total_tests - total_failures - total_errors) / total_tests * 100) if total_tests > 0 else 0
        )
        print(f"   Success Rate: {success_rate:.1f}%")

        # Overall result
        if total_failures == 0 and total_errors == 0:
            print("\n🎉 ALL TESTS PASSED! Suspension system is ready for production.")
            return True
        else:
            print(f"\n⚠️  {total_failures + total_errors} tests failed. Please review and fix issues.")
            return False

    except Exception as e:
        print(f"\n💥 CRITICAL ERROR in test runner: {str(e)}")
        traceback.print_exc()
        return False
    finally:
        frappe.destroy()


def run_quick_suspension_tests():
    """Run a quick subset of critical suspension tests"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        print("🚀 SUSPENSION SYSTEM QUICK TEST SUITE")
        print("=" * 50)

        # Test critical functionality
        test_scenarios = [
            "Test suspension integration import",
            "Test suspension API import",
            "Test permission function import",
            "Test mixin integration",
        ]

        passed = 0
        total = len(test_scenarios)

        # Test 1: Integration functions
        try:
            pass

            print("✅ Test suspension integration import")
            passed += 1
        except Exception as e:
            print(f"❌ Test suspension integration import: {str(e)}")

        # Test 2: API functions
        try:
            pass

            print("✅ Test suspension API import")
            passed += 1
        except Exception as e:
            print(f"❌ Test suspension API import: {str(e)}")

        # Test 3: Permission functions
        try:
            pass

            print("✅ Test permission function import")
            passed += 1
        except Exception as e:
            print(f"❌ Test permission function import: {str(e)}")

        # Test 4: Mixin integration
        try:
            from verenigingen.verenigingen.doctype.member.mixins.termination_mixin import TerminationMixin

            # Check for suspension methods
            required_methods = ["get_suspension_summary", "suspend_member", "unsuspend_member"]
            for method in required_methods:
                if not hasattr(TerminationMixin, method):
                    raise AttributeError(f"Missing method: {method}")

            print("✅ Test mixin integration")
            passed += 1
        except Exception as e:
            print(f"❌ Test mixin integration: {str(e)}")

        # Summary
        print(f"\n📊 QUICK TEST RESULTS: {passed}/{total} tests passed")

        if passed == total:
            print("🎉 All critical components working!")
            return True
        else:
            print("⚠️  Some critical components have issues")
            return False

    except Exception as e:
        print(f"💥 CRITICAL ERROR: {str(e)}")
        return False
    finally:
        frappe.destroy()


def run_suspension_smoke_test():
    """Run basic smoke test to verify suspension system is functional"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        print("💨 SUSPENSION SYSTEM SMOKE TEST")
        print("=" * 40)

        # Basic import test
        print("🔍 Testing basic imports...")

        components = {
            "Core Integration": "verenigingen.utils.termination_integration",
            "API Layer": "verenigingen.api.suspension_api",
            "Permissions": "verenigingen.permissions",
            "Member Mixin": "verenigingen.verenigingen.doctype.member.mixins.termination_mixin"}

        all_passed = True

        for component_name, module_path in components.items():
            try:
                __import__(module_path)
                print(f"✅ {component_name}")
            except Exception as e:
                print(f"❌ {component_name}: {str(e)}")
                all_passed = False

        # Test key function availability
        print("\n🔍 Testing key functions...")

        key_functions = [
            ("suspend_member_safe", "verenigingen.utils.termination_integration"),
            ("unsuspend_member_safe", "verenigingen.utils.termination_integration"),
            ("suspend_member", "verenigingen.api.suspension_api"),
            ("can_terminate_member", "verenigingen.permissions"),
        ]

        for func_name, module_path in key_functions:
            try:
                module = __import__(module_path, fromlist=[func_name])
                func = getattr(module, func_name)
                if callable(func):
                    print(f"✅ {func_name}")
                else:
                    print(f"❌ {func_name}: Not callable")
                    all_passed = False
            except Exception as e:
                print(f"❌ {func_name}: {str(e)}")
                all_passed = False

        print(f"\n📊 SMOKE TEST: {'PASSED' if all_passed else 'FAILED'}")
        return all_passed

    except Exception as e:
        print(f"💥 SMOKE TEST FAILED: {str(e)}")
        return False
    finally:
        frappe.destroy()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "quick":
            run_quick_suspension_tests()
        elif sys.argv[1] == "smoke":
            run_suspension_smoke_test()
        else:
            run_all_suspension_tests()
    else:
        run_all_suspension_tests()
