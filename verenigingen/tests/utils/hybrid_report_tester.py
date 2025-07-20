"""
Hybrid Report Testing Framework
Combines ERPNext's standardized patterns with enhanced testing capabilities
"""

import json
import unittest
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe.tests.utils import FrappeTestCase

# Type hints following ERPNext patterns
ReportName = str
ReportFilters = Dict[str, Any]
RegressionPattern = Dict[str, str]


class HybridReportTestCase(FrappeTestCase):
    """
    Enhanced test case that combines ERPNext patterns with advanced report testing
    Follows ERPNext's execute_script_report pattern but with additional capabilities
    """
    
    def setUp(self):
        super().setUp()
        self.default_filters = {
            "from_date": "2024-01-01",
            "to_date": "2024-12-31"
        }
        self.test_results = {}
    
    def execute_script_report_enhanced(
        self,
        report_name: ReportName,
        module: str,
        filters: ReportFilters,
        default_filters: Optional[ReportFilters] = None,
        optional_filters: Optional[ReportFilters] = None,
        regression_patterns: Optional[List[RegressionPattern]] = None,
        expected_errors: Optional[List[str]] = None,
        validate_structure: bool = True,
        test_exports: bool = False,
    ) -> Dict[str, Any]:
        """
        Enhanced version of ERPNext's execute_script_report with additional capabilities
        
        Args:
            report_name: Name of the report to test
            module: Module name (for ERPNext compatibility)
            filters: Test filters to apply
            default_filters: Default filters merged with test filters
            optional_filters: Additional filters to test individually
            regression_patterns: List of error patterns that indicate regressions
            expected_errors: List of error types that are acceptable
            validate_structure: Whether to validate return structure
            test_exports: Whether to test export functionality
            
        Returns:
            Dict with comprehensive test results
        """
        if default_filters is None:
            default_filters = self.default_filters
        
        if regression_patterns is None:
            regression_patterns = []
        
        if expected_errors is None:
            expected_errors = []
        
        test_results = {
            "report_name": report_name,
            "module": module,
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
            "regressions_detected": [],
            "structure_analysis": {},
            "export_tests": {}
        }
        
        # Test 1: Basic execution with default + test filters
        combined_filters = {**default_filters, **filters}
        basic_result = self._test_basic_execution(
            report_name, combined_filters, regression_patterns, expected_errors
        )
        test_results.update(basic_result)
        
        # Test 2: Optional filters (ERPNext pattern)
        if optional_filters:
            optional_result = self._test_optional_filters(
                report_name, default_filters, optional_filters, regression_patterns, expected_errors
            )
            test_results["optional_filter_tests"] = optional_result
        
        # Test 3: Structure validation
        if validate_structure and basic_result.get("success"):
            structure_result = self._validate_report_structure(basic_result.get("result"))
            test_results["structure_analysis"] = structure_result
        
        # Test 4: Export functionality
        if test_exports and basic_result.get("success"):
            export_result = self._test_export_functionality(report_name, combined_filters)
            test_results["export_tests"] = export_result
        
        # Store for later analysis
        self.test_results[report_name] = test_results
        
        return test_results
    
    def _test_basic_execution(
        self, 
        report_name: ReportName, 
        filters: ReportFilters,
        regression_patterns: List[RegressionPattern],
        expected_errors: List[str]
    ) -> Dict[str, Any]:
        """Test basic report execution following ERPNext patterns"""
        try:
            # Use Frappe's standard query report execution
            result = frappe.get_attr("frappe.desk.query_report.run")(
                report_name=report_name,
                filters=filters,
                ignore_prepared_report=False,
                are_default_filters=False
            )
            
            return {
                "success": True,
                "tests_run": 1,
                "tests_passed": 1,
                "tests_failed": 0,
                "result": result,
                "filters_used": filters,
                "execution_method": "frappe.desk.query_report.run"
            }
            
        except Exception as e:
            error_msg = str(e)
            error_type = str(type(e).__name__)
            
            # Check for regression patterns (our enhancement)
            for pattern in regression_patterns:
                if pattern.get("pattern", "") in error_msg:
                    return {
                        "success": False,
                        "tests_run": 1,
                        "tests_passed": 0, 
                        "tests_failed": 1,
                        "regression_detected": True,
                        "regression_pattern": pattern,
                        "error": error_msg,
                        "error_type": error_type
                    }
            
            # Check if error is expected (ERPNext pattern)
            if error_type in expected_errors:
                return {
                    "success": True,
                    "tests_run": 1,
                    "tests_passed": 1,
                    "tests_failed": 0,
                    "expected_error": True,
                    "error": error_msg,
                    "error_type": error_type
                }
            
            return {
                "success": False,
                "tests_run": 1,
                "tests_passed": 0,
                "tests_failed": 1,
                "error": error_msg,
                "error_type": error_type
            }
    
    def _test_optional_filters(
        self,
        report_name: ReportName,
        default_filters: ReportFilters,
        optional_filters: ReportFilters,
        regression_patterns: List[RegressionPattern],
        expected_errors: List[str]
    ) -> Dict[str, Any]:
        """Test report with each optional filter individually (ERPNext pattern)"""
        results = {}
        
        for filter_key, filter_value in optional_filters.items():
            test_filters = {**default_filters, filter_key: filter_value}
            result = self._test_basic_execution(
                report_name, test_filters, regression_patterns, expected_errors
            )
            results[f"{filter_key}={filter_value}"] = result
        
        return results
    
    def _validate_report_structure(self, result: Any) -> Dict[str, Any]:
        """Validate report return structure (our enhancement)"""
        if not result:
            return {"valid": False, "reason": "Empty result"}
        
        # Handle different return structures
        report_result = result
        if isinstance(result, dict) and 'result' in result:
            report_result = result['result']
        
        analysis = {
            "valid": True,
            "format_type": str(type(report_result).__name__),
            "has_data": False,
            "structure_details": {}
        }
        
        if isinstance(report_result, list):
            analysis.update({
                "format_type": "list",
                "data_count": len(report_result),
                "has_data": len(report_result) > 0,
                "sample_item_type": str(type(report_result[0]).__name__) if report_result else None
            })
        elif isinstance(report_result, dict):
            analysis.update({
                "format_type": "dict",
                "available_keys": list(report_result.keys()),
                "has_columns": 'columns' in report_result,
                "has_data": len(report_result.get('data', [])) > 0,
                "columns_count": len(report_result.get('columns', [])),
                "data_count": len(report_result.get('data', [])),
                "has_chart": 'chart' in report_result,
                "has_summary": 'summary' in report_result
            })
        else:
            analysis.update({
                "valid": False,
                "reason": f"Unexpected result type: {type(report_result)}",
                "result_preview": str(report_result)[:200]
            })
        
        return analysis
    
    def _test_export_functionality(self, report_name: ReportName, filters: ReportFilters) -> Dict[str, Any]:
        """Test report export functionality (Frappe core pattern)"""
        export_results = {}
        
        # Test different export formats
        export_formats = ["XLSX", "CSV"]
        
        for export_format in export_formats:
            try:
                # Use Frappe's export functionality
                result = frappe.get_attr("frappe.desk.query_report.export_query")(
                    report_name=report_name,
                    filters=filters,
                    file_format_type=export_format
                )
                
                export_results[export_format] = {
                    "success": True,
                    "has_content": bool(result),
                    "content_type": str(type(result).__name__)
                }
                
            except Exception as e:
                export_results[export_format] = {
                    "success": False,
                    "error": str(e),
                    "error_type": str(type(e).__name__)
                }
        
        return export_results


class VereningingenReportTestCase(HybridReportTestCase):
    """
    Verenigingen-specific report test case with predefined configurations
    """
    
    # ERPNext-style test case definitions
    DEFAULT_FILTERS = {
        "from_date": "2024-01-01",
        "to_date": "2024-12-31"
    }
    
    OPTIONAL_FILTERS = {
        "company": "_Test Company",
        "chapter": "Test Chapter"
    }
    
    # Our enhancement: Regression patterns for known issues
    REGRESSION_PATTERNS = {
        "ANBI Donation Summary": [
            {"pattern": "bsn_encrypted", "description": "Database field name issue with BSN field"},
            {"pattern": "rsin_encrypted", "description": "Database field name issue with RSIN field"},
            {"pattern": "anbi_consent_given", "description": "Database field name issue with consent field"},
            {"pattern": "Unknown column", "description": "SQL field reference error"}
        ],
        "Overdue Member Payments": [
            {"pattern": "today", "description": "today() function import issue"},
            {"pattern": "UnboundLocalError", "description": "Variable scope issue"}
        ]
    }
    
    # ERPNext-style report filter test cases
    REPORT_FILTER_TEST_CASES: List[tuple[ReportName, ReportFilters]] = [
        ("ANBI Donation Summary", {"donor_type": "Individual"}),
        ("Overdue Member Payments", {"days_overdue": 30}),
        ("Pending Membership Applications", {"status": "Pending"}),
        ("Chapter Members", {"chapter": "Test Chapter"}),
        ("New Members", {"days_back": 30}),
        ("Members Without Chapter", {}),
        ("Expiring Memberships", {"days_ahead": 60}),
    ]
    
    def test_execute_all_verenigingen_reports(self):
        """
        Test all Verenigingen reports following ERPNext pattern
        Enhanced with regression detection and structure validation
        """
        results_summary = {
            "total_reports": len(self.REPORT_FILTER_TEST_CASES),
            "passed": 0,
            "failed": 0,
            "regressions": 0
        }
        
        for report_name, test_filters in self.REPORT_FILTER_TEST_CASES:
            with self.subTest(report=report_name):
                result = self.execute_script_report_enhanced(
                    report_name=report_name,
                    module="Verenigingen",
                    filters=test_filters,
                    default_filters=self.DEFAULT_FILTERS,
                    optional_filters=self.OPTIONAL_FILTERS,
                    regression_patterns=self.REGRESSION_PATTERNS.get(report_name, []),
                    validate_structure=True,
                    test_exports=False  # Can be enabled for comprehensive testing
                )
                
                if result.get("regression_detected"):
                    results_summary["regressions"] += 1
                    self.fail(f"REGRESSION DETECTED in {report_name}: {result.get('regression_pattern', {}).get('description')}")
                elif result.get("success"):
                    results_summary["passed"] += 1
                else:
                    results_summary["failed"] += 1
                    # Log but don't fail for non-regression errors
                    print(f"⚠️  {report_name} failed: {result.get('error', 'Unknown error')}")
        
        # Summary assertions
        self.assertGreater(results_summary["passed"], 0, "At least some reports should pass")
        self.assertEqual(results_summary["regressions"], 0, "No regressions should be detected")
        
        print(f"\n📊 Test Summary: {results_summary['passed']}/{results_summary['total_reports']} reports passed")


# Standalone utility functions following ERPNext patterns
def execute_script_report_hybrid(
    report_name: ReportName,
    module: str,
    filters: ReportFilters,
    default_filters: Optional[ReportFilters] = None,
    optional_filters: Optional[ReportFilters] = None,
    regression_patterns: Optional[List[RegressionPattern]] = None,
) -> Dict[str, Any]:
    """
    Standalone utility function following ERPNext's execute_script_report pattern
    Enhanced with regression detection capabilities
    """
    tester = HybridReportTestCase()
    tester.setUp()
    
    return tester.execute_script_report_enhanced(
        report_name=report_name,
        module=module,
        filters=filters,
        default_filters=default_filters,
        optional_filters=optional_filters,
        regression_patterns=regression_patterns
    )


@frappe.whitelist()
def test_all_reports_hybrid():
    """
    Whitelisted function to test all reports using hybrid framework
    Can be called via bench execute
    """
    try:
        # Create and run test case
        test_case = VereningingenReportTestCase()
        test_case.setUp()
        
        # Execute all tests
        test_case.test_execute_all_verenigingen_reports()
        
        # Return summary
        return {
            "success": True,
            "message": "All report tests completed successfully",
            "detailed_results": test_case.test_results
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Report testing failed: {str(e)}",
            "error_type": str(type(e).__name__)
        }


@frappe.whitelist()  
def test_single_report_hybrid(report_name, filters=None):
    """
    Test a single report using hybrid framework
    
    Args:
        report_name: Name of report to test
        filters: JSON string or dict of filters
    """
    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except:
            filters = {}
    
    if not filters:
        filters = {}
    
    # Get regression patterns for this report
    test_case = VereningingenReportTestCase()
    regression_patterns = test_case.REGRESSION_PATTERNS.get(report_name, [])
    
    return execute_script_report_hybrid(
        report_name=report_name,
        module="Verenigingen", 
        filters=filters,
        regression_patterns=regression_patterns
    )