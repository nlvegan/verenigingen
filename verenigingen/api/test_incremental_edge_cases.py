import json

import frappe


@frappe.whitelist()
def test_edge_cases():
    """Test edge cases for the incremental update system"""

    results = {
        "empty_member_test": None,
        "no_employee_test": None,
        "no_donor_test": None,
        "multiple_calls_test": None,
        "performance_benchmark": None,
    }

    try:
        # Test 1: Member with no employee link
        members_without_links = frappe.get_all("Member", filters={"employee": ["is", "not set"]}, limit=1)

        if members_without_links:
            member_doc = frappe.get_doc("Member", members_without_links[0].name)
            result = member_doc.incremental_update_history_tables()

            results["empty_member_test"] = {
                "success": True,
                "member": members_without_links[0].name,
                "result": result,
                "expected_no_changes": result["volunteer_expenses"]["count"] == 0
                and result["donations"]["count"] == 0,
            }
        else:
            results["empty_member_test"] = {"success": False, "error": "No member without links found"}

        # Test 2: Member with employee but no recent expense claims
        members_with_employee = frappe.get_all("Member", filters={"employee": ["!=", ""]}, limit=5)

        if members_with_employee:
            for member_data in members_with_employee:
                member_doc = frappe.get_doc("Member", member_data.name)

                # Check if this employee has any expense claims
                expense_count = frappe.db.count("Expense Claim", {"employee": member_doc.employee})

                if expense_count == 0:
                    result = member_doc.incremental_update_history_tables()
                    results["no_employee_test"] = {
                        "success": True,
                        "member": member_data.name,
                        "employee": member_doc.employee,
                        "result": result,
                        "handled_no_claims": True,
                    }
                    break

            if results["no_employee_test"] is None:
                results["no_employee_test"] = {
                    "success": True,
                    "note": "All members with employee links have expense claims",
                }

        # Test 3: Multiple consecutive calls (should be idempotent)
        test_member = "Assoc-Member-2025-07-0030"
        if frappe.db.exists("Member", test_member):
            member_doc = frappe.get_doc("Member", test_member)

            # First call
            result1 = member_doc.incremental_update_history_tables()

            # Second call immediately after (should show no changes)
            member_doc.reload()  # Reload to get fresh state
            result2 = member_doc.incremental_update_history_tables()

            results["multiple_calls_test"] = {
                "success": True,
                "first_call": result1,
                "second_call": result2,
                "idempotent": (
                    result2["volunteer_expenses"]["count"] == 0 and result2["donations"]["count"] == 0
                ),
                "member": test_member,
            }

        # Test 4: Performance benchmark
        import time

        test_member = "Assoc-Member-2025-07-0030"
        if frappe.db.exists("Member", test_member):
            member_doc = frappe.get_doc("Member", test_member)

            # Run multiple times to get average
            times = []
            for i in range(5):
                start_time = time.time()
                result = member_doc.incremental_update_history_tables()
                end_time = time.time()
                times.append((end_time - start_time) * 1000)  # Convert to ms
                member_doc.reload()  # Reset state

            avg_time = sum(times) / len(times)

            results["performance_benchmark"] = {
                "success": True,
                "average_time_ms": avg_time,
                "all_times_ms": times,
                "acceptable_performance": avg_time < 1000,  # Should be under 1 second
                "runs": len(times),
            }

        return results

    except Exception as e:
        frappe.log_error(f"Edge case testing failed: {str(e)}", "Edge Case Test Error")
        return {"error": str(e), "partial_results": results}


@frappe.whitelist()
def test_interface_compatibility():
    """Test that the interface matches what JavaScript expects"""

    # Get test member
    test_member = "Assoc-Member-2025-07-0030"
    if not frappe.db.exists("Member", test_member):
        test_member = frappe.db.get_value("Member", {"employee": ["!=", ""]}, "name")

    if not test_member:
        return {"error": "No suitable member found"}

    member_doc = frappe.get_doc("Member", test_member)
    result = member_doc.incremental_update_history_tables()

    # Check interface structure
    interface_check = {
        "has_overall_success": "overall_success" in result,
        "overall_success_type": type(result.get("overall_success", None)).__name__,
        "has_volunteer_expenses": "volunteer_expenses" in result,
        "volunteer_expenses_is_dict": isinstance(result.get("volunteer_expenses"), dict),
        "volunteer_expenses_has_success": "success" in result.get("volunteer_expenses", {}),
        "volunteer_expenses_has_count": "count" in result.get("volunteer_expenses", {}),
        "has_donations": "donations" in result,
        "donations_is_dict": isinstance(result.get("donations"), dict),
        "donations_has_success": "success" in result.get("donations", {}),
        "donations_has_count": "count" in result.get("donations", {}),
        "has_message": "message" in result,
        "message_type": type(result.get("message", None)).__name__,
    }

    # Test JavaScript-style access
    js_compatible = True
    try:
        # These are the kind of accesses JavaScript would make
        overall_success = result["overall_success"]
        volunteer_success = result["volunteer_expenses"]["success"]
        volunteer_count = result["volunteer_expenses"]["count"]
        donation_success = result["donations"]["success"]
        donation_count = result["donations"]["count"]
        message = result["message"]

        # Verify types
        if not isinstance(overall_success, bool):
            js_compatible = False
        if not isinstance(volunteer_success, bool):
            js_compatible = False
        if not isinstance(volunteer_count, (int, float)):
            js_compatible = False
        if not isinstance(donation_success, bool):
            js_compatible = False
        if not isinstance(donation_count, (int, float)):
            js_compatible = False
        if not isinstance(message, str):
            js_compatible = False

    except (KeyError, TypeError) as e:
        js_compatible = False
        interface_check["access_error"] = str(e)

    return {
        "member_tested": test_member,
        "result_structure": result,
        "interface_check": interface_check,
        "js_compatible": js_compatible,
        "all_checks_pass": all(interface_check.values()),
    }
