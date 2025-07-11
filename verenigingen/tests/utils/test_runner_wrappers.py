"""
Wrapper functions for test runner compatibility
Provides standardized run functions for various test modules
"""

import frappe

# Quick test wrappers


@frappe.whitelist()
def run_iban_validation_tests():
    """Run IBAN validation tests"""
    try:
        from verenigingen.tests.backend.validation.test_iban_validator import run_tests

        run_tests()
        return {"success": True, "message": "IBAN validation tests completed"}
    except Exception as e:
        return {"success": False, "message": f"IBAN validation tests failed: {str(e)}"}


@frappe.whitelist()
def run_special_character_tests():
    """Run special character validation tests"""
    try:
        # Run the tests using unittest
        import unittest

        from verenigingen.tests.backend.security import test_special_characters_validation

        suite = unittest.TestLoader().loadTestsFromModule(test_special_characters_validation)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        return {
            "success": result.wasSuccessful(),
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "message": f"{result.testsRun} tests run, {len(result.failures)} failures, {len(result.errors)} errors",
        }
    except Exception as e:
        return {"success": False, "message": f"Special character tests failed: {str(e)}"}


# Comprehensive test wrappers


@frappe.whitelist()
def run_all_doctype_validation_tests():
    """Run all doctype validation tests"""
    try:
        from verenigingen.tests.backend.comprehensive.test_doctype_validation_comprehensive import run_doctype_validation_tests

        return run_doctype_validation_tests()
    except Exception as e:
        return {"success": False, "message": f"Doctype validation tests failed: {str(e)}"}


@frappe.whitelist()
def run_all_security_tests():
    """Run all security tests"""
    try:
        from verenigingen.tests.backend.security.test_security_comprehensive import run_all_security_tests

        return run_all_security_tests()
    except Exception as e:
        return {"success": False, "message": f"Security tests failed: {str(e)}"}


@frappe.whitelist()
def run_all_tests():
    """Run comprehensive edge case tests"""
    try:
        from verenigingen.tests.backend.comprehensive.test_comprehensive_edge_cases import run_all_tests

        return run_all_tests()
    except Exception as e:
        return {"success": False, "message": f"Comprehensive tests failed: {str(e)}"}


@frappe.whitelist()
def run_expense_integration_tests():
    """Run expense integration tests"""
    try:
        # Import test class and run
        import unittest

        from verenigingen.tests.backend.comprehensive.test_erpnext_expense_integration import TestERPNextExpenseIntegration

        suite = unittest.TestLoader().loadTestsFromTestCase(TestERPNextExpenseIntegration)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        return {
            "success": result.wasSuccessful(),
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "message": f"Expense integration tests: {result.testsRun} run, {len(result.failures)} failures",
        }
    except Exception as e:
        return {"success": False, "message": f"Expense integration tests failed: {str(e)}"}


@frappe.whitelist()
def run_all_sepa_tests():
    """Run all SEPA tests"""
    try:
        from verenigingen.tests.backend.security.test_sepa_mandate_creation import run_all_sepa_tests

        return run_all_sepa_tests()
    except Exception as e:
        return {"success": False, "message": f"SEPA tests failed: {str(e)}"}


@frappe.whitelist()
def run_all_portal_tests():
    """Run all volunteer portal tests"""
    try:
        import unittest

        from verenigingen.tests.backend.comprehensive.test_volunteer_portal_integration import TestVolunteerPortalIntegration

        suite = unittest.TestLoader().loadTestsFromTestCase(TestVolunteerPortalIntegration)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        return {
            "success": result.wasSuccessful(),
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "message": f"Portal tests: {result.testsRun} run, {len(result.failures)} failures",
        }
    except Exception as e:
        return {"success": False, "message": f"Portal tests failed: {str(e)}"}


@frappe.whitelist()
def run_all_termination_tests():
    """Run all termination system tests"""
    try:
        from verenigingen.tests.backend.comprehensive.test_termination_system_comprehensive import run_all_termination_tests

        return run_all_termination_tests()
    except Exception as e:
        return {"success": False, "message": f"Termination tests failed: {str(e)}"}


@frappe.whitelist()
def run_workflow_tests():
    """Run chapter membership workflow tests"""
    try:
        import unittest

        from verenigingen.tests.backend.comprehensive.test_chapter_membership_workflow import TestChapterMembershipWorkflow

        suite = unittest.TestLoader().loadTestsFromTestCase(TestChapterMembershipWorkflow)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        return {
            "success": result.wasSuccessful(),
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "message": f"Workflow tests: {result.testsRun} run, {len(result.failures)} failures",
        }
    except Exception as e:
        return {"success": False, "message": f"Workflow tests failed: {str(e)}"}


@frappe.whitelist()
def run_transition_tests():
    """Run member status transition tests"""
    try:
        from verenigingen.tests.backend.comprehensive.test_member_status_transitions import run_all_transition_tests

        return run_all_transition_tests()
    except Exception as e:
        return {"success": False, "message": f"Transition tests failed: {str(e)}"}


# Scheduled test wrappers


@frappe.whitelist()
def run_performance_tests():
    """Run performance edge case tests"""
    try:
        from verenigingen.tests.backend.comprehensive.test_performance_edge_cases import run_performance_tests

        return run_performance_tests()
    except Exception as e:
        return {"success": False, "message": f"Performance tests failed: {str(e)}"}


@frappe.whitelist()
def run_payment_failure_tests():
    """Run payment failure scenario tests"""
    try:
        from verenigingen.tests.backend.comprehensive.test_payment_failure_scenarios import run_all_payment_failure_tests

        return run_all_payment_failure_tests()
    except Exception as e:
        return {"success": False, "message": f"Payment failure tests failed: {str(e)}"}


@frappe.whitelist()
def run_financial_tests():
    """Run financial integration edge case tests"""
    try:
        from verenigingen.tests.backend.comprehensive.test_financial_integration_edge_cases import run_all_financial_tests

        return run_all_financial_tests()
    except Exception as e:
        return {"success": False, "message": f"Financial tests failed: {str(e)}"}
