"""
API functions to test report fixes
"""

import frappe
from frappe import _


@frappe.whitelist()
def test_anbi_report_fix():
    """Test the ANBI Donation Summary report fix"""
    try:
        # Import and execute the report
        from verenigingen.verenigingen.report.anbi_donation_summary.anbi_donation_summary import execute

        # Test with basic filters
        result = execute({"from_date": "2024-07-20", "to_date": "2025-07-20"})

        if not isinstance(result, tuple) or len(result) != 2:
            return {
                "success": False,
                "message": "Report returned unexpected structure",
                "result_type": str(type(result)),
                "result_length": len(result) if hasattr(result, "__len__") else "N/A",
            }

        columns, data = result

        return {
            "success": True,
            "message": "ANBI Donation Summary report executed successfully",
            "columns_count": len(columns),
            "data_count": len(data),
            "sample_columns": [col.get("fieldname") for col in columns[:5]] if columns else [],
        }

    except Exception as e:
        # Check for the specific error that was fixed
        if "Unknown column" in str(e) and any(
            field in str(e) for field in ["bsn_encrypted", "rsin_encrypted", "anbi_consent_given"]
        ):
            return {
                "success": False,
                "message": "REGRESSION: Database field name issue has returned",
                "error": str(e),
                "error_type": str(type(e).__name__),
            }

        return {
            "success": False,
            "message": f"Report execution failed: {str(e)}",
            "error_type": str(type(e).__name__),
        }


@frappe.whitelist()
def test_overdue_payments_report_fix():
    """Test the Overdue Member Payments report fix"""
    try:
        # Import and execute the report
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import execute

        # Test with basic filters
        result = execute({"from_date": "2024-07-20", "to_date": "2025-07-20"})

        if not isinstance(result, tuple) or len(result) != 5:
            return {
                "success": False,
                "message": "Report returned unexpected structure",
                "result_type": str(type(result)),
                "result_length": len(result) if hasattr(result, "__len__") else "N/A",
            }

        columns, data, message, chart, summary = result

        return {
            "success": True,
            "message": "Overdue Member Payments report executed successfully",
            "columns_count": len(columns),
            "data_count": len(data),
            "has_chart": chart is not None,
            "summary_count": len(summary) if summary else 0,
        }

    except UnboundLocalError as e:
        if "today" in str(e):
            return {
                "success": False,
                "message": "REGRESSION: today() function import issue has returned",
                "error": str(e),
                "error_type": "UnboundLocalError",
            }
        else:
            return {
                "success": False,
                "message": f"UnboundLocalError (not today related): {str(e)}",
                "error_type": "UnboundLocalError",
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Report execution failed: {str(e)}",
            "error_type": str(type(e).__name__),
        }


@frappe.whitelist()
def test_both_report_fixes():
    """Test both report fixes together"""
    results = {}

    # Test ANBI report
    anbi_result = test_anbi_report_fix()
    results["anbi_donation_summary"] = anbi_result

    # Test Overdue Payments report
    overdue_result = test_overdue_payments_report_fix()
    results["overdue_member_payments"] = overdue_result

    # Overall success
    overall_success = anbi_result.get("success", False) and overdue_result.get("success", False)

    return {
        "success": overall_success,
        "message": f"Report tests completed. ANBI: {'✅' if anbi_result.get('success') else '❌'}, Overdue: {'✅' if overdue_result.get('success') else '❌'}",
        "details": results,
    }
