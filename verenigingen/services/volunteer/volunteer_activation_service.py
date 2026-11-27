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

from verenigingen.utils.member_utils import get_orphan_volunteer_for_email, get_volunteer_for_member
from verenigingen.utils.safe_error_logging import safe_log_error
from verenigingen.utils.secure_operations import authorised_follow_on_steps, follow_on_ignore_permissions

UPGRADE_FAILED_TITLE = "Volunteer user upgrade refused"


def _log_upgrade_result(upgrade_result, context_label, member_name=None):
    """Log the result of a volunteer user account upgrade.

    Args:
        upgrade_result: Dict from @critical_api-decorated upgrade_member_to_volunteer_user
        context_label: Description for log messages (e.g. "volunteer", "new volunteer")
        member_name: Member being activated; a failure is recorded once per member
    """
    if upgrade_result.get("success"):
        message = upgrade_result.get("meta", {}).get("message", "") if upgrade_result.get("meta") else ""
        frappe.logger().info(f"User account upgrade for {context_label}: {message}")
    else:
        error_obj = upgrade_result.get("error", {})
        errors = error_obj.get("errors", []) if isinstance(error_obj, dict) else []
        detail = "; ".join(errors)
        frappe.logger().warning(f"Could not upgrade user account for {context_label}: {detail}")
        _record_upgrade_failure(context_label, member_name, detail)


def _record_upgrade_failure(context_label, member_name, detail):
    """Write a readable Error Log row (frappe.logger() output is never read), once per member.

    Since #2860 this is the normal outcome for a member-only volunteer: the account stays a
    Website User until the scheduled role profile sync grants the volunteer roles.
    """
    if member_name and frappe.db.exists(
        "Error Log", {"method": UPGRADE_FAILED_TITLE, "error": ["like", f"%{member_name}%"]}
    ):
        return
    frappe.log_error(
        title=UPGRADE_FAILED_TITLE,
        message=f"Member {member_name} ({context_label}): {detail or 'no detail'}. "
        "The account stays a Website User until the scheduled role profile sync.",
    )


def activate_volunteer_record(member):
    """Activate volunteer record when membership application is approved.

    The caller must have chapter-authorised the approver: the check in here is role-level only.
    Defensive hardening per ruling #1930 (#3022): approve_application cannot reach the failing branch today
    (it seats the member in the chapter first, so the approver may already write the Volunteer); the
    elevation guards a future caller or a change in chapter-row timing.
    """
    # Permission check - ensure user can write to Volunteer records
    if not frappe.has_permission("Volunteer", "write"):
        frappe.throw(_("You don't have permission to activate volunteers"))

    # The check above is the approver's own authorisation and stays. Once it has passed, the writes below
    # run with permission checks bypassed, still as the approver (#1930, #3022): a chapter board approver's
    # DocPerms refuse the Active flip on a Volunteer that has no chapter. The scope covers this call only.
    with authorised_follow_on_steps():
        _activate_volunteer_record_authorised(member)


def _activate_volunteer_record_authorised(member):
    """The activation writes. Call only inside `authorised_follow_on_steps` after the caller's permission check."""
    ignore_permissions = follow_on_ignore_permissions()
    try:
        # Find existing volunteer record for this member
        volunteer_name = get_volunteer_for_member(member.name)

        # Also check by email in case member record was recreated
        if not volunteer_name:
            # Orphans only (#2784): a Volunteer linked to another Member is not ours to repoint
            volunteer_name = get_orphan_volunteer_for_email(member.email)
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
                volunteer.save(ignore_permissions=ignore_permissions)

                # Also update member's volunteer_record field if it exists
                if hasattr(member, "volunteer_record"):
                    member.volunteer_record = volunteer_name
                    member.save(ignore_permissions=ignore_permissions)

        if volunteer_name:
            # Update existing volunteer record
            volunteer = frappe.get_doc("Volunteer", volunteer_name)
            volunteer.status = "Active"
            volunteer.save(ignore_permissions=ignore_permissions)
            frappe.logger().info(f"Activated volunteer record {volunteer_name} for member {member.name}")

            # Link volunteer to member record if not already linked
            if hasattr(member, "volunteer_record") and member.volunteer_record != volunteer_name:
                member.reload()  # Ensure we have latest data
                member.volunteer_record = volunteer_name
                member.save(ignore_permissions=ignore_permissions)
                frappe.logger().info(f"Linked volunteer {volunteer_name} to member {member.name}")

            # Upgrade user account from Website User to System User for volunteer access
            if member.user:
                try:
                    from verenigingen.services.member.account.account_creation_api import (
                        upgrade_member_to_volunteer_user,
                    )

                    upgrade_result = upgrade_member_to_volunteer_user(member.name)
                    _log_upgrade_result(upgrade_result, "volunteer", member.name)
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
                volunteer.save(ignore_permissions=ignore_permissions)
                frappe.logger().info(
                    f"Created and activated volunteer record {volunteer.name} for member {member.name}"
                )

                # Upgrade user account from Website User to System User for volunteer access
                if member.user:
                    try:
                        from verenigingen.services.member.account.account_creation_api import (
                            upgrade_member_to_volunteer_user,
                        )

                        upgrade_result = upgrade_member_to_volunteer_user(member.name)
                        _log_upgrade_result(upgrade_result, "new volunteer", member.name)
                    except Exception as e:
                        frappe.logger().error(f"Error upgrading user account to System User: {str(e)}")
                        # Non-critical - continue with volunteer activation
    except Exception as e:
        safe_log_error(
            "Volunteer activation error",
            f"Error activating volunteer record for member {member.name}: {str(e)}",
        )
