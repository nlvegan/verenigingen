"""
Member Testing Utilities - Comprehensive test suites for Member functionality.

This module contains testing utilities extracted from member.py to maintain clean
separation between production code and testing/debugging tools.

ERROR HANDLING PATTERN: OperationResult Pattern
===============================================
All API methods return OperationResult[Dict] with type-safe error handling.
Never throws exceptions - all errors returned as OperationResult.fail().

Public API Methods:
- test_member_form_functionality: Returns OperationResult[Dict] (test execution results)
- test_automatic_fee_history_update: Returns OperationResult[Dict] (fee history test results)
- test_fee_history_functionality: Returns OperationResult[Dict] (fee history validation results)
- test_amendment_filtering: Returns OperationResult[Dict] (amendment filtering test results)
- test_dues_schedule_query: Returns OperationResult[Dict] (dues schedule query results)

Migration Status: ✅ COMPLETE (2025-11-25)
- All API methods migrated from dict-based to OperationResult pattern
- Consistent error handling with comprehensive metadata
- Type-safe error handling preserved across all test utilities

See: docs/patterns/OPERATION_RESULT_PATTERN.md

Functions:
    - test_member_form_functionality(): Test Member form loading and functionality
    - test_automatic_fee_history_update(): Test fee history business logic
    - test_fee_history_functionality(): Validate fee change history
    - test_amendment_filtering(): Test amendment filtering logic
    - test_dues_schedule_query(): Test query logic used in JavaScript
"""

from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from verenigingen.utils.operation_result import OperationResult


@frappe.whitelist()
def test_member_form_functionality(member_name) -> OperationResult[Dict[str, Any]]:
    """Test Member form loading and functionality.

    Extracted from member.py test method. Tests form loading, onload method,
    address optimization and field content validation.

    Args:
        member_name (str): Name of member to test

    Returns:
        OperationResult[Dict]: Test results with status, tests performed, and any errors
    """
    try:
        member = frappe.get_doc("Member", member_name)
        results = {"status": "success", "member_name": member.name, "tests": [], "errors": []}

        # Test 1: Onload method
        try:
            member.onload()
            results["tests"].append(
                {"test": "onload() method", "status": "passed", "message": "Executed without errors"}
            )
        except Exception as e:
            results["tests"].append(
                {"test": "onload() method", "status": "failed", "message": f"Error: {str(e)}"}
            )
            results["errors"].append(f"Onload error: {str(e)}")

        # Test 2: Address optimization functionality
        try:
            if hasattr(member, "get_other_members_at_address"):
                other_members = member.get_other_members_at_address()
                count = len(other_members) if other_members else 0
                results["tests"].append(
                    {
                        "test": "Address optimization",
                        "status": "passed",
                        "message": f"Found {count} other members",
                    }
                )
            else:
                results["tests"].append(
                    {"test": "Address optimization", "status": "failed", "message": "Method not found"}
                )
        except Exception as e:
            results["tests"].append(
                {"test": "Address optimization", "status": "failed", "message": f"Error: {str(e)}"}
            )
            results["errors"].append(f"Address optimization error: {str(e)}")

        # Test 3: HTML field updates
        try:
            if hasattr(member, "update_other_members_at_address_display"):
                member.update_other_members_at_address_display()
                results["tests"].append(
                    {
                        "test": "Address display update",
                        "status": "passed",
                        "message": "Completed successfully",
                    }
                )
            else:
                results["tests"].append(
                    {"test": "Address display update", "status": "failed", "message": "Method not found"}
                )
        except Exception as e:
            results["tests"].append(
                {"test": "Address display update", "status": "failed", "message": f"Error: {str(e)}"}
            )
            results["errors"].append(f"Display update error: {str(e)}")

        # Test 4: Check field content
        try:
            field_content = getattr(member, "other_members_at_address", None)
            if field_content:
                results["tests"].append(
                    {"test": "Address links display", "status": "passed", "message": "Field has content"}
                )
            else:
                results["tests"].append(
                    {"test": "Address links display", "status": "warning", "message": "Field is empty"}
                )
        except Exception as e:
            results["tests"].append(
                {"test": "Address links display", "status": "failed", "message": f"Error: {str(e)}"}
            )

        # Return success with all test results
        test_passed_count = len([t for t in results["tests"] if t["status"] == "passed"])
        total_tests = len(results["tests"])

        return OperationResult.ok(
            results, message=f"Member form test completed: {test_passed_count}/{total_tests} tests passed"
        )

    except frappe.DoesNotExistError:
        return OperationResult.fail(
            _("Member not found"),
            errors=[f"Member {member_name} does not exist"],
            status="error",
            member_name=member_name,
            tests=[],
            context={"operation": "member_form_test", "params": {"member_name": member_name}},
        )
    except frappe.PermissionError:
        return OperationResult.fail(
            _("Insufficient permissions to access member"),
            errors=["Permission denied"],
            status="error",
            member_name=member_name,
            tests=[],
            context={"operation": "member_form_test", "params": {"member_name": member_name}},
        )
    except Exception as e:
        frappe.log_error(f"Error in member form functionality test: {str(e)}", "Member Test Utilities Error")
        return OperationResult.fail(
            _("An error occurred while testing member form functionality. Please contact support."),
            errors=[str(e)],
            status="error",
            member_name=member_name,
            tests=[],
            context={"operation": "member_form_test", "params": {"member_name": member_name}},
        )


@frappe.whitelist()
def test_automatic_fee_history_update(
    member_name="Assoc-Member-2025-07-0017",
) -> OperationResult[Dict[str, Any]]:
    """Test that fee change history updates automatically when dues schedules are modified.

    Extracted from member.py without modification. Tests the business logic
    that automatically creates fee change history entries when dues rates change.

    Args:
        member_name (str): Name of member to test

    Returns:
        OperationResult[Dict]: Test results with success status and counts
    """
    try:
        print(f"Testing automatic fee change history update for {member_name}")

        # Get current fee change history count
        current_count = frappe.db.count("Member Fee Change History", {"parent": member_name})
        print(f"Current fee change history count: {current_count}")

        # Get member's current active dues schedule
        active_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "status": "Active"},
            ["name", "dues_rate"],
            as_dict=True,
        )

        if not active_schedule:
            return OperationResult.fail(
                _("No active dues schedule found for member"),
                errors=["No active dues schedule"],
                success=False,
                message="No active dues schedule found",
                context={"operation": "fee_history_test", "params": {"member_name": member_name}},
            )

        print(f"Current active schedule: {active_schedule.name} with rate: €{active_schedule.dues_rate}")

        # Update the dues rate to trigger the automatic fee change history update
        schedule_doc = frappe.get_doc("Membership Dues Schedule", active_schedule.name)
        old_rate = schedule_doc.dues_rate
        new_rate = max(old_rate + 5.00, 10.00)  # Add €5 or set to €10, whichever is higher

        print(f"Changing dues rate from €{old_rate} to €{new_rate}")

        # Update the schedule
        schedule_doc.dues_rate = new_rate
        schedule_doc.save()

        # Check if fee change history was updated automatically
        new_count = frappe.db.count("Member Fee Change History", {"parent": member_name})
        print(f"New fee change history count: {new_count}")

        success = new_count > current_count

        if success:
            print("✅ SUCCESS: Fee change history was updated automatically!")

            # Get the latest entry
            latest_entry = frappe.db.get_value(
                "Member Fee Change History",
                {"parent": member_name},
                ["change_date", "old_dues_rate", "new_dues_rate", "change_type"],
                as_dict=True,
                order_by="idx DESC",
            )

            if latest_entry:
                print(
                    f"Latest entry: {latest_entry.change_type} - €{latest_entry.old_dues_rate} → €{latest_entry.new_dues_rate}"
                )
        else:
            print("❌ FAILED: Fee change history was not updated automatically")

        # Revert the change
        schedule_doc.dues_rate = old_rate
        schedule_doc.save()
        print(f"Reverted dues rate back to €{old_rate}")

        result_data = {
            "success": success,
            "current_count": current_count,
            "new_count": new_count,
            "test_completed": True,
        }

        if success:
            return OperationResult.ok(
                result_data, message="Fee change history test passed - automatic update working correctly"
            )
        else:
            return OperationResult.fail(
                _("Fee change history was not updated automatically"),
                errors=["Automatic fee history update did not occur"],
                **result_data,
                context={"operation": "fee_history_test", "params": {"member_name": member_name}},
            )

    except frappe.DoesNotExistError as e:
        return OperationResult.fail(
            _("Member or schedule not found"),
            errors=[str(e)],
            success=False,
            test_completed=False,
            context={"operation": "fee_history_test", "params": {"member_name": member_name}},
        )
    except Exception as e:
        frappe.log_error(f"Error in fee history update test: {str(e)}", "Member Test Utilities Error")
        return OperationResult.fail(
            _("An error occurred while testing fee history update. Please contact support."),
            errors=[str(e)],
            success=False,
            test_completed=False,
            context={"operation": "fee_history_test", "params": {"member_name": member_name}},
        )


@frappe.whitelist()
def test_fee_history_functionality(
    member_name="Assoc-Member-2025-07-0030",
) -> OperationResult[Dict[str, Any]]:
    """Test function to validate fee change history functionality.

    Extracted from member.py without modification. Tests the refresh_fee_change_history
    function and returns comprehensive fee history information.

    Args:
        member_name (str): Name of member to test

    Returns:
        OperationResult[Dict]: Comprehensive fee history test results
    """
    try:
        # Call the refresh function
        from verenigingen.verenigingen.doctype.member.member import refresh_fee_change_history

        result = refresh_fee_change_history(member_name)

        # Get member data
        member = frappe.get_doc("Member", member_name)

        # Get dues schedules
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name},
            fields=["name", "schedule_name", "dues_rate", "status"],
        )

        test_data = {
            "refresh_result": result,
            "member_name": member_name,
            "fee_change_history_count": len(member.fee_change_history or []),
            "dues_schedules_count": len(dues_schedules),
            "dues_schedules": dues_schedules,
            "fee_change_history": [
                {
                    "change_date": entry.change_date,
                    "change_type": entry.change_type,
                    "old_rate": entry.old_dues_rate,
                    "new_rate": entry.new_dues_rate,
                    "reason": entry.reason,
                    "dues_schedule": entry.dues_schedule,
                }
                for entry in (member.fee_change_history or [])
            ],
        }

        return OperationResult.ok(
            test_data,
            message=f"Fee history validation complete: {test_data['fee_change_history_count']} history entries found",
        )

    except ImportError as e:
        return OperationResult.fail(
            _("Unable to import refresh_fee_change_history function"),
            errors=[str(e)],
            error="Import error",
            context={"operation": "fee_history_validation", "params": {"member_name": member_name}},
        )
    except frappe.DoesNotExistError:
        return OperationResult.fail(
            _("Member not found"),
            errors=[f"Member {member_name} does not exist"],
            error="Member not found",
            context={"operation": "fee_history_validation", "params": {"member_name": member_name}},
        )
    except Exception as e:
        import traceback

        frappe.log_error(f"Test fee history error: {str(e)}\n{traceback.format_exc()}", "Test Fee History")
        return OperationResult.fail(
            _("An error occurred while testing fee history functionality. Please contact support."),
            errors=[str(e)],
            error=str(e),
            traceback=traceback.format_exc(),
            context={"operation": "fee_history_validation", "params": {"member_name": member_name}},
        )


@frappe.whitelist()
def test_amendment_filtering() -> OperationResult[Dict[str, Any]]:
    """Test the new amendment filtering logic.

    Extracted from member.py without modification. Tests amendment filtering
    to ensure proper display of pending contribution amendments.

    Returns:
        OperationResult[Dict]: Amendment filtering test results
    """
    try:
        # Test with a real member that might have amendments
        member_name = "Assoc-Member-2025-07-0017"

        # Import the function
        from verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request import (
            get_member_pending_contribution_amendments,
        )

        # Get amendments with new filtering
        amendments = get_member_pending_contribution_amendments(member_name)

        print(f"Found {len(amendments)} pending amendments for {member_name}")

        # Also test the raw query to see what would be returned without filtering
        raw_amendments = frappe.get_all(
            "Contribution Amendment Request",
            filters={"member": member_name, "status": ["in", ["Draft", "Pending Approval", "Approved"]]},
            fields=["name", "status", "effective_date", "creation"],
            order_by="creation desc",
        )

        print(f"Raw query returned {len(raw_amendments)} amendments")

        # Show the difference
        for amendment in raw_amendments:
            in_filtered = any(a.name == amendment.name for a in amendments)
            status_str = "✓ INCLUDED" if in_filtered else "✗ FILTERED OUT"

            if amendment.effective_date:
                date_status = f"(effective: {amendment.effective_date})"
                if amendment.status == "Approved":
                    # using getdate, today from top-level import
                    from frappe.utils import getdate, today

                    is_future = getdate(amendment.effective_date) >= getdate(today())
                    date_status += f" - {'FUTURE' if is_future else 'PAST'}"
            else:
                date_status = "(no effective date)"

            print(f"  {status_str}: {amendment.name} - {amendment.status} {date_status}")

        result_data = {
            "member": member_name,
            "filtered_count": len(amendments),
            "raw_count": len(raw_amendments),
            "success": True,
        }

        return OperationResult.ok(
            result_data,
            message=f"Amendment filtering test complete: {result_data['filtered_count']} amendments after filtering",
        )

    except ImportError as e:
        return OperationResult.fail(
            _("Unable to import amendment filtering function"),
            errors=[str(e)],
            success=False,
            error="Import error",
            context={"operation": "amendment_filtering_test"},
        )
    except Exception as e:
        frappe.log_error(f"Error in amendment filtering test: {str(e)}", "Member Test Utilities Error")
        return OperationResult.fail(
            _("An error occurred while testing amendment filtering. Please contact support."),
            errors=[str(e)],
            success=False,
            error=str(e),
            context={"operation": "amendment_filtering_test"},
        )


@frappe.whitelist()
def test_dues_schedule_query(member_name) -> OperationResult[Dict[str, Any]]:
    """Test the exact query used in JavaScript.

    Extracted from member.py without modification. Tests the dues schedule
    query logic that is used in the JavaScript controller.

    Args:
        member_name (str): Name of member to test query for

    Returns:
        OperationResult[Dict]: Query test results
    """
    try:
        filters = {"member": member_name, "is_template": 0, "status": ["in", ["Active", "Paused"]]}
        result = frappe.db.get_value(
            "Membership Dues Schedule",
            filters,
            ["name", "dues_rate", "billing_frequency", "status"],
            as_dict=True,
        )

        query_data = {"query_result": result, "filters_used": filters}

        if result:
            return OperationResult.ok(
                query_data, message=f"Dues schedule query successful: Found {result.get('name', 'schedule')}"
            )
        else:
            return OperationResult.ok(
                query_data, message="Dues schedule query completed: No matching schedule found"
            )

    except Exception as e:
        frappe.log_error(f"Error in dues schedule query test: {str(e)}", "Member Test Utilities Error")
        filters = {"member": member_name, "is_template": 0, "status": ["in", ["Active", "Paused"]]}
        return OperationResult.fail(
            _("An error occurred while querying dues schedule. Please contact support."),
            errors=[str(e)],
            error=str(e),
            filters_used=filters,
            context={"operation": "dues_schedule_query_test", "params": {"member_name": member_name}},
        )
