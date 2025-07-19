import frappe


@frappe.whitelist()
def test_duplicate_query():
    """Test the duplicate detection query"""

    # Test filters
    filters = {"posting_date": ["between", ["2025-06-30", "2025-07-14"]], "grand_total": 0}

    try:
        results = frappe.get_all(
            "Sales Invoice", filters=filters, fields=["name", "customer", "grand_total"], limit=5
        )

        return {"success": True, "count": len(results), "results": results}
    except Exception as e:
        return {"success": False, "error": str(e), "filters": filters}
