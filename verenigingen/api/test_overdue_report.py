"""
API test for Overdue Member Payments report
"""

import frappe


@frappe.whitelist()
def test_overdue_payments_report():
    """Test the Overdue Member Payments report"""

    try:
        # Import the report module
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import execute

        # Test with sample filters
        filters = {"from_date": "2025-04-20", "to_date": "2025-07-20"}

        print(f"Testing with filters: {filters}")

        # Execute the report
        result = execute(filters)

        # Test without filters
        print("Testing without filters...")
        result_no_filters = execute()

        # Validate result structure
        if isinstance(result, tuple) and len(result) >= 2 and isinstance(result_no_filters, tuple):
            columns, data = result[:2]
            columns_nf, data_nf = result_no_filters[:2]

            return {
                "success": True,
                "message": "Report executed successfully with and without filters",
                "with_filters": {"columns_count": len(columns), "data_rows": len(data) if data else 0},
                "without_filters": {
                    "columns_count": len(columns_nf),
                    "data_rows": len(data_nf) if data_nf else 0,
                },
                "filters_tested": filters,
            }
        else:
            return {
                "success": False,
                "message": "Report returned unexpected result structure",
                "result_type": str(type(result)),
            }

    except Exception as e:
        import traceback

        return {
            "success": False,
            "message": f"Report test failed: {str(e)}",
            "traceback": traceback.format_exc(),
        }
