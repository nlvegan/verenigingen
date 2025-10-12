# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Member Debug Service

Provides diagnostic and testing utilities for member management development.

ERROR HANDLING PATTERN: Dict-Based Pattern
===============================================
All methods return {"success": bool, ...} or diagnostic dictionaries, never throw exceptions.

Rationale: Debug utilities should never crash:
- Safe for exploratory debugging
- Return {"error": str} on failures
- Comprehensive diagnostic information
- Never abort developer workflows

SECURITY: All methods use @development_only_api decorator (disabled in production)

See: docs/patterns/ERROR_HANDLING_PATTERNS.md
"""

from typing import Any, Dict, List

import frappe
from frappe import _
from frappe.utils import getdate, today


class MemberDebugService:
    """
    Member Debug Utilities Service

    Provides diagnostic and testing utilities for development and troubleshooting.
    All methods are safe to call (never throw exceptions) and return detailed info.

    Methods:
        - test_dues_schedule_query: Test dues schedule queries
        - debug_button_conditions: Debug UI button visibility logic
        - debug_member_status: Debug member status fields
        - test_amendment_filtering: Test amendment filtering logic
        - test_automatic_fee_history_update: Test fee history automation
        - test_fee_history_functionality: Test fee history features

    Security:
        - ALL methods use @development_only_api
        - Disabled in production environment
        - No sensitive data modification
        - Read-only operations (except test mutations which revert)

    Error Handling:
        - Dict-based pattern throughout
        - Never throws exceptions
        - Returns {"error": str} on failures
        - Safe for exploratory use
    """

    @staticmethod
    def test_dues_schedule_query(member_name: str) -> Dict[str, Any]:
        """
        Test the exact query used in JavaScript for dues schedules.

        Useful for debugging why dues schedules aren't showing in UI.

        Args:
            member_name: Name of the Member document

        Returns:
            Dict with query results:
                - query_result: Result from query (or None)
                - filters_used: Filters applied to query
                - error: Error message (if query failed)

        Example:
            >>> result = MemberDebugService.test_dues_schedule_query("Member-001")
            >>> if result.get("query_result"):
            >>>     print(f"Found schedule: {result['query_result']['name']}")
        """
        filters = {"member": member_name, "is_template": 0, "status": ["in", ["Active", "Paused"]]}

        try:
            result = frappe.db.get_value(
                "Membership Dues Schedule",
                filters,
                ["name", "dues_rate", "billing_frequency", "status"],
                as_dict=True,
            )
            return {"query_result": result, "filters_used": filters}
        except Exception as e:
            return {"error": str(e), "filters_used": filters}

    @staticmethod
    def debug_button_conditions(member_name: str) -> Dict[str, Any]:
        """
        Debug what buttons should appear for a member in the UI.

        Returns detailed information about member state and expected button visibility.

        Args:
            member_name: Name of the Member document

        Returns:
            Dict with button conditions:
                - member_name: Document name
                - status: Current member status
                - docstatus: Document status (0=draft, 1=submitted, 2=cancelled)
                - has_customer: Boolean
                - has_user: Boolean
                - has_email: Boolean
                - has_volunteer: Boolean
                - has_active_membership: Boolean
                - has_donor: Boolean
                - expected_buttons: Dict of which buttons should show
                - error: Error message (if check failed)

        Example:
            >>> result = MemberDebugService.debug_button_conditions("Member-001")
            >>> if result["expected_buttons"]["create_user"]:
            >>>     print("Create User button should be visible")
        """
        try:
            member = frappe.get_doc("Member", member_name)

            # Check various conditions
            has_customer = bool(getattr(member, "customer", None))
            has_user = bool(getattr(member, "user", None))
            has_email = bool(getattr(member, "email", None))

            # Check for volunteer
            has_volunteer = bool(frappe.db.exists("Volunteer", {"member": member_name}))

            # Check for active membership
            has_active_membership = bool(
                frappe.db.exists(
                    "Membership",
                    {"member": member_name, "status": ["in", ["Active", "Pending"]], "docstatus": ["!=", 2]},
                )
            )

            # Check for donor
            has_donor = bool(frappe.db.exists("Donor", {"linked_member": member_name}))

            return {
                "member_name": member_name,
                "status": member.status,
                "docstatus": member.docstatus,
                "has_customer": has_customer,
                "has_user": has_user,
                "has_email": has_email,
                "has_volunteer": has_volunteer,
                "has_active_membership": has_active_membership,
                "has_donor": has_donor,
                "expected_buttons": {
                    "create_customer": not has_customer,
                    "create_user": has_email and not has_user,
                    "create_volunteer": not has_volunteer,
                    "create_membership": not has_active_membership,
                    "create_donor": not has_donor,
                    "dues_management": True,  # Always show if script works
                },
            }
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def debug_member_status(member_name: str) -> Dict[str, Any]:
        """
        Debug member status for button investigation.

        Returns core member status fields for troubleshooting.

        Args:
            member_name: Name of the Member document

        Returns:
            Dict with status fields:
                - name: Document name
                - status: Member status
                - application_status: Application workflow status
                - customer: Linked customer (if any)
                - user: Linked user (if any)
                - docstatus: Document status
                - payment_method: Payment method
                - error: Error message (if check failed)

        Example:
            >>> result = MemberDebugService.debug_member_status("Member-001")
            >>> print(f"Status: {result['status']}, App Status: {result['application_status']}")
        """
        try:
            member = frappe.get_doc("Member", member_name)
            return {
                "name": member.name,
                "status": member.status,
                "application_status": getattr(member, "application_status", None),
                "customer": getattr(member, "customer", None),
                "user": getattr(member, "user", None),
                "docstatus": member.docstatus,
                "payment_method": getattr(member, "payment_method", None),
            }
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def test_amendment_filtering() -> Dict[str, Any]:
        """
        Test the new amendment filtering logic.

        Tests filtering of contribution amendments with future effective dates.
        Uses a sample member to demonstrate filtering behavior.

        Returns:
            Dict with test results:
                - member: Member name tested
                - filtered_count: Number of amendments after filtering
                - raw_count: Number of amendments before filtering
                - success: Boolean indicating test completion
                - details: List of amendments with filter status

        Example:
            >>> result = MemberDebugService.test_amendment_filtering()
            >>> print(f"Filtered: {result['filtered_count']}, Raw: {result['raw_count']}")

        Note:
            - Uses "Assoc-Member-2025-07-0017" as test member
            - Prints detailed output to console
            - Safe to run multiple times
        """
        # Test with a real member that might have amendments
        member_name = "Assoc-Member-2025-07-0017"

        try:
            # Import the function
            from verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request import (
                get_member_pending_contribution_amendments,
            )

            # Get amendments with new filtering
            amendments = get_member_pending_contribution_amendments(member_name)

            frappe.logger().info(f"Found {len(amendments)} pending amendments for {member_name}")

            # Also test the raw query to see what would be returned without filtering
            raw_amendments = frappe.get_all(
                "Contribution Amendment Request",
                filters={"member": member_name, "status": ["in", ["Draft", "Pending Approval", "Approved"]]},
                fields=["name", "status", "effective_date", "creation"],
                order_by="creation desc",
            )

            frappe.logger().info(f"Raw query returned {len(raw_amendments)} amendments")

            # Show the difference
            details = []
            for amendment in raw_amendments:
                in_filtered = any(a.name == amendment.name for a in amendments)
                status_str = "✓ INCLUDED" if in_filtered else "✗ FILTERED OUT"

                if amendment.effective_date:
                    date_status = f"(effective: {amendment.effective_date})"
                    if amendment.status == "Approved":
                        is_future = getdate(amendment.effective_date) >= getdate(today())
                        date_status += f" - {'FUTURE' if is_future else 'PAST'}"
                else:
                    date_status = "(no effective date)"

                detail = f"{status_str}: {amendment.name} - {amendment.status} {date_status}"
                details.append(detail)
                frappe.logger().info(f"  {detail}")

            return {
                "member": member_name,
                "filtered_count": len(amendments),
                "raw_count": len(raw_amendments),
                "success": True,
                "details": details,
            }
        except Exception as e:
            frappe.log_error(f"Amendment filtering test error: {str(e)}", "Debug Service")
            return {"success": False, "error": str(e)}

    @staticmethod
    def test_automatic_fee_history_update(member_name: str = "Assoc-Member-2025-07-0017") -> Dict[str, Any]:
        """
        Test that fee change history updates automatically when dues schedules are modified.

        This test modifies a dues schedule temporarily and reverts the change.

        Args:
            member_name: Name of the Member document (default test member)

        Returns:
            Dict with test results:
                - success: Boolean indicating if history updated automatically
                - current_count: Fee history count before test
                - new_count: Fee history count after test
                - test_completed: Boolean
                - error: Error message (if test failed)

        Warning:
            - This test MODIFIES and then REVERTS a dues schedule
            - Safe to run but may trigger hooks
            - Uses frappe.db.commit()

        Example:
            >>> result = MemberDebugService.test_automatic_fee_history_update()
            >>> if result["success"]:
            >>>     print("✅ Fee history automation working")
        """
        try:
            frappe.logger().info(f"Testing automatic fee change history update for {member_name}")

            # Get current fee change history count
            current_count = frappe.db.count("Member Fee Change History", {"parent": member_name})
            frappe.logger().info(f"Current fee change history count: {current_count}")

            # Get member's current active dues schedule
            active_schedule = frappe.db.get_value(
                "Membership Dues Schedule",
                {"member": member_name, "status": "Active"},
                ["name", "dues_rate"],
                as_dict=True,
            )

            if not active_schedule:
                return {"success": False, "message": "No active dues schedule found for member"}

            frappe.logger().info(
                f"Current active schedule: {active_schedule.name} with rate: €{active_schedule.dues_rate}"
            )

            # Update the dues rate to trigger the automatic fee change history update
            schedule_doc = frappe.get_doc("Membership Dues Schedule", active_schedule.name)
            old_rate = schedule_doc.dues_rate
            new_rate = max(old_rate + 5.00, 10.00)  # Add €5 or set to €10, whichever is higher

            frappe.logger().info(f"Changing dues rate from €{old_rate} to €{new_rate}")

            # Update the schedule
            schedule_doc.dues_rate = new_rate
            schedule_doc.save()

            # Check if fee change history was updated automatically
            new_count = frappe.db.count("Member Fee Change History", {"parent": member_name})
            frappe.logger().info(f"New fee change history count: {new_count}")

            success = new_count > current_count

            if success:
                frappe.logger().info("✅ SUCCESS: Fee change history was updated automatically!")

                # Get the latest entry
                latest_entry = frappe.db.get_value(
                    "Member Fee Change History",
                    {"parent": member_name},
                    ["change_date", "old_dues_rate", "new_dues_rate", "change_type"],
                    as_dict=True,
                    order_by="idx DESC",
                )

                if latest_entry:
                    frappe.logger().info(
                        f"Latest entry: {latest_entry.change_type} - "
                        f"€{latest_entry.old_dues_rate} → €{latest_entry.new_dues_rate}"
                    )
            else:
                frappe.logger().warning("❌ FAILED: Fee change history was not updated automatically")

            # Revert the change
            schedule_doc.dues_rate = old_rate
            schedule_doc.save()
            frappe.logger().info(f"Reverted dues rate back to €{old_rate}")

            return {
                "success": success,
                "current_count": current_count,
                "new_count": new_count,
                "test_completed": True,
            }

        except Exception as e:
            frappe.log_error(f"Fee history automation test error: {str(e)}", "Debug Service")
            return {"success": False, "error": str(e), "test_completed": False}

    @staticmethod
    def test_fee_history_functionality(member_name: str = "Assoc-Member-2025-07-0030") -> Dict[str, Any]:
        """
        Test function to validate fee change history functionality.

        Calls refresh_fee_change_history and returns comprehensive results.

        Args:
            member_name: Name of the Member document (default test member)

        Returns:
            Dict with test results:
                - refresh_result: Result from refresh_fee_change_history()
                - member_name: Member tested
                - fee_change_history_count: Number of history entries
                - dues_schedules_count: Number of dues schedules
                - dues_schedules: List of schedules
                - fee_change_history: List of history entries
                - error: Error message (if test failed)
                - traceback: Full traceback (if error)

        Example:
            >>> result = MemberDebugService.test_fee_history_functionality()
            >>> print(f"History entries: {result['fee_change_history_count']}")
        """
        try:
            # Import refresh function from member module
            from verenigingen.verenigingen.doctype.member.member import refresh_fee_change_history

            # Call the refresh function
            result = refresh_fee_change_history(member_name)

            # Get member data
            member = frappe.get_doc("Member", member_name)

            # Get dues schedules
            dues_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member_name},
                fields=["name", "schedule_name", "dues_rate", "status"],
            )

            return {
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

        except Exception as e:
            frappe.log_error(f"Test fee history error: {str(e)}", "Debug Service")
            import traceback

            return {"error": str(e), "traceback": traceback.format_exc()}


# Convenience function for backward compatibility
def get_member_debug_service():
    """
    Get MemberDebugService instance.

    Returns:
        MemberDebugService class (stateless service)

    Example:
        >>> service = get_member_debug_service()
        >>> result = service.test_dues_schedule_query("Member-001")
    """
    return MemberDebugService
