"""
API functions to test report page loading simulation
"""

import frappe
from frappe import _


@frappe.whitelist()
def simulate_anbi_report_page_loading():
    """Simulate normal page loading for ANBI Donation Summary report"""
    try:
        # Simulate the exact same call that would be made when the page loads
        result = frappe.get_attr("frappe.desk.query_report.run")(
            report_name="ANBI Donation Summary",
            filters={"from_date": "2024-07-20", "to_date": "2025-07-20"},
            ignore_prepared_report=False,
            are_default_filters=True,
        )

        if not result:
            return {"success": False, "message": "Report returned empty result", "page_loading": False}

        # Check if result has expected structure from query_report.run
        if not isinstance(result, dict):
            return {
                "success": False,
                "message": f"Report returned unexpected type: {type(result)}",
                "result_structure": str(result)[:200],
                "page_loading": False,
            }

        # query_report.run can return different structures depending on the query
        # Let's handle both cases: direct list/dict or wrapped in result key
        report_result = result
        if isinstance(result, dict) and "result" in result:
            report_result = result["result"]

        # Handle different return structures
        if isinstance(report_result, list):
            # Direct list return from some reports
            return {
                "success": True,
                "message": "ANBI Donation Summary report page loading simulation successful (list format)",
                "page_loading": True,
                "data_count": len(report_result),
                "columns_count": "N/A (list format)",
                "format_type": "list",
            }
        elif isinstance(report_result, dict):
            # Dict format with columns and data
            columns = report_result.get("columns", [])
            data = report_result.get("data", [])

            return {
                "success": True,
                "message": "ANBI Donation Summary report page loading simulation successful (dict format)",
                "page_loading": True,
                "columns_count": len(columns),
                "data_count": len(data),
                "has_chart": "chart" in report_result,
                "sample_columns": [col.get("fieldname") for col in columns[:5]] if columns else [],
                "format_type": "dict",
            }
        else:
            return {
                "success": False,
                "message": f"Report result has unexpected structure: {type(report_result)}",
                "result_preview": str(report_result)[:200],
                "page_loading": False,
            }

    except Exception as e:
        # Check for the specific errors that were fixed
        error_msg = str(e)

        if "Unknown column" in error_msg and any(
            field in error_msg for field in ["bsn_encrypted", "rsin_encrypted", "anbi_consent_given"]
        ):
            return {
                "success": False,
                "message": "REGRESSION: Database field name issue has returned in page loading",
                "error": error_msg,
                "error_type": str(type(e).__name__),
                "page_loading": False,
            }

        if "OperationalError" in str(type(e)) and "1054" in error_msg:
            return {
                "success": False,
                "message": "REGRESSION: SQL field reference error has returned in page loading",
                "error": error_msg,
                "error_type": "OperationalError",
                "page_loading": False,
            }

        return {
            "success": False,
            "message": f"Page loading simulation failed: {error_msg}",
            "error_type": str(type(e).__name__),
            "page_loading": False,
        }


@frappe.whitelist()
def simulate_overdue_payments_report_page_loading():
    """Simulate normal page loading for Overdue Member Payments report"""
    try:
        # Simulate the exact same call that would be made when the page loads
        result = frappe.get_attr("frappe.desk.query_report.run")(
            report_name="Overdue Member Payments",
            filters={"from_date": "2024-07-20", "to_date": "2025-07-20"},
            ignore_prepared_report=False,
            are_default_filters=True,
        )

        if not result:
            return {"success": False, "message": "Report returned empty result", "page_loading": False}

        # Handle different return structures from query_report.run
        report_result = result
        if isinstance(result, dict) and "result" in result:
            report_result = result["result"]

        # Handle different return formats
        if isinstance(report_result, list):
            # Some reports return a direct list
            return {
                "success": True,
                "message": "Overdue Member Payments report page loading simulation successful (list format)",
                "page_loading": True,
                "data_count": len(report_result),
                "format_type": "list",
            }
        elif isinstance(report_result, dict):
            # Dict format with structured data
            return {
                "success": True,
                "message": "Overdue Member Payments report page loading simulation successful (dict format)",
                "page_loading": True,
                "columns_count": len(report_result.get("columns", [])),
                "data_count": len(report_result.get("data", [])),
                "has_chart": report_result.get("chart") is not None,
                "has_summary": len(report_result.get("summary", [])) > 0,
                "format_type": "dict",
            }
        else:
            return {
                "success": False,
                "message": f"Report result has unexpected structure: {type(report_result)}",
                "page_loading": False,
            }

    except UnboundLocalError as e:
        if "today" in str(e):
            return {
                "success": False,
                "message": "REGRESSION: today() function import issue has returned in page loading",
                "error": str(e),
                "error_type": "UnboundLocalError",
                "page_loading": False,
            }
        else:
            return {
                "success": False,
                "message": f"UnboundLocalError (not today related) in page loading: {str(e)}",
                "error_type": "UnboundLocalError",
                "page_loading": False,
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Page loading simulation failed: {str(e)}",
            "error_type": str(type(e).__name__),
            "page_loading": False,
        }


@frappe.whitelist()
def simulate_both_reports_page_loading():
    """Simulate page loading for both reports"""
    results = {}

    # Test ANBI report page loading
    anbi_result = simulate_anbi_report_page_loading()
    results["anbi_donation_summary"] = anbi_result

    # Test Overdue Payments report page loading
    overdue_result = simulate_overdue_payments_report_page_loading()
    results["overdue_member_payments"] = overdue_result

    # Overall success
    overall_success = anbi_result.get("success", False) and overdue_result.get("success", False)
    overall_page_loading = anbi_result.get("page_loading", False) and overdue_result.get(
        "page_loading", False
    )

    return {
        "success": overall_success,
        "page_loading": overall_page_loading,
        "message": f"Page loading simulation completed. ANBI: {'✅' if anbi_result.get('success') else '❌'}, Overdue: {'✅' if overdue_result.get('success') else '❌'}",
        "details": results,
    }
