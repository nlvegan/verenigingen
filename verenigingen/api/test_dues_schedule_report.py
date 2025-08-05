import frappe


@frappe.whitelist()
def test_dues_schedule_report_permissions():
    """Test if the Members Without Dues Schedule report can run without permission errors"""

    try:
        # Import the report execute function
        from verenigingen.verenigingen.report.members_without_dues_schedule.members_without_dues_schedule import (
            execute,
        )

        # Test running the report with minimal filters
        test_filters = {
            "problems_only": True,  # Only show problematic schedules
            "include_terminated": False,
            "include_suspended": False,
            "include_pending": False,
        }

        # Execute the report
        columns, data, message, chart, summary = execute(test_filters)

        return {
            "success": True,
            "message": "Report executed successfully without permission errors",
            "column_count": len(columns),
            "record_count": len(data) if data else 0,
            "has_summary": bool(summary),
            "has_chart": bool(chart),
            "sample_columns": [col.split(":")[0] for col in columns[:5]] if columns else [],
            "test_filters": test_filters,
        }

    except frappe.PermissionError as pe:
        return {
            "success": False,
            "error_type": "PermissionError",
            "error": str(pe),
            "message": "Report still has permission issues",
        }
    except Exception as e:
        return {
            "success": False,
            "error_type": type(e).__name__,
            "error": str(e),
            "message": "Report failed with non-permission error",
        }


@frappe.whitelist()
def test_report_as_verenigingen_admin():
    """Test report access specifically as Verenigingen Administrator role"""

    try:
        # Check current user and roles
        current_user = frappe.session.user
        current_roles = frappe.get_roles()

        # Check if current user has Verenigingen Administrator role
        has_admin_role = "Verenigingen Administrator" in current_roles

        # Test Customer access specifically
        try:
            customer_test = frappe.db.get_value(
                "Customer", {}, ["name", "customer_name"], limit=1, as_dict=True
            )
            customer_access = True
            customer_error = None
        except Exception as e:
            customer_access = False
            customer_error = str(e)
            customer_test = None

        # Test Member access
        try:
            member_test = frappe.db.get_value(
                "Member", {}, ["name", "full_name", "customer"], limit=1, as_dict=True
            )
            member_access = True
            member_error = None
        except Exception as e:
            member_access = False
            member_error = str(e)
            member_test = None

        return {
            "success": True,
            "current_user": current_user,
            "has_verenigingen_admin_role": has_admin_role,
            "all_roles": current_roles,
            "customer_access": customer_access,
            "customer_error": customer_error,
            "customer_sample": customer_test,
            "member_access": member_access,
            "member_error": member_error,
            "member_sample": member_test,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
