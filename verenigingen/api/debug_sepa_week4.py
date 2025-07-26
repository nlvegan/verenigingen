import frappe

from verenigingen.utils.sepa_admin_reporting import SEPAAdminReportGenerator


@frappe.whitelist()
def check_sepa_admin_methods():
    """Debug function to check if SEPA admin reporting methods exist"""
    try:
        generator = SEPAAdminReportGenerator()

        methods_to_check = [
            "_analyze_mandate_lifecycle",
            "_analyze_performance_trends",
            "_calculate_trend",
            "_calculate_coefficient_of_variation",
        ]

        results = {}
        for method_name in methods_to_check:
            results[method_name] = hasattr(generator, method_name)

        return {
            "success": True,
            "methods": results,
            "class_methods": [method for method in dir(generator) if not method.startswith("__")],
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_mandate_lifecycle_method():
    """Test the mandate lifecycle analysis method directly"""
    try:
        generator = SEPAAdminReportGenerator()

        # Test with sample data
        sample_data = [
            {"status": "Active", "creation": "2025-01-15 10:00:00"},
            {"status": "Pending", "creation": "2025-01-20 10:00:00"},
        ]

        result = generator._analyze_mandate_lifecycle(sample_data)

        return {"success": True, "result": result}

    except Exception as e:
        return {"success": False, "error": str(e)}
