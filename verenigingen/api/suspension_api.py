# ===== File: verenigingen/api/suspension_api.py =====
import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.utils.error_handling import handle_api_error, validate_required_fields
from verenigingen.utils.migration.migration_performance import BatchProcessor
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.performance_utils import performance_monitor

# Import security framework
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
    utility_api,
)
from verenigingen.utils.validation_utilities import DocumentExistenceValidator


@critical_api(operation_type=OperationType.WRITE)
@frappe.whitelist()
def suspend_member(
    member_name, suspension_reason, suspend_user=True, suspend_teams=True
) -> OperationResult[Dict[str, Any]]:
    """
    Suspend a member with specified options
    """
    try:
        # Validate mandatory fields - raise exceptions for proper error handling
        if not member_name or not member_name.strip():
            frappe.log_error(
                f"suspend_member called with empty member_name by {frappe.session.user}",
                "Suspension API Validation Error",
            )
            return OperationResult.fail(error=_("Member name is required"), error_code="INVALID_INPUT")

        if not suspension_reason or not suspension_reason.strip():
            frappe.log_error(
                f"suspend_member called with empty suspension_reason for {member_name} by {frappe.session.user}",
                "Suspension API Validation Error",
            )
            return OperationResult.fail(error=_("Suspension reason is required"), error_code="INVALID_INPUT")

        # Validate member exists
        if not DocumentExistenceValidator.check_document_exists("Member", member_name):
            frappe.log_error(
                f"suspend_member called with non-existent member {member_name} by {frappe.session.user}",
                "Suspension API Validation Error",
            )
            return OperationResult.fail(
                error=_("Member {0} does not exist").format(member_name), error_code="DOES_NOT_EXIST"
            )

        # Check permissions first
        from verenigingen.permissions import can_terminate_member

        if not can_terminate_member(member_name):
            frappe.log_error(
                f"Unauthorized suspension attempt on {member_name} by {frappe.session.user}",
                "Suspension API Permission Error",
            )
            return OperationResult.fail(
                error=_("You don't have permission to suspend this member"), error_code="PERMISSION_DENIED"
            )

        # Convert string booleans to actual booleans
        from verenigingen.utils.boolean_utils import cbool
        from verenigingen.utils.termination_integration import suspend_member_safe

        suspend_user = cbool(suspend_user)
        suspend_teams = cbool(suspend_teams)

        results = suspend_member_safe(
            member_name=member_name,
            suspension_reason=suspension_reason,
            suspension_date=today(),
            suspend_user=suspend_user,
            suspend_teams=suspend_teams,
        )

        if results.get("success"):
            data = {
                "actions_taken": results.get("actions_taken", []),
                "member_name": member_name,
            }
            actions_str = ", ".join(results.get("actions_taken", []))
            return OperationResult.ok(
                data, message=_("Member suspended successfully. Actions taken: {0}").format(actions_str)
            )
        else:
            error_msg = results.get("error", "Unknown error")
            frappe.log_error(
                f"Failed to suspend member {member_name}: {error_msg}\nFull result: {results}",
                "Suspension API Error",
            )
            return OperationResult.fail(
                error=_("Failed to suspend member: {0}").format(error_msg), error_code="SUSPENSION_FAILED"
            )
    except Exception as e:
        frappe.log_error(
            f"Exception in suspend_member for {member_name}: {str(e)}\n{traceback.format_exc()}",
            "Suspension API Exception",
        )
        return OperationResult.fail(
            error=_("An unexpected error occurred while suspending the member"), error_code="INTERNAL_ERROR"
        )


@critical_api(operation_type=OperationType.WRITE)
@frappe.whitelist()
def unsuspend_member(member_name, unsuspension_reason) -> OperationResult[Dict[str, Any]]:
    """
    Unsuspend a member
    """
    try:
        # Validate mandatory fields
        if not member_name or not member_name.strip():
            frappe.log_error(
                f"unsuspend_member called with empty member_name by {frappe.session.user}",
                "Suspension API Validation Error",
            )
            return OperationResult.fail(error=_("Member name is required"), error_code="INVALID_INPUT")

        if not unsuspension_reason or not unsuspension_reason.strip():
            frappe.log_error(
                f"unsuspend_member called with empty unsuspension_reason for {member_name} by {frappe.session.user}",
                "Suspension API Validation Error",
            )
            return OperationResult.fail(
                error=_("Unsuspension reason is required"), error_code="INVALID_INPUT"
            )

        # Validate member exists
        if not DocumentExistenceValidator.check_document_exists("Member", member_name):
            frappe.log_error(
                f"unsuspend_member called with non-existent member {member_name} by {frappe.session.user}",
                "Suspension API Validation Error",
            )
            return OperationResult.fail(
                error=_("Member {0} does not exist").format(member_name), error_code="DOES_NOT_EXIST"
            )

        # Check permissions first
        from verenigingen.permissions import can_terminate_member

        if not can_terminate_member(member_name):
            frappe.log_error(
                f"Unauthorized unsuspension attempt on {member_name} by {frappe.session.user}",
                "Suspension API Permission Error",
            )
            return OperationResult.fail(
                error=_("You don't have permission to unsuspend this member"), error_code="PERMISSION_DENIED"
            )

        from verenigingen.utils.termination_integration import unsuspend_member_safe

        results = unsuspend_member_safe(member_name=member_name, unsuspension_reason=unsuspension_reason)

        if results.get("success"):
            data = {
                "actions_taken": results.get("actions_taken", []),
                "member_name": member_name,
            }
            actions_str = ", ".join(results.get("actions_taken", []))
            return OperationResult.ok(
                data, message=_("Member unsuspended successfully. Actions taken: {0}").format(actions_str)
            )
        else:
            # Handle "already active" as success case, not error
            error_msg = str(results.get("error", ""))
            if "is not suspended" in error_msg.lower() or "current status" in error_msg.lower():
                data = {
                    "actions_taken": [],
                    "member_name": member_name,
                }
                return OperationResult.ok(data, message=_("Member is already active"))
            else:
                frappe.log_error(
                    f"Failed to unsuspend member {member_name}: {error_msg}\nFull result: {results}",
                    "Suspension API Error",
                )
                return OperationResult.fail(
                    error=_("Failed to unsuspend member: {0}").format(error_msg),
                    error_code="UNSUSPENSION_FAILED",
                )
    except Exception as e:
        frappe.log_error(
            f"Exception in unsuspend_member for {member_name}: {str(e)}\n{traceback.format_exc()}",
            "Suspension API Exception",
        )
        return OperationResult.fail(
            error=_("An unexpected error occurred while unsuspending the member"), error_code="INTERNAL_ERROR"
        )


@standard_api(operation_type=OperationType.READ)
@frappe.whitelist()
def get_my_suspension_status() -> OperationResult[Dict[str, Any]]:
    """
    Get suspension status for the current logged-in member
    Members can only access their own suspension status
    """
    try:
        # Get current user
        user_email = frappe.session.user
        if user_email == "Guest":
            return OperationResult.fail(
                error=_("Authentication required"),
                error_code="NOT_AUTHENTICATED",
                data={"authenticated": False},
            )

        # Find member record for current user
        member_name = frappe.db.get_value("Member", {"user": user_email}, "name")
        if not member_name:
            return OperationResult.fail(
                error=_("No member record found for current user"),
                error_code="NO_MEMBER_RECORD",
                data={"has_member_record": False},
            )

        # Get suspension status
        from verenigingen.utils.termination_integration import get_member_suspension_status

        status_data = get_member_suspension_status(member_name)
        return OperationResult.ok(status_data, message=_("Suspension status retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            f"Error getting suspension status for user {frappe.session.user}: {str(e)}\n{traceback.format_exc()}",
            "Member Suspension Status Error",
        )
        return OperationResult.fail(
            error=_("Unable to retrieve suspension status"), error_code="INTERNAL_ERROR"
        )


@standard_api(operation_type=OperationType.READ)
@frappe.whitelist()
def get_suspension_status(member_name) -> OperationResult[Dict[str, Any]]:
    """
    Get suspension status for a member (admin/staff use only)
    """
    try:
        from verenigingen.utils.termination_integration import get_member_suspension_status

        status_data = get_member_suspension_status(member_name)
        return OperationResult.ok(status_data, message=_("Suspension status retrieved successfully"))
    except frappe.PermissionError as e:
        # Return graceful error instead of throwing exception
        frappe.log_error(
            f"Permission denied for {frappe.session.user} to get suspension status of {member_name}: {str(e)}",
            "Suspension API Permission Error",
        )
        return OperationResult.fail(
            error=_("Access denied. This function requires administrative privileges."),
            error_code="PERMISSION_DENIED",
            data={
                "required_action": _(
                    "Please contact an administrator if you need to check suspension status."
                )
            },
        )
    except Exception as e:
        frappe.log_error(
            f"Error getting suspension status for member {member_name}: {str(e)}\n{traceback.format_exc()}",
            "Admin Suspension Status Error",
        )
        return OperationResult.fail(
            error=_("Unable to retrieve suspension status"), error_code="INTERNAL_ERROR"
        )


@utility_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def can_suspend_member(member_name=None) -> OperationResult[Dict[str, Any]]:
    """
    Check if current user can suspend/unsuspend a member
    If no member_name provided, checks general suspension permissions
    """
    try:
        # If no member specified, just check if user has any suspension permissions
        if not member_name:
            user_roles = frappe.get_roles(frappe.session.user)
            admin_roles = [
                "System Manager",
                "Verenigingen Administrator",
                "Verenigingen Staff",
            ]
            has_permission = any(role in user_roles for role in admin_roles)
            return OperationResult.ok(
                {"can_suspend": has_permission}, message=_("Permission check completed")
            )

        # Import the function using frappe's import system to handle any import issues
        try:
            # Use frappe.get_attr to import the function
            can_terminate_member = frappe.get_attr("verenigingen.permissions.can_terminate_member")
            # For suspension, we use the same permission logic as termination
            # since suspension is essentially a temporary termination
            has_permission = can_terminate_member(member_name)
            return OperationResult.ok(
                {"can_suspend": has_permission, "member_name": member_name},
                message=_("Permission check completed"),
            )
        except Exception as e:
            frappe.log_error(
                f"Import error in can_suspend_member: {str(e)}\n{traceback.format_exc()}",
                "Suspension API Import Error",
            )
            # Fallback to basic permission check
            has_permission = _can_suspend_member_fallback(member_name)
            return OperationResult.ok(
                {"can_suspend": has_permission, "member_name": member_name, "fallback_used": True},
                message=_("Permission check completed using fallback"),
            )

    except Exception as e:
        frappe.log_error(
            f"Error checking suspension permissions: {str(e)}\n{traceback.format_exc()}",
            "Suspension Permission Error",
        )
        return OperationResult.fail(
            error=_("Unable to check suspension permissions"),
            error_code="INTERNAL_ERROR",
            data={"can_suspend": False},
        )


def _can_suspend_member_fallback(member_name):
    """
    Fallback permission check for suspension if import fails
    """
    user = frappe.session.user

    # System managers and Association managers always can
    admin_roles = ["System Manager", "Verenigingen Administrator"]
    user_roles = frappe.get_roles(user)
    if any(role in user_roles for role in admin_roles):
        return True

    # Get the member being suspended
    try:
        member_doc = frappe.get_doc("Member", member_name)
    except Exception:
        return False

    # Get the user making the request as a member
    requesting_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not requesting_member:
        return False

    # Check if user is a board member of the member's chapter
    if member_doc.current_chapter_display:
        try:
            chapter_doc = frappe.get_doc("Chapter", member_doc.current_chapter_display)
            # Simple check - if the function exists on the chapter
            if hasattr(chapter_doc, "user_has_board_access"):
                return chapter_doc.user_has_board_access(requesting_member)
        except Exception:
            pass

    return False


@high_security_api(operation_type=OperationType.READ)
@frappe.whitelist()
@handle_api_error
@performance_monitor()
def get_suspension_preview(member_name) -> OperationResult[Dict[str, Any]]:
    """
    Preview what would be affected by suspension with caching
    """
    try:
        if not member_name:
            return OperationResult.fail(error=_("member_name is required"), error_code="INVALID_INPUT")

        member = frappe.get_doc("Member", member_name)

        # Get user account info - check both linked user field and email match
        user_from_link = frappe.db.get_value("Member", member_name, "user")
        member_email = frappe.db.get_value("Member", member_name, "email")

        user_email = None
        user_found_via = None
        if user_from_link and frappe.db.exists("User", user_from_link):
            user_email = user_from_link
            user_found_via = "linked_user_field"
        elif member_email and frappe.db.exists("User", member_email):
            user_email = member_email
            user_found_via = "email_match"

        has_user_account = bool(user_email)

        # Get team memberships through volunteer
        active_teams = 0
        team_details = []
        if user_email:
            # First get volunteer record for this user
            volunteer = frappe.db.get_value("Volunteer", {"email": user_email}, "name")
            if volunteer:
                teams = frappe.get_all(
                    "Team Member", filters={"volunteer": volunteer, "is_active": 1}, fields=["parent", "role"]
                )
                active_teams = len(teams)
                team_details = [{"team": t.parent, "role": t.role} for t in teams]

        # Get active memberships
        active_memberships = frappe.get_all(
            "Membership",
            filters={"member": member_name, "status": "Active", "docstatus": 1},
            fields=["name", "membership_type"],
        )

        data = {
            "member_status": member.status,
            "has_user_account": has_user_account,
            "user_email": user_email,
            "user_found_via": user_found_via,
            "active_teams": active_teams,
            "team_details": team_details,
            "active_memberships": len(active_memberships),
            "membership_details": active_memberships,
            "can_suspend": member.status != "Suspended",
            "is_currently_suspended": member.status == "Suspended",
        }

        return OperationResult.ok(data, message=_("Suspension preview retrieved successfully"))
    except frappe.DoesNotExistError:
        frappe.log_error(
            f"Member {member_name} not found for suspension preview by {frappe.session.user}",
            "Suspension API Error",
        )
        return OperationResult.fail(
            error=_("Member {0} does not exist").format(member_name), error_code="DOES_NOT_EXIST"
        )
    except Exception as e:
        frappe.log_error(
            f"Error getting suspension preview for {member_name}: {str(e)}\n{traceback.format_exc()}",
            "Suspension API Exception",
        )
        return OperationResult.fail(
            error=_("Unable to retrieve suspension preview"), error_code="INTERNAL_ERROR"
        )


@critical_api(operation_type=OperationType.WRITE)
@frappe.whitelist()
@handle_api_error
@performance_monitor()
def bulk_suspend_members(
    member_list, suspension_reason, suspend_user=True, suspend_teams=True
) -> OperationResult[Dict[str, Any]]:
    """
    Suspend multiple members at once using optimized batch processing
    """
    try:
        if isinstance(member_list, str):
            import json

            member_list = json.loads(member_list)

        # Validate inputs
        if not member_list:
            data = {
                "processed": 0,
                "total": 0,
                "successful": 0,
                "failed": 0,
            }
            return OperationResult.ok(data, message=_("No members to process"))

        if not suspension_reason:
            return OperationResult.fail(error=_("suspension_reason is required"), error_code="INVALID_INPUT")

        # Use BatchProcessor for optimized processing
        batch_processor = BatchProcessor(batch_size=50, parallel_workers=2)

        def process_member_suspension(member_name):
            """Process single member suspension with error handling"""
            try:
                # Check permissions for each member
                from verenigingen.permissions import can_terminate_member

                if not can_terminate_member(member_name):
                    return {
                        "member": member_name,
                        "status": "failed",
                        "error": "No permission to suspend this member",
                    }

                # Suspend the member
                from verenigingen.utils.boolean_utils import cbool
                from verenigingen.utils.termination_integration import suspend_member_safe

                suspend_result = suspend_member_safe(
                    member_name=member_name,
                    suspension_reason=suspension_reason,
                    suspend_user=cbool(suspend_user),
                    suspend_teams=cbool(suspend_teams),
                )

                if suspend_result.get("success"):
                    return {
                        "member": member_name,
                        "status": "success",
                        "actions": suspend_result.get("actions_taken", []),
                    }
                else:
                    return {
                        "member": member_name,
                        "status": "failed",
                        "error": suspend_result.get("error", "Unknown error"),
                    }

            except Exception as e:
                return {"member": member_name, "status": "failed", "error": str(e)}

        # Process in batches
        batch_results = batch_processor.process_in_batches(
            member_list, process_member_suspension, context={"suspension_reason": suspension_reason}
        )

        # Aggregate results
        results = {
            "successful": batch_results["successful"],
            "failed": batch_results["failed"],
            "details": [],
            "batch_stats": batch_results["batch_stats"],
        }

        # Extract details from batch results
        for batch_stat in batch_results["batch_stats"]:
            if "results" in batch_stat:
                results["details"].extend(batch_stat["results"])

        # Show summary message
        if results["successful"] > 0:
            frappe.msgprint(
                _("Bulk suspension completed: {0} successful, {1} failed").format(
                    results["successful"], results["failed"]
                ),
                indicator="blue",
            )
            return OperationResult.ok(
                results,
                message=_("Bulk suspension completed: {0} successful, {1} failed").format(
                    results["successful"], results["failed"]
                ),
            )
        else:
            frappe.msgprint(_("Bulk suspension failed: No members were suspended"), indicator="red")
            return OperationResult.fail(
                error=_("Bulk suspension failed: No members were suspended"),
                error_code="BULK_SUSPENSION_FAILED",
                data=results,
            )
    except Exception as e:
        frappe.log_error(
            f"Exception in bulk_suspend_members: {str(e)}\n{traceback.format_exc()}",
            "Suspension API Exception",
        )
        return OperationResult.fail(
            error=_("An unexpected error occurred during bulk suspension"), error_code="INTERNAL_ERROR"
        )


@standard_api(operation_type=OperationType.READ)
@frappe.whitelist()
@handle_api_error
@performance_monitor()
def get_suspension_list(limit=100, offset=0, status=None, chapter=None) -> OperationResult[Dict[str, Any]]:
    """
    Get list of suspended members with pagination and filtering
    """
    try:
        # Validate and sanitize pagination parameters
        limit = frappe.utils.cint(limit) if limit else 100
        offset = frappe.utils.cint(offset) if offset else 0

        if limit > 1000:
            limit = 1000  # Max limit for performance
        if offset < 0:
            offset = 0

        # Build filters
        filters = {"status": "Suspended"}
        if chapter:
            filters["current_chapter_display"] = chapter

        # Get suspended members with optimized query
        fields = [
            "name",
            "full_name",
            "email",
            "status",
            "current_chapter_display",
            "suspension_date",
            "suspension_reason",
            "creation",
        ]

        members = frappe.get_all(
            "Member",
            filters=filters,
            fields=fields,
            limit=limit,
            start=offset,
            order_by="suspension_date desc, creation desc",
        )

        # Get total count for pagination
        total_count = frappe.db.count("Member", filters)

        # Enhance data with additional information
        for member in members:
            # Add team count
            if member.get("email"):
                user_exists = frappe.db.exists("User", member["email"])
                if user_exists:
                    # Get volunteer linked to this user/member
                    volunteer_name = frappe.db.get_value(
                        "Verenigingen Volunteer", {"user": member["email"]}, "name"
                    )
                    if volunteer_name:
                        team_count = frappe.db.count(
                            "Team Member", {"volunteer": volunteer_name, "docstatus": 1}
                        )
                        member["active_team_count"] = team_count
                    else:
                        member["active_team_count"] = 0
                else:
                    member["active_team_count"] = 0
            else:
                member["active_team_count"] = 0

        data = {
            "data": members,
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < total_count,
        }

        return OperationResult.ok(data, message=_("Suspension list retrieved successfully"))
    except Exception as e:
        frappe.log_error(
            f"Error getting suspension list: {str(e)}\n{traceback.format_exc()}", "Suspension API Exception"
        )
        return OperationResult.fail(
            error=_("Unable to retrieve suspension list"), error_code="INTERNAL_ERROR"
        )


@standard_api(operation_type=OperationType.READ)
@frappe.whitelist(allow_guest=True)
def get_suspension_status_safe(member_name=None) -> OperationResult[Dict[str, Any]]:
    """
    Safe wrapper for getting suspension status that handles permission errors gracefully
    If member_name is not provided, gets status for current user's member record
    """
    try:
        # If no member_name provided, try to get current user's member record
        if not member_name:
            user_email = frappe.session.user
            if user_email == "Guest":
                return OperationResult.fail(
                    error=_("Please log in to view suspension status"),
                    error_code="NOT_AUTHENTICATED",
                    data={"authenticated": False},
                )

            member_name = frappe.db.get_value("Member", {"user": user_email}, "name")
            if not member_name:
                return OperationResult.fail(
                    error=_("No member record found for your account"),
                    error_code="NO_MEMBER_RECORD",
                    data={"has_member_record": False},
                )

        # First check if the user has permission to access this member's data
        current_user = frappe.session.user

        # Allow users to access their own data
        member_user = frappe.db.get_value("Member", member_name, "user")
        if member_user == current_user:
            from verenigingen.utils.termination_integration import get_member_suspension_status

            result = get_member_suspension_status(member_name)
            result["access_type"] = "own_record"
            return OperationResult.ok(result, message=_("Suspension status retrieved successfully"))

        # For other members, check if user has admin permissions
        user_roles = frappe.get_roles(current_user)
        admin_roles = [
            "System Manager",
            "Verenigingen Administrator",
            "Verenigingen Staff",
        ]

        if any(role in user_roles for role in admin_roles):
            from verenigingen.utils.termination_integration import get_member_suspension_status

            result = get_member_suspension_status(member_name)
            result["access_type"] = "admin_access"
            return OperationResult.ok(result, message=_("Suspension status retrieved successfully"))
        else:
            return OperationResult.fail(
                error=_("You can only view your own suspension status"),
                error_code="PERMISSION_DENIED",
                data={
                    "access_denied": True,
                    "help": _("To view another member's status, you need administrative privileges"),
                },
            )

    except Exception as e:
        frappe.log_error(
            f"Error in safe suspension status check: {str(e)}\n{traceback.format_exc()}",
            "Safe Suspension Status Error",
        )
        return OperationResult.fail(
            error=_("Unable to retrieve suspension status at this time"),
            error_code="INTERNAL_ERROR",
            data={"help": _("Please try again later or contact support if the problem persists")},
        )


@utility_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def test_bank_details_debug() -> OperationResult[Dict[str, Any]]:
    """Test function to debug bank details issue"""
    try:
        data = {
            "status": "working_from_api_file",
            "user": frappe.session.user,
            "form_data": dict(frappe.local.form_dict) if hasattr(frappe.local, "form_dict") else {},
        }
        return OperationResult.ok(data, message=_("Debug information retrieved successfully"))
    except Exception as e:
        frappe.log_error(
            f"Error in test_bank_details_debug: {str(e)}\n{traceback.format_exc()}",
            "Suspension API Exception",
        )
        return OperationResult.fail(
            error=_("Unable to retrieve debug information"), error_code="INTERNAL_ERROR"
        )
