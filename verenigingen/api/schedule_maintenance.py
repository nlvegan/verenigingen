"""
Schedule Maintenance API
Admin tools for managing dues schedules and preventing orphaned records
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.secure_operations import secure_document_operation

# Import security framework
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api
from verenigingen.utils.security.audit_logging import log_sensitive_operation
from verenigingen.utils.security.authorization import require_role
from verenigingen.utils.security.csrf_protection import validate_csrf_token
from verenigingen.utils.security.rate_limiting import rate_limit


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
@rate_limit(calls=10, period=60)  # 10 calls per minute
@require_role(["Accounts Manager", "System Manager", "Verenigingen Administrator"])
@validate_csrf_token
def get_schedule_health_report() -> OperationResult[Dict[str, Any]]:
    """
    Generate a comprehensive health report for all dues schedules
    Safe for regular use by administrators

    Returns:
        OperationResult: Schedule health report data
    """
    try:
        # Log this sensitive operation
        log_sensitive_operation(
            "schedule_maintenance", "get_schedule_health_report", {"requested_by": frappe.session.user}
        )

        # Check user permissions
        if not frappe.has_permission("Membership Dues Schedule", "read"):
            return OperationResult.fail(
                _("Insufficient permissions to view schedule maintenance"),
                errors=["Permission denied"],
                context={"operation": "get_schedule_health_report"},
            )

        # Get all active schedules
        active_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"status": "Active"},
            fields=[
                "name",
                "member",
                "schedule_name",
                "membership_type",
                "is_template",
                "creation",
                "dues_rate",
            ],
        )

        # Categorize schedules
        healthy_schedules = []
        orphaned_member_schedules = []
        orphaned_type_schedules = []
        template_schedules = []
        inappropriate_zero_rate_schedules = []

        for schedule in active_schedules:
            # Skip templates (they're supposed to not have members)
            if schedule.is_template:
                template_schedules.append(schedule)
                continue

            issues = []

            # Check member reference
            if schedule.member:
                if not frappe.db.exists("Member", schedule.member):
                    issues.append("missing_member")
            else:
                issues.append("no_member")

            # Check membership type reference
            if schedule.membership_type:
                if not frappe.db.exists("Membership Type", schedule.membership_type):
                    issues.append("missing_membership_type")
            else:
                issues.append("no_membership_type")

            # Check for zero rates - only flag if membership type requires payment
            if schedule.dues_rate == 0 and schedule.membership_type:
                # Check if the membership type allows zero rates (free memberships)
                membership_type_data = frappe.db.get_value(
                    "Membership Type", schedule.membership_type, ["minimum_amount"], as_dict=True
                )

                if membership_type_data and membership_type_data.minimum_amount > 0:
                    # Zero rate but membership type requires payment - this is problematic
                    issues.append("inappropriate_zero_rate")
                # If minimum_amount is 0, then zero rate is expected (free membership)

            # Categorize based on issues
            if not issues:
                healthy_schedules.append(schedule)
            else:
                if "missing_member" in issues:
                    orphaned_member_schedules.append({**schedule, "issues": issues})
                elif "missing_membership_type" in issues:
                    orphaned_type_schedules.append({**schedule, "issues": issues})
                elif "inappropriate_zero_rate" in issues:
                    inappropriate_zero_rate_schedules.append({**schedule, "issues": issues})

        data = {
            "report_date": now_datetime(),
            "total_active_schedules": len(active_schedules),
            "healthy_schedules": len(healthy_schedules),
            "template_schedules": len(template_schedules),
            "issues": {
                "orphaned_members": {
                    "count": len(orphaned_member_schedules),
                    "schedules": orphaned_member_schedules[:10],  # Show first 10
                },
                "orphaned_types": {
                    "count": len(orphaned_type_schedules),
                    "schedules": orphaned_type_schedules[:10],
                },
                "inappropriate_zero_rates": {
                    "count": len(inappropriate_zero_rate_schedules),
                    "schedules": inappropriate_zero_rate_schedules[:10],
                },
            },
            "recommendations": _generate_maintenance_recommendations(
                len(orphaned_member_schedules),
                len(orphaned_type_schedules),
                len(inappropriate_zero_rate_schedules),
            ),
        }

        return OperationResult.ok(data, message=_("Schedule health report generated successfully"))

    except Exception as e:
        frappe.log_error(
            f"Error getting schedule health report: {str(e)}\n{traceback.format_exc()}",
            "Schedule Health Report Error",
        )
        return OperationResult.fail(
            _("Failed to generate schedule health report"),
            errors=[str(e)],
            context={"operation": "get_schedule_health_report"},
        )


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
@rate_limit(calls=5, period=300)  # 5 calls per 5 minutes
@require_role(["Accounts Manager", "System Manager"])
@validate_csrf_token
def cleanup_orphaned_schedules(issue_type, dry_run=True) -> OperationResult[Dict[str, Any]]:
    """
    Clean up orphaned schedules with proper audit trail

    Args:
        issue_type: 'orphaned_members', 'orphaned_types', or 'zero_rates'
        dry_run: True to preview actions, False to execute

    Returns:
        OperationResult: Cleanup results
    """
    try:
        # Log this sensitive operation
        log_sensitive_operation(
            "schedule_maintenance",
            "cleanup_orphaned_schedules",
            {"issue_type": issue_type, "dry_run": dry_run, "requested_by": frappe.session.user},
        )

        # Check permissions
        if not frappe.has_permission("Membership Dues Schedule", "write"):
            return OperationResult.fail(
                _("Insufficient permissions for schedule maintenance"),
                errors=["Permission denied"],
                context={"operation": "cleanup_orphaned_schedules"},
            )

        if not dry_run and not frappe.has_permission("Membership Dues Schedule", "delete"):
            return OperationResult.fail(
                _("Insufficient permissions to cancel schedules"),
                errors=["Permission denied"],
                context={"operation": "cleanup_orphaned_schedules", "dry_run": dry_run},
            )

        # Get health report to identify issues
        health_report_result = get_schedule_health_report()
        if not health_report_result.success:
            return health_report_result

        health_report = health_report_result.data

        if issue_type == "orphaned_members":
            problem_schedules = health_report["issues"]["orphaned_members"]["schedules"]
            action_description = "Cancel schedules with missing member references"
        elif issue_type == "orphaned_types":
            problem_schedules = health_report["issues"]["orphaned_types"]["schedules"]
            action_description = "Cancel schedules with missing membership type references"
        elif issue_type == "inappropriate_zero_rates":
            problem_schedules = health_report["issues"]["inappropriate_zero_rates"]["schedules"]
            action_description = "Cancel schedules with inappropriate zero rates"
        else:
            return OperationResult.fail(
                _("Invalid issue type specified"),
                errors=[f"Invalid issue type: {issue_type}"],
                context={"operation": "cleanup_orphaned_schedules", "issue_type": issue_type},
            )

        if not problem_schedules:
            data = {"processed": 0, "dry_run": dry_run}
            return OperationResult.ok(data, message=_("No {0} found to clean up").format(issue_type))

        # Get full list (not just first 10 from report)
        if issue_type == "orphaned_members":
            # Get all schedules with missing members
            all_active = frappe.get_all(
                "Membership Dues Schedule",
                filters={"status": "Active", "is_template": 0},
                fields=["name", "member", "schedule_name"],
            )
            problem_schedules = [
                s for s in all_active if s.member and not frappe.db.exists("Member", s.member)
            ]

        cleanup_actions = []

        try:
            if not dry_run:
                frappe.db.begin()

            for schedule_data in problem_schedules:
                action = {
                    "schedule": schedule_data["name"],
                    "schedule_name": schedule_data.get("schedule_name", "N/A"),
                    "action": "would_cancel" if dry_run else "cancelled",
                    "issue": issue_type,
                    "reason": _get_cancellation_reason(schedule_data, issue_type),
                }

                if not dry_run:
                    # Create a proper audit trail
                    schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule_data["name"])
                    original_status = schedule_doc.status

                    # Cancel using direct SQL (safe approach proven to work)
                    frappe.db.sql(
                        """
                        UPDATE `tabMembership Dues Schedule`
                        SET status = 'Cancelled',
                            modified = NOW(),
                            modified_by = %s
                        WHERE name = %s
                    """,
                        (frappe.session.user, schedule_data["name"]),
                    )

                    # Add a comment for audit trail
                    comment_doc = frappe.get_doc(
                        {
                            "doctype": "Comment",
                            "comment_type": "Comment",
                            "reference_doctype": "Membership Dues Schedule",
                            "reference_name": schedule_data["name"],
                            "content": f'Automatically cancelled by schedule maintenance tool. Reason: {action["reason"]}. Original status: {original_status}.',
                        }
                    )
                    # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                    result = secure_document_operation(
                        operation="insert",
                        doc=comment_doc,
                        justification=f"Create audit trail comment for schedule {schedule_data['name']} cancellation - administrative compliance tracking",
                        required_permissions=["Comment:create"],
                    )

                    if not result.success:
                        frappe.log_error(
                            f"Failed to create audit comment for schedule {schedule_data['name']}: {'; '.join(result.errors)}"
                        )

                cleanup_actions.append(action)

            if not dry_run:
                frappe.db.commit()

            data = {
                "processed": len(cleanup_actions),
                "actions": cleanup_actions[:20],  # Limit response size
                "dry_run": dry_run,
                "total_found": len(problem_schedules),
            }

            message = _("{0}: {1} {2} schedules").format(
                action_description,
                "Would cancel" if dry_run else "Cancelled",
                len(cleanup_actions),
            )

            return OperationResult.ok(data, message=message)

        except Exception as e:
            if not dry_run:
                frappe.db.rollback()

            frappe.log_error(
                f"Error during cleanup: {str(e)}\n{traceback.format_exc()}",
                "Schedule Cleanup Error",
            )
            return OperationResult.fail(
                _("Error during cleanup operation"),
                errors=[str(e)],
                context={
                    "operation": "cleanup_orphaned_schedules",
                    "processed": len(cleanup_actions),
                    "actions": cleanup_actions,
                },
            )

    except Exception as e:
        frappe.log_error(
            f"Error in cleanup_orphaned_schedules: {str(e)}\n{traceback.format_exc()}",
            "Schedule Cleanup Error",
        )
        return OperationResult.fail(
            _("Failed to cleanup orphaned schedules"),
            errors=[str(e)],
            context={"operation": "cleanup_orphaned_schedules", "issue_type": issue_type, "dry_run": dry_run},
        )


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
@rate_limit(calls=15, period=60)  # 15 calls per minute
@require_role(["Accounts Manager", "System Manager", "Verenigingen Administrator"])
@validate_csrf_token
def prevent_orphaned_schedules() -> OperationResult[Dict[str, Any]]:
    """
    Check for potential issues before they become orphaned schedules
    Returns warnings about at-risk schedules

    Returns:
        OperationResult: Warnings about at-risk schedules
    """
    try:
        # Log this sensitive operation
        log_sensitive_operation(
            "schedule_maintenance", "prevent_orphaned_schedules", {"requested_by": frappe.session.user}
        )

        if not frappe.has_permission("Membership Dues Schedule", "read"):
            return OperationResult.fail(
                _("Insufficient permissions to view schedule maintenance"),
                errors=["Permission denied"],
                context={"operation": "prevent_orphaned_schedules"},
            )

        warnings = []

        # Check for schedules with members that have no active memberships
        # Use safer approach with frappe.get_all instead of complex SQL
        active_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"status": "Active", "is_template": 0},
            fields=["name", "schedule_name", "member"],
        )

        at_risk_count = 0
        at_risk_samples = []

        for schedule in active_schedules:
            if schedule.member:
                # Check if member has any active memberships
                active_memberships = frappe.get_all(
                    "Membership",
                    filters={"member": schedule.member, "status": "Active", "docstatus": 1},
                    limit=1,
                )

                if not active_memberships:
                    at_risk_count += 1
                    if len(at_risk_samples) < 10:
                        member_name = frappe.db.get_value("Member", schedule.member, "full_name")
                        at_risk_samples.append(
                            {
                                "name": schedule.name,
                                "schedule_name": schedule.schedule_name,
                                "member": schedule.member,
                                "member_name": member_name,
                                "issue": "No active membership",
                            }
                        )

        if at_risk_count > 0:
            warnings.append(
                {
                    "type": "inactive_membership",
                    "count": at_risk_count,
                    "message": "Schedules linked to members with no active memberships",
                    "schedules": at_risk_samples,
                }
            )

        # Check for schedules with inappropriate zero rates
        # (zero rates are fine for free memberships, but problematic for paid memberships)
        zero_rate_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"status": "Active", "is_template": 0, "dues_rate": 0},
            fields=["name", "schedule_name", "member", "membership_type"],
        )

        inappropriate_zero_count = 0
        inappropriate_zero_samples = []

        for schedule in zero_rate_schedules:
            if schedule.membership_type:
                # Check if this membership type should have a non-zero rate
                membership_type_data = frappe.db.get_value(
                    "Membership Type", schedule.membership_type, ["minimum_amount"], as_dict=True
                )

                if membership_type_data and membership_type_data.minimum_amount > 0:
                    inappropriate_zero_count += 1
                    if len(inappropriate_zero_samples) < 10:
                        inappropriate_zero_samples.append(
                            {
                                "name": schedule.name,
                                "schedule_name": schedule.schedule_name,
                                "member": schedule.member,
                                "membership_type": schedule.membership_type,
                                "issue": f"Zero rate but membership type requires minimum €{membership_type_data.minimum_amount}",
                            }
                        )

        if inappropriate_zero_count > 0:
            warnings.append(
                {
                    "type": "inappropriate_zero_rates",
                    "count": inappropriate_zero_count,
                    "message": "Schedules with zero rates for paid membership types",
                    "schedules": inappropriate_zero_samples,
                }
            )

        data = {
            "check_date": now_datetime(),
            "warnings": warnings,
            "total_warnings": sum(w["count"] for w in warnings),
        }

        warning_msg = (
            _("Found {0} potential issues").format(data["total_warnings"])
            if data["total_warnings"] > 0
            else _("No potential issues found")
        )

        return OperationResult.ok(data, message=warning_msg)

    except Exception as e:
        frappe.log_error(
            f"Error checking for orphaned schedules: {str(e)}\n{traceback.format_exc()}",
            "Schedule Prevention Check Error",
        )
        return OperationResult.fail(
            _("Failed to check for potential schedule issues"),
            errors=[str(e)],
            context={"operation": "prevent_orphaned_schedules"},
        )


def _generate_maintenance_recommendations(orphaned_members, orphaned_types, inappropriate_zero_rates):
    """Generate actionable recommendations based on health report"""

    recommendations = []

    if orphaned_members > 0:
        recommendations.append(
            {
                "priority": "high",
                "action": "cleanup_orphaned_schedules",
                "params": {"issue_type": "orphaned_members"},
                "description": f"Cancel {orphaned_members} schedules with missing member references",
                "impact": "Prevents invoice generation errors",
            }
        )

    if orphaned_types > 0:
        recommendations.append(
            {
                "priority": "medium",
                "action": "cleanup_orphaned_schedules",
                "params": {"issue_type": "orphaned_types"},
                "description": f"Cancel {orphaned_types} schedules with missing membership types",
                "impact": "Prevents validation errors during processing",
            }
        )

    if inappropriate_zero_rates > 0:  # Any inappropriate zero rates should be addressed
        recommendations.append(
            {
                "priority": "medium",
                "action": "cleanup_orphaned_schedules",
                "params": {"issue_type": "inappropriate_zero_rates"},
                "description": f"Fix {inappropriate_zero_rates} schedules with inappropriate zero rates",
                "impact": "Prevents under-billing for paid memberships",
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "priority": "info",
                "description": "All schedules appear healthy - no maintenance needed",
                "impact": "System ready for invoice generation",
            }
        )

    return recommendations


def _get_cancellation_reason(schedule_data, issue_type):
    """Generate human-readable cancellation reason"""

    if issue_type == "orphaned_members":
        return f"Member {schedule_data.get('member', 'N/A')} no longer exists"
    elif issue_type == "orphaned_types":
        return f"Membership type {schedule_data.get('membership_type', 'N/A')} no longer exists"
    elif issue_type == "inappropriate_zero_rates":
        return "Schedule has zero rate but membership type requires payment"
    else:
        return f"Issue type: {issue_type}"
