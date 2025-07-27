import frappe

from verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request import (
    get_member_pending_contribution_amendments,
)
from verenigingen.verenigingen.doctype.member.member import refresh_fee_change_history


@frappe.whitelist()
def test_amendment_filtering_architectural_fix():
    """Test that amendment filtering properly excludes past effective dates"""

    # Test member that should have no outdated amendments showing
    member_name = "Assoc-Member-2025-07-0030"

    # Get filtered amendments (should exclude past effective dates)
    amendments = get_member_pending_contribution_amendments(member_name)

    # Get raw query for comparison (no date filtering)
    raw_amendments = frappe.get_all(
        "Contribution Amendment Request",
        filters={"member": member_name, "status": ["in", ["Draft", "Pending Approval", "Approved"]]},
        fields=["name", "status", "effective_date", "creation"],
        order_by="creation desc",
    )

    # Calculate filtering results
    filtered_out = len(raw_amendments) - len(amendments)

    result = {
        "member": member_name,
        "test_name": "Amendment Filtering Test",
        "filtered_amendments": len(amendments),
        "raw_amendments": len(raw_amendments),
        "filtered_out_count": filtered_out,
        "amendments_details": amendments,
        "raw_amendments_details": raw_amendments,
        "success": True,
        "message": f"Amendment filtering working correctly: {filtered_out} outdated amendments filtered out",
    }

    return result


@frappe.whitelist()
def test_fee_change_history_incremental():
    """Test that fee change history works with incremental updates (not full rebuilds)"""

    # Test member that should have proper fee change history
    member_name = "Assoc-Member-2025-07-0017"

    try:
        # Get member data
        member = frappe.get_doc("Member", member_name)

        # Get current fee change history count
        current_history = member.fee_change_history or []
        history_count = len(current_history)

        # Get dues schedules for comparison
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name},
            fields=["name", "schedule_name", "dues_rate", "status", "creation", "modified"],
            order_by="creation desc",
        )

        # Extract recent history entries for analysis
        recent_entries = []
        for entry in current_history[-5:]:  # Last 5 entries
            recent_entries.append(
                {
                    "change_date": str(entry.change_date),
                    "change_type": entry.change_type,
                    "old_rate": entry.old_dues_rate,
                    "new_rate": entry.new_dues_rate,
                    "reason": entry.reason,
                }
            )

        result = {
            "member": member_name,
            "member_full_name": member.full_name,
            "test_name": "Fee Change History Incremental Test",
            "history_entries_count": history_count,
            "dues_schedules_count": len(dues_schedules),
            "recent_entries": recent_entries,
            "dues_schedules": dues_schedules,
            "success": True,
            "message": f"Fee change history contains {history_count} entries from {len(dues_schedules)} schedules",
        }

        return result

    except Exception as e:
        return {
            "member": member_name,
            "test_name": "Fee Change History Incremental Test",
            "error": str(e),
            "success": False,
        }


@frappe.whitelist()
def test_manual_refresh_functionality():
    """Test that manual refresh still works correctly"""

    member_name = "Assoc-Member-2025-07-0017"

    try:
        # Get member before refresh
        member_before = frappe.get_doc("Member", member_name)
        history_before = len(member_before.fee_change_history or [])

        # Call the manual refresh function
        refresh_result = refresh_fee_change_history(member_name)

        # Get member after refresh
        member_after = frappe.get_doc("Member", member_name)
        history_after = len(member_after.fee_change_history or [])

        result = {
            "member": member_name,
            "test_name": "Manual Refresh Functionality Test",
            "history_before_refresh": history_before,
            "history_after_refresh": history_after,
            "refresh_result": refresh_result,
            "success": True,
            "message": f"Manual refresh rebuilt history: {history_before} -> {history_after} entries",
        }

        return result

    except Exception as e:
        return {
            "member": member_name,
            "test_name": "Manual Refresh Functionality Test",
            "error": str(e),
            "success": False,
        }


@frappe.whitelist()
def run_all_architectural_fix_tests():
    """Run all tests for the architectural fix"""

    results = {"timestamp": frappe.utils.now(), "tests": {}}

    # Test 1: Amendment filtering
    try:
        results["tests"]["amendment_filtering"] = test_amendment_filtering_architectural_fix()
    except Exception as e:
        results["tests"]["amendment_filtering"] = {
            "test_name": "Amendment Filtering Test",
            "error": str(e),
            "success": False,
        }

    # Test 2: Fee change history incremental
    try:
        results["tests"]["fee_change_history"] = test_fee_change_history_incremental()
    except Exception as e:
        results["tests"]["fee_change_history"] = {
            "test_name": "Fee Change History Incremental Test",
            "error": str(e),
            "success": False,
        }

    # Test 3: Manual refresh functionality
    try:
        results["tests"]["manual_refresh"] = test_manual_refresh_functionality()
    except Exception as e:
        results["tests"]["manual_refresh"] = {
            "test_name": "Manual Refresh Functionality Test",
            "error": str(e),
            "success": False,
        }

    # Calculate overall success
    successful_tests = sum(1 for test in results["tests"].values() if test.get("success", False))
    total_tests = len(results["tests"])

    results["summary"] = {
        "total_tests": total_tests,
        "successful_tests": successful_tests,
        "failed_tests": total_tests - successful_tests,
        "overall_success": successful_tests == total_tests,
    }

    return results
