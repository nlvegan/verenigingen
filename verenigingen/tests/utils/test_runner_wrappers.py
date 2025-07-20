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
            "message": f"{result.testsRun} tests run, {len(result.failures)} failures, {len(result.errors)} errors"}
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
            "message": f"Expense integration tests: {result.testsRun} run, {len(result.failures)} failures"}
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
            "message": f"Portal tests: {result.testsRun} run, {len(result.failures)} failures"}
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
            "message": f"Workflow tests: {result.testsRun} run, {len(result.failures)} failures"}
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


@frappe.whitelist()
def run_report_regression_tests():
    """Run report regression tests including overdue payments report"""
    try:
        import unittest

        from verenigingen.tests.backend.components.test_overdue_payments_report_regression import TestOverduePaymentsReportRegression

        suite = unittest.TestLoader().loadTestsFromTestCase(TestOverduePaymentsReportRegression)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        return {
            "success": result.wasSuccessful(),
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "message": f"Report regression tests: {result.testsRun} run, {len(result.failures)} failures, {len(result.errors)} errors"}
    except Exception as e:
        return {"success": False, "message": f"Report regression tests failed: {str(e)}"}


@frappe.whitelist()
def run_anbi_report_tests():
    """Run ANBI Donation Summary report tests"""
    try:
        import unittest

        from verenigingen.tests.backend.components.test_anbi_donation_summary_report import (
            TestANBIDonationSummaryReport,
            TestANBIDonationSummaryReportRegression
        )

        # Create test suite with both test classes
        suite = unittest.TestSuite()
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestANBIDonationSummaryReport))
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestANBIDonationSummaryReportRegression))
        
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        return {
            "success": result.wasSuccessful(),
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "message": f"ANBI report tests: {result.testsRun} run, {len(result.failures)} failures, {len(result.errors)} errors"}
    except Exception as e:
        return {"success": False, "message": f"ANBI report tests failed: {str(e)}"}


@frappe.whitelist()
def run_all_report_tests():
    """Run all report tests (overdue payments + ANBI donation summary)"""
    try:
        import unittest

        from verenigingen.tests.backend.components.test_overdue_payments_report_regression import TestOverduePaymentsReportRegression
        from verenigingen.tests.backend.components.test_anbi_donation_summary_report import (
            TestANBIDonationSummaryReport,
            TestANBIDonationSummaryReportRegression
        )

        # Create comprehensive test suite
        suite = unittest.TestSuite()
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestOverduePaymentsReportRegression))
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestANBIDonationSummaryReport))
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestANBIDonationSummaryReportRegression))
        
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        return {
            "success": result.wasSuccessful(),
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "message": f"All report tests: {result.testsRun} run, {len(result.failures)} failures, {len(result.errors)} errors"}
    except Exception as e:
        return {"success": False, "message": f"All report tests failed: {str(e)}"}


@frappe.whitelist()
def run_hybrid_report_tests():
    """Run report tests using the new hybrid framework"""
    try:
        from verenigingen.tests.utils.hybrid_report_tester import test_all_reports_hybrid
        
        result = test_all_reports_hybrid()
        
        if result.get("success"):
            detailed = result.get("detailed_results", {})
            total_reports = len(detailed)
            passed_reports = sum(1 for r in detailed.values() if r.get("success"))
            
            return {
                "success": True,
                "tests_run": total_reports,
                "failures": total_reports - passed_reports,
                "errors": 0,
                "message": f"Hybrid report tests: {passed_reports}/{total_reports} reports passed"
            }
        else:
            return {
                "success": False,
                "tests_run": 0,
                "failures": 1,
                "errors": 0,
                "message": f"Hybrid report tests failed: {result.get('message')}"
            }
    except Exception as e:
        return {"success": False, "message": f"Hybrid report tests failed: {str(e)}"}


@frappe.whitelist()
def run_comprehensive_report_tests():
    """Run both traditional and hybrid report tests"""
    try:
        # Run traditional tests
        traditional_result = run_all_report_tests()
        
        # Run hybrid tests  
        hybrid_result = run_hybrid_report_tests()
        
        overall_success = traditional_result.get("success", False) and hybrid_result.get("success", False)
        
        return {
            "success": overall_success,
            "message": f"Comprehensive tests: Traditional {'✅' if traditional_result.get('success') else '❌'}, Hybrid {'✅' if hybrid_result.get('success') else '❌'}",
            "traditional_tests": traditional_result,
            "hybrid_tests": hybrid_result
        }
    except Exception as e:
        return {"success": False, "message": f"Comprehensive report tests failed: {str(e)}"}
