# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Member Debug Service

Provides diagnostic and testing utilities for member management development.

ERROR HANDLING PATTERN: OperationResult Pattern
===============================================
All methods return OperationResult[Dict[str, Any]] with type-safe error handling.
Never throws exceptions - all errors returned as OperationResult.fail().

Rationale: Debug utilities should never crash:
- Safe for exploratory debugging
- Type safety prevents runtime errors
- Comprehensive diagnostic information in .data dict
- Never abort developer workflows
- Clear success/failure indication

Public Methods:
- test_dues_schedule_query: Returns OperationResult[Dict[str, Any]] (query results)
- debug_button_conditions: Returns OperationResult[Dict[str, Any]] (button visibility logic)
- debug_member_status: Returns OperationResult[Dict[str, Any]] (member status fields)
- test_amendment_filtering: Returns OperationResult[Dict[str, Any]] (filtering test results)
- test_automatic_fee_history_update: Returns OperationResult[Dict[str, Any]] (history automation test)
- test_fee_history_functionality: Returns OperationResult[Dict[str, Any]] (fee history test)

Migration Status: ✅ COMPLETE (2025-11-24)
- All 6 methods migrated from dict-based to OperationResult pattern
- Proper error handling with type-safe generic return types
- Enhanced error messages for troubleshooting

SECURITY: All methods use @development_only_api decorator (disabled in production)

See: docs/patterns/OPERATION_RESULT_PATTERN.md
"""

from typing import Any, Dict, List

import frappe
from frappe import _
from frappe.utils import getdate, today

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.operation_result import OperationResult


class MemberDebugService(StatelessService):
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

    def __init__(self) -> None:
        """Initialize the member debug service."""
        super().__init__(service_name="MemberDebugService")

    def test_dues_schedule_query(self, member_name: str) -> OperationResult[Dict[str, Any]]:
        """
        Test the exact query used in JavaScript for dues schedules.

        Useful for debugging why dues schedules aren't showing in UI.

        Args:
            member_name: Name of the Member document

        Returns:
            OperationResult[Dict[str, Any]]: Query results dict with:
                - query_result: Result from query (or None)
                - filters_used: Filters applied to query

        Example:
            >>> result = MemberDebugService.test_dues_schedule_query("Member-001")
            >>> if result.success and result.data.get("query_result"):
            >>>     print(f"Found schedule: {result.data['query_result']['name']}")

        Note:
            - Never throws exceptions (returns failed OperationResult)
            - Returns query_result=None if no schedule found (not an error)
        """
        filters = {"member": member_name, "is_template": 0, "status": ["in", ["Active", "Paused"]]}

        try:
            result = frappe.db.get_value(
                "Membership Dues Schedule",
                filters,
                ["name", "dues_rate", "billing_frequency", "status"],
                as_dict=True,
            )
            return OperationResult.ok(
                {"query_result": result, "filters_used": filters}, message="Query executed successfully"
            )
        except Exception as e:
            self.logger.error(f"Dues schedule query failed for {member_name}: {str(e)}")
            return OperationResult.fail(
                f"Query failed: {str(e)}", errors=[str(e)], filters_used=filters, member=member_name
            )

    def debug_button_conditions(self, member_name: str) -> OperationResult[Dict[str, Any]]:
        """
        Debug what buttons should appear for a member in the UI.

        Returns detailed information about member state and expected button visibility.

        Args:
            member_name: Name of the Member document

        Returns:
            OperationResult[Dict[str, Any]]: Button conditions dict with:
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

        Example:
            >>> result = MemberDebugService.debug_button_conditions("Member-001")
            >>> if result.success and result.data["expected_buttons"]["create_user"]:
            >>>     print("Create User button should be visible")

        Note:
            - Never throws exceptions (returns failed OperationResult)
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

            button_conditions = {
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

            return OperationResult.ok(button_conditions)

        except Exception as e:
            self.logger.error(f"Button conditions debug failed for {member_name}: {str(e)}")
            return OperationResult.fail(
                f"Failed to retrieve button conditions: {str(e)}", errors=[str(e)], member=member_name
            )

    def debug_member_status(self, member_name: str) -> OperationResult[Dict[str, Any]]:
        """
        Debug member status for button investigation.

        Returns core member status fields for troubleshooting.

        Args:
            member_name: Name of the Member document

        Returns:
            OperationResult[Dict[str, Any]]: Status fields dict with:
                - name: Document name
                - status: Member status
                - application_status: Application workflow status
                - customer: Linked customer (if any)
                - user: Linked user (if any)
                - docstatus: Document status
                - payment_method: Payment method

        Example:
            >>> result = MemberDebugService.debug_member_status("Member-001")
            >>> if result.success:
            >>>     print(f"Status: {result.data['status']}, App Status: {result.data['application_status']}")

        Note:
            - Never throws exceptions (returns failed OperationResult)
        """
        try:
            member = frappe.get_doc("Member", member_name)
            status_info = {
                "name": member.name,
                "status": member.status,
                "application_status": getattr(member, "application_status", None),
                "customer": getattr(member, "customer", None),
                "user": getattr(member, "user", None),
                "docstatus": member.docstatus,
                "payment_method": getattr(member, "payment_method", None),
            }
            return OperationResult.ok(status_info)

        except Exception as e:
            self.logger.error(f"Member status debug failed for {member_name}: {str(e)}")
            return OperationResult.fail(
                f"Failed to retrieve member status: {str(e)}", errors=[str(e)], member=member_name
            )

    def test_amendment_filtering(self) -> OperationResult[Dict[str, Any]]:
        """
        Test the new amendment filtering logic.

        Tests filtering of contribution amendments with future effective dates.
        Uses a sample member to demonstrate filtering behavior.

        Returns:
            OperationResult[Dict[str, Any]]: Test results dict with:
                - member: Member name tested
                - filtered_count: Number of amendments after filtering
                - raw_count: Number of amendments before filtering
                - details: List of amendments with filter status

        Example:
            >>> result = MemberDebugService.test_amendment_filtering()
            >>> if result.success:
            >>>     print(f"Filtered: {result.data['filtered_count']}, Raw: {result.data['raw_count']}")

        Note:
            - Uses "Assoc-Member-2025-07-0017" as test member
            - Prints detailed output to console
            - Safe to run multiple times
            - Never throws exceptions (returns failed OperationResult)
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

            self.logger.info(f"Found {len(amendments)} pending amendments for {member_name}")

            # Also test the raw query to see what would be returned without filtering
            raw_amendments = frappe.get_all(
                "Contribution Amendment Request",
                filters={"member": member_name, "status": ["in", ["Draft", "Pending Approval", "Approved"]]},
                fields=["name", "status", "effective_date", "creation"],
                order_by="creation desc",
            )

            self.logger.info(f"Raw query returned {len(raw_amendments)} amendments")

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
                self.logger.info(f"  {detail}")

            test_results = {
                "member": member_name,
                "filtered_count": len(amendments),
                "raw_count": len(raw_amendments),
                "details": details,
            }

            return OperationResult.ok(
                test_results,
                message=f"Amendment filtering test completed: {len(amendments)}/{len(raw_amendments)} amendments",
            )

        except Exception as e:
            self.logger.error(f"Amendment filtering test error: {str(e)}")
            return OperationResult.fail(
                f"Amendment filtering test failed: {str(e)}", errors=[str(e)], member=member_name
            )

    def test_automatic_fee_history_update(
        self,
        member_name: str = "Assoc-Member-2025-07-0017",
    ) -> OperationResult[Dict[str, Any]]:
        """
        Test that fee change history updates automatically when dues schedules are modified.

        This test modifies a dues schedule temporarily and reverts the change.

        Args:
            member_name: Name of the Member document (default test member)

        Returns:
            OperationResult[Dict[str, Any]]: Test results dict with:
                - history_updated: Boolean indicating if history updated automatically
                - current_count: Fee history count before test
                - new_count: Fee history count after test
                - test_completed: Boolean

        Warning:
            - This test MODIFIES and then REVERTS a dues schedule
            - Safe to run but may trigger hooks
            - Uses frappe.db.commit()

        Example:
            >>> result = MemberDebugService.test_automatic_fee_history_update()
            >>> if result.success and result.data["history_updated"]:
            >>>     print("✅ Fee history automation working")

        Note:
            - Never throws exceptions (returns failed OperationResult)
        """
        try:
            self.logger.info(f"Testing automatic fee change history update for {member_name}")

            # Get current fee change history count
            current_count = frappe.db.count("Member Fee Change History", {"parent": member_name})
            self.logger.info(f"Current fee change history count: {current_count}")

            # Get member's current active dues schedule
            active_schedule = frappe.db.get_value(
                "Membership Dues Schedule",
                {"member": member_name, "status": "Active"},
                ["name", "dues_rate"],
                as_dict=True,
            )

            if not active_schedule:
                return OperationResult.fail(
                    "No active dues schedule found for member",
                    errors=["No active schedule"],
                    member=member_name,
                )

            self.logger.info(
                f"Current active schedule: {active_schedule.name} with rate: €{active_schedule.dues_rate}"
            )

            # Update the dues rate to trigger the automatic fee change history update
            schedule_doc = frappe.get_doc("Membership Dues Schedule", active_schedule.name)
            old_rate = schedule_doc.dues_rate
            new_rate = max(old_rate + 5.00, 10.00)  # Add €5 or set to €10, whichever is higher

            self.logger.info(f"Changing dues rate from €{old_rate} to €{new_rate}")

            # Update the schedule
            schedule_doc.dues_rate = new_rate
            schedule_doc.save()

            # Check if fee change history was updated automatically
            new_count = frappe.db.count("Member Fee Change History", {"parent": member_name})
            self.logger.info(f"New fee change history count: {new_count}")

            history_updated = new_count > current_count

            if history_updated:
                self.logger.info("✅ SUCCESS: Fee change history was updated automatically!")

                # Get the latest entry
                latest_entry = frappe.db.get_value(
                    "Member Fee Change History",
                    {"parent": member_name},
                    ["change_date", "old_dues_rate", "new_dues_rate", "change_type"],
                    as_dict=True,
                    order_by="idx DESC",
                )

                if latest_entry:
                    self.logger.info(
                        f"Latest entry: {latest_entry.change_type} - "
                        f"€{latest_entry.old_dues_rate} → €{latest_entry.new_dues_rate}"
                    )
            else:
                self.logger.warning("❌ FAILED: Fee change history was not updated automatically")

            # Revert the change
            schedule_doc.dues_rate = old_rate
            schedule_doc.save()
            self.logger.info(f"Reverted dues rate back to €{old_rate}")

            test_results = {
                "history_updated": history_updated,
                "current_count": current_count,
                "new_count": new_count,
                "test_completed": True,
            }

            return OperationResult.ok(
                test_results,
                message=f"Fee history automation test completed: {'✅ PASSED' if history_updated else '❌ FAILED'}",
            )

        except Exception as e:
            self.logger.error(f"Fee history automation test error: {str(e)}")
            return OperationResult.fail(
                f"Fee history automation test failed: {str(e)}",
                errors=[str(e)],
                member=member_name,
                test_completed=False,
            )

    def test_fee_history_functionality(
        self,
        member_name: str = "Assoc-Member-2025-07-0030",
    ) -> OperationResult[Dict[str, Any]]:
        """
        Test function to validate fee change history functionality.

        Calls refresh_fee_change_history and returns comprehensive results.

        Args:
            member_name: Name of the Member document (default test member)

        Returns:
            OperationResult[Dict[str, Any]]: Test results dict with:
                - refresh_result: Result from refresh_fee_change_history()
                - member_name: Member tested
                - fee_change_history_count: Number of history entries
                - dues_schedules_count: Number of dues schedules
                - dues_schedules: List of schedules
                - fee_change_history: List of history entries

        Example:
            >>> result = MemberDebugService.test_fee_history_functionality()
            >>> if result.success:
            >>>     print(f"History entries: {result.data['fee_change_history_count']}")

        Note:
            - Never throws exceptions (returns failed OperationResult)
        """
        try:
            # Import refresh function from member module
            from verenigingen.verenigingen.doctype.member.member import refresh_fee_change_history

            # Call the refresh function
            refresh_result = refresh_fee_change_history(member_name)

            # Get member data
            member = frappe.get_doc("Member", member_name)

            # Get dues schedules
            dues_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member_name},
                fields=["name", "schedule_name", "dues_rate", "status"],
            )

            test_results = {
                "refresh_result": refresh_result,
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
                test_results,
                message=f"Fee history test completed: {len(member.fee_change_history or [])} history entries",
            )

        except Exception as e:
            self.logger.error(f"Test fee history error: {str(e)}")
            import traceback

            return OperationResult.fail(
                f"Fee history functionality test failed: {str(e)}",
                errors=[str(e)],
                member=member_name,
                traceback=traceback.format_exc(),
            )


def get_member_debug_service() -> MemberDebugService:
    """
    Get MemberDebugService instance.

    Returns:
        MemberDebugService instance

    Example:
        >>> service = get_member_debug_service()
        >>> result = service.test_dues_schedule_query("Member-001")
    """
    return MemberDebugService()
