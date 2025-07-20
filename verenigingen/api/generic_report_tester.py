"""
Generic Report Testing Framework
Can be used to test any Frappe query report for basic functionality and regression issues
"""

import frappe
from frappe import _


@frappe.whitelist()
def test_generic_report_loading(
    report_name, test_filters=None, expected_errors=None, regression_patterns=None
):
    """
    Generic function to test any Frappe query report

    Args:
        report_name: Name of the report to test
        test_filters: Dict of filters to apply (optional)
        expected_errors: List of error types that are acceptable (optional)
        regression_patterns: List of error patterns that indicate regressions (optional)
    """
    try:
        # Set default filters if none provided
        if test_filters is None:
            test_filters = {}

        # Set default regression patterns if none provided
        if regression_patterns is None:
            regression_patterns = []

        # Execute the report
        result = frappe.get_attr("frappe.desk.query_report.run")(
            report_name=report_name,
            filters=test_filters,
            ignore_prepared_report=False,
            are_default_filters=True,
        )

        if not result:
            return {
                "success": False,
                "message": f"Report '{report_name}' returned empty result",
                "page_loading": False,
                "report_name": report_name,
            }

        # Handle different return structures from query_report.run
        report_result = result
        if isinstance(result, dict) and "result" in result:
            report_result = result["result"]

        # Analyze result structure
        result_analysis = analyze_report_structure(report_result)

        return {
            "success": True,
            "message": f"Report '{report_name}' loaded successfully",
            "page_loading": True,
            "report_name": report_name,
            "filters_applied": test_filters,
            **result_analysis,
        }

    except Exception as e:
        error_msg = str(e)
        error_type = str(type(e).__name__)

        # Check for regression patterns
        for pattern in regression_patterns:
            if pattern.get("pattern") in error_msg:
                return {
                    "success": False,
                    "message": f"REGRESSION in '{report_name}': {pattern.get('description', 'Known issue has returned')}",
                    "error": error_msg,
                    "error_type": error_type,
                    "page_loading": False,
                    "regression_detected": True,
                    "report_name": report_name,
                }

        # Check if error is expected/acceptable
        if expected_errors and error_type in expected_errors:
            return {
                "success": True,
                "message": f"Report '{report_name}' failed with expected error type: {error_type}",
                "error": error_msg,
                "error_type": error_type,
                "page_loading": False,
                "expected_failure": True,
                "report_name": report_name,
            }

        return {
            "success": False,
            "message": f"Report '{report_name}' failed to load: {error_msg}",
            "error_type": error_type,
            "page_loading": False,
            "report_name": report_name,
        }


def analyze_report_structure(report_result):
    """Analyze the structure of a report result and return metadata"""
    analysis = {"format_type": str(type(report_result).__name__), "structure_valid": True}

    if isinstance(report_result, list):
        analysis.update(
            {
                "format_type": "list",
                "data_count": len(report_result),
                "has_data": len(report_result) > 0,
                "sample_item": report_result[0] if report_result else None,
            }
        )
    elif isinstance(report_result, dict):
        analysis.update(
            {
                "format_type": "dict",
                "available_keys": list(report_result.keys()),
                "columns_count": len(report_result.get("columns", [])),
                "data_count": len(report_result.get("data", [])),
                "has_columns": "columns" in report_result,
                "has_data": len(report_result.get("data", [])) > 0,
                "has_chart": "chart" in report_result and report_result.get("chart") is not None,
                "has_summary": "summary" in report_result and len(report_result.get("summary", [])) > 0,
                "sample_columns": [col.get("fieldname") for col in report_result.get("columns", [])[:5]]
                if report_result.get("columns")
                else [],
            }
        )
    else:
        analysis.update(
            {"structure_valid": False, "unexpected_type": True, "result_preview": str(report_result)[:200]}
        )

    return analysis


@frappe.whitelist()
def test_multiple_reports(report_configs):
    """
    Test multiple reports with their specific configurations

    Args:
        report_configs: List of dicts with report configurations
        Example: [
            {
                "report_name": "ANBI Donation Summary",
                "filters": {"from_date": "2024-01-01", "to_date": "2024-12-31"},
                "regression_patterns": [
                    {"pattern": "bsn_encrypted", "description": "Database field name issue"}
                ]
            }
        ]
    """
    if isinstance(report_configs, str):
        # Handle JSON string input
        import json

        report_configs = json.loads(report_configs)

    results = {}
    overall_success = True

    for config in report_configs:
        report_name = config.get("report_name")
        if not report_name:
            continue

        result = test_generic_report_loading(
            report_name=report_name,
            test_filters=config.get("filters"),
            expected_errors=config.get("expected_errors"),
            regression_patterns=config.get("regression_patterns"),
        )

        results[report_name] = result
        if not result.get("success", False):
            overall_success = False

    return {
        "success": overall_success,
        "message": f"Tested {len(report_configs)} reports. Overall: {'✅' if overall_success else '❌'}",
        "reports_tested": len(report_configs),
        "results": results,
    }


# Predefined configurations for common Verenigingen reports
VERENIGINGEN_REPORT_CONFIGS = [
    {
        "report_name": "ANBI Donation Summary",
        "filters": {"from_date": "2024-07-20", "to_date": "2025-07-20"},
        "regression_patterns": [
            {"pattern": "bsn_encrypted", "description": "Database field name issue with BSN field"},
            {"pattern": "rsin_encrypted", "description": "Database field name issue with RSIN field"},
            {"pattern": "anbi_consent_given", "description": "Database field name issue with consent field"},
            {"pattern": "Unknown column", "description": "SQL field reference error"},
        ],
    },
    {
        "report_name": "Overdue Member Payments",
        "filters": {"from_date": "2024-07-20", "to_date": "2025-07-20"},
        "regression_patterns": [
            {"pattern": "today", "description": "today() function import issue"},
            {"pattern": "UnboundLocalError", "description": "Variable scope issue"},
        ],
    },
]


@frappe.whitelist()
def test_all_verenigingen_reports():
    """Test all Verenigingen reports with their specific configurations"""
    return test_multiple_reports(VERENIGINGEN_REPORT_CONFIGS)


@frappe.whitelist()
def discover_and_test_reports(app_name="verenigingen"):
    """
    Discover all reports in an app and test them with basic configuration

    Args:
        app_name: Name of the app to discover reports from
    """
    try:
        # Get all reports for the app
        reports = frappe.get_all(
            "Report",
            filters={"module": ["like", f"%{app_name}%"], "report_type": "Script Report"},
            fields=["name", "module"],
        )

        # Test each report with basic configuration
        results = {}
        overall_success = True

        for report in reports:
            result = test_generic_report_loading(
                report_name=report.name,
                test_filters={"from_date": "2024-01-01", "to_date": "2024-12-31"},  # Basic date filter
            )

            results[report.name] = result
            if not result.get("success", False):
                overall_success = False

        return {
            "success": overall_success,
            "message": f"Auto-discovered and tested {len(reports)} reports from {app_name}",
            "app_name": app_name,
            "reports_found": len(reports),
            "report_names": [r.name for r in reports],
            "results": results,
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to discover reports from {app_name}: {str(e)}",
            "error_type": str(type(e).__name__),
        }
