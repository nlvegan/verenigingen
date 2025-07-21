# ===== File: verenigingen/api/suspension_api.py =====
import frappe
from frappe import _
from frappe.utils import today

from verenigingen.utils.error_handling import handle_api_error, validate_required_fields
from verenigingen.utils.migration.migration_performance import BatchProcessor
from verenigingen.utils.performance_utils import performance_monitor


@frappe.whitelist()
def suspend_member(member_name, suspension_reason, suspend_user=True, suspend_teams=True):
    """
    Suspend a member with specified options
    """
    try:
        # Validate mandatory fields
        if not member_name or not member_name.strip():
            return {"success": False, "error": "Member name is required"}

        if not suspension_reason or not suspension_reason.strip():
            return {"success": False, "error": "Suspension reason is required"}

        # Validate member exists
        if not frappe.db.exists("Member", member_name):
            return {"success": False, "error": f"Member {member_name} does not exist"}

        # Check permissions first
        from verenigingen.permissions import can_terminate_member

        if not can_terminate_member(member_name):
            return {"success": False, "error": "You don't have permission to suspend this member"}

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
            return {
                "success": True,
                "message": f"Member suspended successfully. Actions taken: {', '.join(results.get('actions_taken', []))}",
                "actions_taken": results.get("actions_taken", []),
                "member_name": member_name,
            }
        else:
            return {
                "success": False,
                "error": f"Failed to suspend member: {results.get('error', 'Unknown error')}",
            }

    except frappe.ValidationError as e:
        return {"success": False, "error": f"Validation error: {str(e)}"}

    except frappe.PermissionError as e:
        return {"success": False, "error": f"Permission denied: {str(e)}"}

    except Exception as e:
        # Log unexpected errors for debugging
        frappe.log_error(
            f"Unexpected error suspending member {member_name}: {str(e)}", "Member Suspension Error"
        )
        return {
            "success": False,
            "error": "An unexpected error occurred while suspending the member. Please try again or contact support.",
        }


@frappe.whitelist()
def unsuspend_member(member_name, unsuspension_reason):
    """
    Unsuspend a member
    """
    try:
        # Validate mandatory fields
        if not member_name or not member_name.strip():
            return {"success": False, "error": "Member name is required"}

        if not unsuspension_reason or not unsuspension_reason.strip():
            return {"success": False, "error": "Unsuspension reason is required"}

        # Validate member exists
        if not frappe.db.exists("Member", member_name):
            return {"success": False, "error": f"Member {member_name} does not exist"}

        # Check permissions first
        from verenigingen.permissions import can_terminate_member

        if not can_terminate_member(member_name):
            return {"success": False, "error": "You don't have permission to unsuspend this member"}

        from verenigingen.utils.termination_integration import unsuspend_member_safe

        results = unsuspend_member_safe(member_name=member_name, unsuspension_reason=unsuspension_reason)

        if results.get("success"):
            return {
                "success": True,
                "message": f"Member unsuspended successfully. Actions taken: {', '.join(results.get('actions_taken', []))}",
                "actions_taken": results.get("actions_taken", []),
                "member_name": member_name,
            }
        else:
            return {
                "success": False,
                "error": f"Failed to unsuspend member: {results.get('error', 'Unknown error')}",
            }

    except frappe.ValidationError as e:
        return {"success": False, "error": f"Validation error: {str(e)}"}

    except frappe.PermissionError as e:
        return {"success": False, "error": f"Permission denied: {str(e)}"}

    except Exception as e:
        # Log unexpected errors for debugging
        frappe.log_error(
            f"Unexpected error unsuspending member {member_name}: {str(e)}", "Member Unsuspension Error"
        )
        return {
            "success": False,
            "error": "An unexpected error occurred while unsuspending the member. Please try again or contact support.",
        }


@frappe.whitelist()
def get_suspension_status(member_name):
    """
    Get suspension status for a member
    """
    from verenigingen.utils.termination_integration import get_member_suspension_status

    return get_member_suspension_status(member_name)


@frappe.whitelist()
def can_suspend_member(member_name):
    """
    Check if current user can suspend/unsuspend a member
    """
    # Import the function using frappe's import system to handle any import issues
    try:
        # Use frappe.get_attr to import the function
        can_terminate_member = frappe.get_attr("verenigingen.permissions.can_terminate_member")
        # For suspension, we use the same permission logic as termination
        # since suspension is essentially a temporary termination
        return can_terminate_member(member_name)
    except Exception as e:
        frappe.log_error(f"Import error in can_suspend_member: {e}", "Suspension API Import Error")
        # Fallback to basic permission check
        return _can_suspend_member_fallback(member_name)


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


@handle_api_error
@performance_monitor()
@frappe.whitelist()
def get_suspension_preview(member_name):
    """
    Preview what would be affected by suspension with caching
    """
    if not member_name:
        raise ValueError("member_name is required")

    member = frappe.get_doc("Member", member_name)

    # Get user account info
    user_email = frappe.db.get_value("Member", member_name, "user")
    has_user_account = bool(user_email and frappe.db.exists("User", user_email))

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

    return {
        "member_status": member.status,
        "has_user_account": has_user_account,
        "active_teams": active_teams,
        "team_details": team_details,
        "active_memberships": len(active_memberships),
        "membership_details": active_memberships,
        "can_suspend": member.status != "Suspended",
        "is_currently_suspended": member.status == "Suspended",
    }


@handle_api_error
@performance_monitor()
@frappe.whitelist()
def bulk_suspend_members(member_list, suspension_reason, suspend_user=True, suspend_teams=True):
    """
    Suspend multiple members at once using optimized batch processing
    """
    if isinstance(member_list, str):
        import json

        member_list = json.loads(member_list)

    # Validate inputs
    if not member_list:
        raise ValueError("member_list cannot be empty")
    if not suspension_reason:
        raise ValueError("suspension_reason is required")

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
        "success": batch_results["successful"],
        "failed": batch_results["failed"],
        "details": [],
        "batch_stats": batch_results["batch_stats"],
    }

    # Extract details from batch results
    for batch_stat in batch_results["batch_stats"]:
        if "results" in batch_stat:
            results["details"].extend(batch_stat["results"])

    # Show summary message
    if results["success"] > 0:
        frappe.msgprint(
            _("Bulk suspension completed: {0} successful, {1} failed").format(
                results["success"], results["failed"]
            ),
            indicator="blue",
        )
    else:
        frappe.msgprint(_("Bulk suspension failed: No members were suspended"), indicator="red")

    return results


@handle_api_error
@performance_monitor()
@frappe.whitelist()
def get_suspension_list(limit=100, offset=0, status=None, chapter=None):
    """
    Get list of suspended members with pagination and filtering
    """
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
                team_count = frappe.db.count("Team Member", {"user": member["email"], "docstatus": 1})
                member["active_team_count"] = team_count
            else:
                member["active_team_count"] = 0
        else:
            member["active_team_count"] = 0

    return {
        "data": members,
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + limit) < total_count,
    }


@frappe.whitelist()
def test_bank_details_debug():
    """Test function to debug bank details issue"""
    return {
        "status": "working_from_api_file",
        "user": frappe.session.user,
        "form_data": dict(frappe.local.form_dict) if hasattr(frappe.local, "form_dict") else {},
    }
