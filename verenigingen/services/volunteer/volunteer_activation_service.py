"""
Volunteer Activation Service

Handles activation of volunteer records during membership approval.
Moved from api/membership_application_review.py to proper service layer.

Functions:
    - activate_volunteer_record(): Activate volunteer record when membership is approved
    - _log_upgrade_result(): Log result of volunteer user account upgrade (private helper)
"""

import frappe
from frappe import _

from verenigingen.utils.member_utils import get_volunteer_for_member
from verenigingen.utils.safe_error_logging import safe_log_error


def _log_upgrade_result(upgrade_result, context_label):
    """Log the result of a volunteer user account upgrade.

    Args:
        upgrade_result: Dict from @critical_api-decorated upgrade_member_to_volunteer_user
        context_label: Description for log messages (e.g. "volunteer", "new volunteer")
    """
    if upgrade_result.get("success"):
        message = upgrade_result.get("meta", {}).get("message", "") if upgrade_result.get("meta") else ""
        frappe.logger().info(f"User account upgrade for {context_label}: {message}")
    else:
        error_obj = upgrade_result.get("error", {})
        errors = error_obj.get("errors", []) if isinstance(error_obj, dict) else []
        frappe.logger().warning(f"Could not upgrade user account for {context_label}: {'; '.join(errors)}")


def activate_volunteer_record(member):
    """Activate volunteer record when membership application is approved."""
    # Permission check - ensure user can write to Volunteer records
    if not frappe.has_permission("Volunteer", "write"):
        frappe.throw(_("You don't have permission to activate volunteers"))

    try:
        # Find existing volunteer record for this member
        volunteer_name = get_volunteer_for_member(member.name)

        # Also check by email in case member record was recreated
        if not volunteer_name:
            volunteer_name = frappe.db.get_value("Volunteer", {"email": member.email}, "name")
            if volunteer_name:
                frappe.logger().info(
                    f"Found orphaned volunteer {volunteer_name} by email, relinking to member {member.name}"
                )
                # Relink the volunteer to this member
                volunteer = frappe.get_doc("Volunteer", volunteer_name)
                volunteer.member = member.name
                volunteer.volunteer_name = (
                    member.full_name or f"{member.first_name} {member.last_name}".strip()
                )
                volunteer.save()

                # Also update member's volunteer_record field if it exists
                if hasattr(member, "volunteer_record"):
                    member.volunteer_record = volunteer_name
                    member.save()

        if volunteer_name:
            # Update existing volunteer record
            volunteer = frappe.get_doc("Volunteer", volunteer_name)
            volunteer.status = "Active"
            volunteer.save()
            frappe.logger().info(f"Activated volunteer record {volunteer_name} for member {member.name}")

            # Link volunteer to member record if not already linked
            if hasattr(member, "volunteer_record") and member.volunteer_record != volunteer_name:
                member.reload()  # Ensure we have latest data
                member.volunteer_record = volunteer_name
                member.save()
                frappe.logger().info(f"Linked volunteer {volunteer_name} to member {member.name}")

            # Upgrade user account from Website User to System User for volunteer access
            if member.user:
                try:
                    from verenigingen.services.member.account.account_creation_manager import (
                        upgrade_member_to_volunteer_user,
                    )

                    upgrade_result = upgrade_member_to_volunteer_user(member.name)
                    _log_upgrade_result(upgrade_result, "volunteer")
                except Exception as e:
                    frappe.logger().error(f"Error upgrading user account to System User: {str(e)}")
                    # Non-critical - continue with volunteer activation

            # Employee creation is now handled by AccountCreationManager
            # The account creation request will handle employee creation properly
            # with full security compliance and audit trail
            frappe.logger().info(
                f"Employee creation for volunteer {volunteer_name} will be handled by AccountCreationManager"
            )
        else:
            # Create volunteer record if it doesn't exist (fallback)
            from verenigingen.services.member.approval.application_helpers import create_volunteer_record

            volunteer = create_volunteer_record(member)
            if volunteer:
                volunteer.status = "Active"
                volunteer.save()
                frappe.logger().info(
                    f"Created and activated volunteer record {volunteer.name} for member {member.name}"
                )

                # Upgrade user account from Website User to System User for volunteer access
                if member.user:
                    try:
                        from verenigingen.services.member.account.account_creation_manager import (
                            upgrade_member_to_volunteer_user,
                        )

                        upgrade_result = upgrade_member_to_volunteer_user(member.name)
                        _log_upgrade_result(upgrade_result, "new volunteer")
                    except Exception as e:
                        frappe.logger().error(f"Error upgrading user account to System User: {str(e)}")
                        # Non-critical - continue with volunteer activation
    except Exception as e:
        safe_log_error(
            "Volunteer activation error",
            f"Error activating volunteer record for member {member.name}: {str(e)}",
        )
