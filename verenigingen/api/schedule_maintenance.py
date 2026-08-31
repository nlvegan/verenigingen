"""
Schedule Maintenance API
Admin tools for managing dues schedules and preventing orphaned records
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from verenigingen.utils.constants import Roles
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.secure_operations import secure_document_operation

# Import security framework
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api
from verenigingen.utils.security.audit_logging import log_sensitive_operation
from verenigingen.utils.security.authorization import require_role
from verenigingen.utils.security.csrf_protection import require_csrf_token


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
@require_role(["Accounts Manager", Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN])
@require_csrf_token
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

        # Categorize all active schedules (shared with cleanup, which needs the
        # COMPLETE lists rather than the display-capped preview below).
        categorized = _categorize_active_schedules()
        orphaned_member_schedules = categorized["orphaned_members"]
        orphaned_type_schedules = categorized["orphaned_types"]
        inappropriate_zero_rate_schedules = categorized["inappropriate_zero_rates"]

        data = {
            "report_date": now_datetime(),
            "total_active_schedules": categorized["active_total"],
            "healthy_schedules": len(categorized["healthy"]),
            "template_schedules": len(categorized["templates"]),
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


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
@require_role(["Accounts Manager", Roles.SYSTEM_MANAGER])
@require_csrf_token
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

        # Identify the COMPLETE set of problem schedules. We call the shared
        # categorizer directly (not get_schedule_health_report, which is a
        # decorated endpoint that serializes its result to a dict and whose
        # display lists are capped to 10) so cleanup never silently skips
        # records beyond the first 10.
        categorized = _categorize_active_schedules()

        if issue_type == "orphaned_members":
            problem_schedules = categorized["orphaned_members"]
            action_description = "Cancel schedules with missing member references"
        elif issue_type == "orphaned_types":
            problem_schedules = categorized["orphaned_types"]
            action_description = "Cancel schedules with missing membership type references"
        elif issue_type == "inappropriate_zero_rates":
            problem_schedules = categorized["inappropriate_zero_rates"]
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

        cleanup_actions = []

        try:
            # NOTE: do NOT call frappe.db.begin() here. The @high_security_api /
            # @require_role decorators and log_sensitive_operation() above have
            # already written audit rows in the ambient request transaction, so an
            # explicit START TRANSACTION trips Frappe's implicit-commit guard and the
            # whole destructive path fails. We accumulate writes in the ambient
            # transaction and commit() at the end (rollback() on error).
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

                    # Cancel below the ORM: this tool exists to clean up schedules the
                    # controller's own validation would reject, so a doc.save() is not an
                    # option. frappe.db.set_value is the same bypass -- it explicitly does
                    # not run document events -- but it maintains `modified`/`modified_by`
                    # itself and clears the document cache, which the raw UPDATE this
                    # replaced did neither of. That UPDATE wrote `modified = NOW()`:
                    # MariaDB's NOW() is the DATABASE SERVER's clock at SECOND precision,
                    # while Frappe fills these datetime(6) columns from the SITE clock with
                    # microseconds. Two writes inside one second therefore collapsed to the
                    # same stamp and Document.check_if_latest -- which compares it as a
                    # string -- stopped rejecting stale in-memory copies (#453).
                    frappe.db.set_value(
                        "Membership Dues Schedule",
                        schedule_data["name"],
                        "status",
                        "Cancelled",
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


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
@require_role(["Accounts Manager", Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN])
@require_csrf_token
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


def _categorize_active_schedules():
    """Categorize every active dues schedule by health issue.

    Returns the COMPLETE (un-capped) lists. Shared by get_schedule_health_report
    (which slices each list to 10 for display) and cleanup_orphaned_schedules
    (which must operate on the full set). Keeping this in one place prevents the
    cleanup path from silently skipping records beyond the report's first-10 preview.

    Issue precedence (a schedule lands in at most one bucket): missing_member >
    missing_membership_type > inappropriate_zero_rate.
    """
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

    healthy = []
    orphaned_members = []
    orphaned_types = []
    templates = []
    inappropriate_zero_rates = []

    for schedule in active_schedules:
        # Skip templates (they're supposed to not have members)
        if schedule.is_template:
            templates.append(schedule)
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
            membership_type_data = frappe.db.get_value(
                "Membership Type", schedule.membership_type, ["minimum_amount"], as_dict=True
            )
            if membership_type_data and membership_type_data.minimum_amount > 0:
                # Zero rate but membership type requires payment - this is problematic
                issues.append("inappropriate_zero_rate")
            # If minimum_amount is 0, then zero rate is expected (free membership)

        # Categorize based on issues (precedence via the elif chain)
        if not issues:
            healthy.append(schedule)
        elif "missing_member" in issues:
            orphaned_members.append({**schedule, "issues": issues})
        elif "missing_membership_type" in issues:
            orphaned_types.append({**schedule, "issues": issues})
        elif "inappropriate_zero_rate" in issues:
            inappropriate_zero_rates.append({**schedule, "issues": issues})

    return {
        "active_total": len(active_schedules),
        "healthy": healthy,
        "orphaned_members": orphaned_members,
        "orphaned_types": orphaned_types,
        "templates": templates,
        "inappropriate_zero_rates": inappropriate_zero_rates,
    }


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
