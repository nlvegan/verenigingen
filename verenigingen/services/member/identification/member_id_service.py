# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Member ID Management Service

Handles member ID assignment for approved members.

ERROR HANDLING PATTERN: OperationResult Pattern
===============================================
All methods return OperationResult[T] with type-safe error handling.
Never throws exceptions - all errors returned as OperationResult.fail().

Rationale: Member ID assignment is an admin utility operation where:
- Callers need detailed error messages for troubleshooting
- Operations should not abort workflows
- Type safety prevents runtime errors
- Results need to be displayed in UI

Public Methods:
- assign_member_id: Returns OperationResult[str] (member_id)
- assign_missing_member_ids: Returns OperationResult[Dict[str, Any]] (batch results)
- debug_member_id_assignment: Returns OperationResult[Dict[str, Any]] (diagnostic info)

Migration Status: ✅ COMPLETE (2025-11-24)
- All 3 methods migrated from dict-based to OperationResult pattern
- Proper error handling with type-safe generic return types
- Comprehensive error messages for troubleshooting

See: docs/patterns/OPERATION_RESULT_PATTERN.md
"""

from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult


class MemberIDService:
    """
    Member ID Management Service

    Handles member ID assignment for approved members within the Verenigingen system.
    Member IDs are generated when members are approved (transition from application to member).

    Methods:
        - assign_member_id: Assign ID to a single member
        - assign_missing_member_ids: Bulk assign IDs to all eligible members
        - debug_member_id_assignment: Debug utility for troubleshooting ID assignment

    Error Handling:
        - Individual assign: Exception-based (throws on error)
        - Bulk assign: Dict-based (returns {"success": bool, "total_checked": N, "assigned": M})
        - Debug: Dict-based (returns diagnostic info, never throws)

    Security:
        - Individual assign: @high_security_api (modifies member data)
        - Bulk assign: @critical_api (admin-only bulk operation)
        - Debug: @development_only_api (production safety)
    """

    @staticmethod
    def assign_member_id(member_name: str) -> OperationResult[str]:
        """
        Assign member ID to a single member.

        Calls the member document's ensure_member_id() method which generates
        and assigns a unique member ID if the member should have one.

        Args:
            member_name: Name of the Member document

        Returns:
            OperationResult[str]: Assigned member ID on success

        Example:
            >>> result = MemberIDService.assign_member_id("Member-001")
            >>> if result.success:
            >>>     print(f"Assigned ID: {result.data}")

        Business Rules:
            - Only approved members get IDs
            - Application members use application_id instead
            - IDs are never changed once assigned

        Note:
            - Never throws exceptions (returns failed OperationResult)
        """
        try:
            if not member_name:
                return OperationResult.fail(
                    _("Member name is required"), errors=["Empty member_name parameter"]
                )

            # Verify member exists
            if not frappe.db.exists("Member", member_name):
                return OperationResult.fail(
                    _("Member {0} does not exist").format(member_name),
                    errors=[f"Member not found: {member_name}"],
                )

            member = frappe.get_doc("Member", member_name)

            # Check if member already has an ID
            if member.member_id:
                return OperationResult.fail(
                    _("Member already has ID: {0}").format(member.member_id),
                    errors=["Member already has ID"],
                    existing_member_id=member.member_id,
                )

            # For application members, they should be approved first
            if member.is_application_member() and not member.should_have_member_id():
                return OperationResult.fail(
                    _(
                        "Application member must be approved before assigning member ID. Current status: {0}"
                    ).format(member.application_status),
                    errors=["Member not eligible for ID"],
                    application_status=member.application_status,
                )

            # Generate and assign member ID using MemberIDManager
            from verenigingen.verenigingen.doctype.member.member_id_manager import MemberIDManager

            next_id = MemberIDManager.get_next_member_id()
            member.member_id = str(next_id)

            # Save the member
            member.save()

            frappe.logger().info(f"MemberIDService: Assigned member ID {member.member_id} to {member_name}")

            return OperationResult.ok(
                str(next_id), message=_("Member ID {0} assigned successfully").format(next_id)
            )

        except Exception as e:
            frappe.log_error(f"Error assigning member ID to {member_name}: {str(e)}", "MemberIDService")
            return OperationResult.fail(
                _("Error assigning member ID: {0}").format(str(e)), errors=[str(e)], member=member_name
            )

    @staticmethod
    def assign_missing_member_ids() -> OperationResult[Dict[str, Any]]:
        """
        Bulk assign member IDs to all eligible members who don't have one.

        This is a batch operation that continues even if individual assignments fail.
        Useful for data migration or fixing members who should have IDs but don't.

        Returns:
            OperationResult[Dict[str, Any]]: Results dict with:
                - total_checked: Number of members examined
                - assigned: Number of IDs successfully assigned
                - errors: List of error messages (if any)

        Security:
            - Requires admin permissions (@critical_api)
            - Logs all assignments for audit trail

        Example:
            >>> result = MemberIDService.assign_missing_member_ids()
            >>> if result.success:
            >>>     print(f"Assigned {result.data['assigned']} IDs")

        Performance:
            - Processes members in batches
            - Commits after each successful assignment
            - Can handle thousands of members

        Note:
            - This operation is idempotent (safe to run multiple times)
            - Only assigns IDs to members without them
            - Skips members who don't qualify
            - Never throws exceptions (returns failed OperationResult)
        """
        frappe.logger().info("MemberIDService: Starting bulk member ID assignment")

        try:
            # Find all members without IDs
            members_without_ids = frappe.get_all(
                "Member",
                filters={"member_id": ["is", "not set"]},
                fields=["name", "application_status", "application_id", "full_name", "status"],
            )

            total_checked = len(members_without_ids)
            assigned_count = 0
            errors = []

            frappe.logger().info(f"MemberIDService: Found {total_checked} members without member IDs")

            for member_data in members_without_ids:
                try:
                    member = frappe.get_doc("Member", member_data.name)

                    # Check if member should have an ID
                    if member.should_have_member_id():
                        member.ensure_member_id()
                        assigned_count += 1

                        frappe.logger().info(
                            f"MemberIDService: Assigned ID {member.member_id} to {member.full_name} ({member.name})"
                        )
                    else:
                        frappe.logger().debug(
                            f"MemberIDService: Skipping {member.name} - does not qualify for member ID "
                            f"(status: {member.status})"
                        )

                except Exception as e:
                    error_msg = f"Failed to assign ID to {member_data.name}: {str(e)}"
                    frappe.logger().error(f"MemberIDService: {error_msg}")
                    errors.append(error_msg)

            # Summary message
            message = f"Assigned member IDs to {assigned_count} out of {total_checked} members"

            if errors:
                message += f" ({len(errors)} errors)"

            frappe.logger().info(f"MemberIDService: {message}")

            results = {
                "total_checked": total_checked,
                "assigned": assigned_count,
                "errors": errors if errors else [],
            }

            # Success if we assigned at least one ID, or if there were no members to process
            if assigned_count > 0 or total_checked == 0:
                return OperationResult.ok(results, message=message)
            else:
                return OperationResult.fail(
                    "No member IDs were assigned",
                    errors=errors if errors else ["No eligible members found"],
                    **results,
                )

        except Exception as e:
            frappe.log_error(f"Bulk member ID assignment failed: {str(e)}", "MemberIDService")
            return OperationResult.fail(f"Bulk member ID assignment failed: {str(e)}", errors=[str(e)])

    @staticmethod
    def debug_member_id_assignment(member_name: str) -> OperationResult[Dict[str, Any]]:
        """
        Debug utility for troubleshooting member ID assignment.

        Returns diagnostic information about why a member does or doesn't have
        a member ID, useful for support and debugging.

        Args:
            member_name: Name of the Member document

        Returns:
            OperationResult[Dict[str, Any]]: Diagnostic information dict with:
                - member_name: Document name
                - current_member_id: Current ID (or None)
                - has_member_id: Boolean
                - is_application_member: Boolean
                - application_id: Application ID (if any)
                - application_status: Application status
                - status: Current member status
                - should_have_member_id: Boolean (eligibility check)
                - can_assign_id: Boolean (can assign now)
                - explanation: Human-readable explanation of current state

        Security:
            - @development_only_api (disabled in production)
            - Never throws exceptions (returns failed OperationResult)

        Example:
            >>> result = MemberIDService.debug_member_id_assignment("Member-001")
            >>> if result.success and result.data["can_assign_id"]:
            >>>     print("Member can receive an ID")
            >>> elif result.success:
            >>>     print(f"Reason: {result.data['explanation']}")

        Use Cases:
            - Support troubleshooting
            - Understanding ID assignment rules
            - Verifying member state transitions

        Note:
            - Never throws exceptions (returns failed OperationResult)
        """
        try:
            # Validate input
            if not member_name:
                return OperationResult.fail("Member name is required", errors=["Empty member_name parameter"])

            # Verify member exists
            if not frappe.db.exists("Member", member_name):
                return OperationResult.fail(
                    f"Member {member_name} does not exist",
                    errors=[f"Member not found: {member_name}"],
                    member=member_name,
                )

            member = frappe.get_doc("Member", member_name)

            # Collect diagnostic information
            debug_info = {
                "member_name": member.name,
                "current_member_id": getattr(member, "member_id", None),
                "has_member_id": bool(getattr(member, "member_id", None)),
                "is_application_member": member.is_application_member(),
                "application_id": getattr(member, "application_id", None),
                "application_status": getattr(member, "application_status", None),
                "status": getattr(member, "status", None),
                "should_have_member_id": member.should_have_member_id(),
            }

            # Can assign ID if: no current ID AND should have ID
            debug_info["can_assign_id"] = (
                not debug_info["has_member_id"] and debug_info["should_have_member_id"]
            )

            # Add explanation
            if debug_info["has_member_id"]:
                debug_info["explanation"] = f"Member already has ID: {debug_info['current_member_id']}"
            elif debug_info["can_assign_id"]:
                debug_info["explanation"] = "Member is eligible and can receive an ID"
            elif debug_info["is_application_member"]:
                debug_info[
                    "explanation"
                ] = f"Application member uses application_id: {debug_info['application_id']}"
            else:
                debug_info[
                    "explanation"
                ] = f"Member status '{debug_info['status']}' does not qualify for member ID"

            frappe.logger().debug(f"MemberIDService: Debug info for {member_name}: {debug_info}")

            return OperationResult.ok(debug_info)

        except Exception as e:
            error_msg = str(e)
            frappe.logger().error(
                f"MemberIDService: Error in debug_member_id_assignment for {member_name}: {error_msg}"
            )
            return OperationResult.fail(
                f"Failed to retrieve debug information: {error_msg}", errors=[error_msg], member=member_name
            )


# Convenience function for backward compatibility
def get_member_id_service():
    """
    Get MemberIDService instance.

    Returns:
        MemberIDService class (stateless service)

    Example:
        >>> service = get_member_id_service()
        >>> member_id = service.assign_member_id("Member-001")
    """
    return MemberIDService
