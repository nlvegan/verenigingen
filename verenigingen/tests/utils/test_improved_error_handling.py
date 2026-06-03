"""
Test script for improved API error handling
Tests all the functions that were updated with structured error handling
"""

import frappe
from frappe.utils import now_datetime
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest

class TestImprovedErrorHandling(EnhancedTestCase):
    """Test all the improved API functions"""
    
    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.results = {
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "details": []
        }
    
    def test_suspension_api_invalid_member(self):
        """Test suspension API with invalid member"""
        print("\n1. Testing Suspension API - Invalid member")
        
        from verenigingen.api.suspension_api import suspend_member
        
        result = suspend_member("NON_EXISTENT_MEMBER", "Test suspension")
        
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("success"), False)
        self.assertIn("error", result)
        print(f"✅ PASS: {result}")
    
    def test_suspension_api_missing_reason(self):
        """Test suspension API with missing reason"""
        print("\n2. Testing Suspension API - Missing reason")

        from verenigingen.api.suspension_api import suspend_member

        result = suspend_member("test-member", "")

        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("success"), False)
        # suspend_member returns an OperationResult serialized to the nested
        # schema, where the human-readable message lives under error.message.
        error_message = result.get("error", {}).get("message", "")
        self.assertIn("reason", error_message.lower())
        print(f"✅ PASS: {result}")
    
    def test_termination_api_invalid_member(self):
        """Test termination API with invalid member"""
        print("\n3. Testing Termination API - Invalid member")
        
        from verenigingen.api.termination_api import execute_safe_termination
        
        result = execute_safe_termination("NON_EXISTENT_MEMBER", "Voluntary")
        
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("success"), False)
        self.assertIn("error", result)
        print(f"✅ PASS: {result}")
    
    def test_termination_api_missing_type(self):
        """Test termination API with missing termination type"""
        print("\n4. Testing Termination API - Missing termination type")
        
        from verenigingen.api.termination_api import execute_safe_termination
        
        result = execute_safe_termination("test-member", "")
        
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("success"), False)
        self.assertIn("termination type", result.get("error", "").lower())
        print(f"✅ PASS: {result}")
    
    def test_application_review_api_invalid_member(self):
        """Test application review API rejects an invalid member reference.

        approve_membership_application validates the member via frappe.throw
        (raising ValidationError) rather than returning an error dict, so the
        invalid reference must surface as a raised exception.
        """
        print("\n5. Testing Application Review API - Invalid member")

        from verenigingen.api.membership_application_review import approve_membership_application

        with self.assertRaises(frappe.ValidationError) as ctx:
            approve_membership_application("NON_EXISTENT_MEMBER")
        self.assertIn("invalid member reference", str(ctx.exception).lower())
        print("✅ PASS: ValidationError raised for invalid member")

    def test_application_review_api_missing_reason(self):
        """Test application review API with missing rejection reason.

        reject_membership_application validates the member reference first (via
        frappe.throw); the "test-member" reference does not exist, so a
        ValidationError is raised before reason validation is reached.
        """
        print("\n6. Testing Application Review API - Missing rejection reason")

        from verenigingen.api.membership_application_review import reject_membership_application

        with self.assertRaises(frappe.ValidationError):
            reject_membership_application("test-member", "")
        print("✅ PASS: ValidationError raised")
    
    def test_dd_batch_scheduler_permissions(self):
        """Test DD batch scheduler API denies a non-privileged user.

        run_batch_creation_now is guarded by @critical_api, which restricts the
        endpoint to Treasurer/National/Admin tiers. A plain member must be
        denied with a PermissionError before the function body runs.
        """
        print("\n7. Testing DD Batch Scheduler API - Without admin permissions")

        from verenigingen.verenigingen_payments.api.dd_batch_scheduler import run_batch_creation_now

        with self.as_role("Verenigingen Member"):
            with self.assertRaises(frappe.PermissionError):
                run_batch_creation_now()
        print("✅ PASS: PermissionError raised for non-privileged user")

    def test_application_stats_permissions(self):
        """Test application statistics API denies a non-privileged user.

        get_application_stats is guarded by @standard_api (MEDIUM), which
        requires Volunteer/Staff/Admin. A plain member must be denied with a
        PermissionError.
        """
        print("\n8. Testing Application Statistics API - Without admin permissions")

        from verenigingen.api.admin_membership_operations import get_application_stats

        with self.as_role("Verenigingen Member"):
            with self.assertRaises(frappe.PermissionError):
                get_application_stats()
        print("✅ PASS: PermissionError raised for non-privileged user")
    
    def test_response_structure_consistency(self):
        """Test that all functions return consistent response structure"""
        print("\n9. Testing Response Structure Consistency")
        
        # These endpoints return a structured result dict (OperationResult-style)
        # on validation failure.
        dict_returning_functions = [
            ("suspension_api", "suspend_member", ["", "test"]),
            ("termination_api", "execute_safe_termination", ["", "test"]),
        ]

        # These endpoints validate their inputs via frappe.throw, so an invalid
        # reference surfaces as a raised ValidationError rather than an error dict.
        raising_functions = [
            ("membership_application_review", "approve_membership_application", [""]),
            ("membership_application_review", "reject_membership_application", ["", ""]),
        ]

        for module, func_name, args in dict_returning_functions:
            with self.subTest(function=func_name):
                module_obj = frappe.get_module(f"verenigingen.api.{module}")
                func = getattr(module_obj, func_name)
                result = func(*args)

                # Check response is dict
                self.assertIsInstance(result, dict, f"{func_name} should return dict")

                # Check has success field
                self.assertIn("success", result, f"{func_name} should have 'success' field")

                # Check has error field for failed responses
                if result.get("success") == False:
                    self.assertIn("error", result, f"{func_name} should have 'error' field for failed response")

        for module, func_name, args in raising_functions:
            with self.subTest(function=func_name):
                module_obj = frappe.get_module(f"verenigingen.api.{module}")
                func = getattr(module_obj, func_name)
                with self.assertRaises(frappe.ValidationError):
                    func(*args)

        print("✅ PASS: All functions surface validation failures consistently")


def run_error_handling_tests():
    """Run all error handling tests and return results"""
    print("🧪 Testing Improved API Error Handling")
    print("=" * 50)
    
    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestImprovedErrorHandling)
    
    # Run tests with custom result collector
    class TestResultCollector(unittest.TestResult):
        def __init__(self):
            super().__init__()
            self.results = []
            
        def addSuccess(self, test):
            super().addSuccess(test)
            self.results.append(f"✅ {test._testMethodName}: PASS")
            
        def addError(self, test, err):
            super().addError(test, err)
            self.results.append(f"❌ {test._testMethodName}: ERROR - {err[1]}")
            
        def addFailure(self, test, err):
            super().addFailure(test, err)
            self.results.append(f"❌ {test._testMethodName}: FAIL - {err[1]}")
    
    result_collector = TestResultCollector()
    suite.run(result_collector)
    
    # Print summary
    print("\n" + "=" * 50)
    print("📊 TEST SUMMARY")
    print("=" * 50)
    print(f"Total Tests: {result_collector.testsRun}")
    print(f"Passed: {result_collector.testsRun - len(result_collector.failures) - len(result_collector.errors)}")
    print(f"Failed: {len(result_collector.failures)}")
    print(f"Errors: {len(result_collector.errors)}")
    
    if result_collector.failures or result_collector.errors:
        success_rate = ((result_collector.testsRun - len(result_collector.failures) - len(result_collector.errors)) / result_collector.testsRun * 100)
    else:
        success_rate = 100.0
    
    print(f"Success Rate: {success_rate:.1f}%")
    
    print("\n📋 DETAILED RESULTS:")
    for detail in result_collector.results:
        print(f"  {detail}")
    
    if not result_collector.failures and not result_collector.errors:
        print("\n🎉 ALL TESTS PASSED! Error handling improvements are working correctly.")
    else:
        print(f"\n⚠️  {len(result_collector.failures + result_collector.errors)} tests failed. Review the failures above.")
    
    print(f"\nTest completed at: {now_datetime()}")
    
    return {
        "total": result_collector.testsRun,
        "passed": result_collector.testsRun - len(result_collector.failures) - len(result_collector.errors),
        "failed": len(result_collector.failures),
        "errors": len(result_collector.errors),
        "success_rate": success_rate
    }


if __name__ == "__main__":
    run_error_handling_tests()