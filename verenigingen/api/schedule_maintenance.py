"""
Schedule Maintenance API
Admin tools for managing dues schedules and preventing orphaned records
"""

import frappe
from frappe.utils import now_datetime, today


@frappe.whitelist()
def get_schedule_health_report():
    """
    Generate a comprehensive health report for all dues schedules
    Safe for regular use by administrators
    """

    # Check user permissions
    if not frappe.has_permission("Membership Dues Schedule", "read"):
        frappe.throw("Insufficient permissions to view schedule maintenance")

    # Get all active schedules
    active_schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"status": "Active"},
        fields=["name", "member", "schedule_name", "membership_type", "is_template", "creation", "dues_rate"],
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

    return {
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


@frappe.whitelist()
def cleanup_orphaned_schedules(issue_type, dry_run=True):
    """
    Clean up orphaned schedules with proper audit trail

    Args:
        issue_type: 'orphaned_members', 'orphaned_types', or 'zero_rates'
        dry_run: True to preview actions, False to execute
    """

    # Check permissions
    if not frappe.has_permission("Membership Dues Schedule", "write"):
        frappe.throw("Insufficient permissions for schedule maintenance")

    if not dry_run and not frappe.has_permission("Membership Dues Schedule", "delete"):
        frappe.throw("Insufficient permissions to cancel schedules")

    # Get health report to identify issues
    health_report = get_schedule_health_report()

    if issue_type == "orphaned_members":
        problem_schedules = health_report["issues"]["orphaned_members"]["schedules"]
        action_description = "Cancel schedules with missing member references"
    elif issue_type == "orphaned_types":
        problem_schedules = health_report["issues"]["orphaned_types"]["schedules"]
        action_description = "Cancel schedules with missing membership type references"
    elif issue_type == "inappropriate_zero_rates":
        problem_schedules = health_report["issues"]["inappropriate_zero_rates"]["schedules"]
        action_description = "Cancel schedules with inappropriate zero dues rates"
    else:
        frappe.throw(f"Invalid issue type: {issue_type}")

    if not problem_schedules:
        return {
            "success": True,
            "message": f"No {issue_type} found to clean up",
            "processed": 0,
            "dry_run": dry_run,
        }

    # Get full list (not just first 10 from report)
    if issue_type == "orphaned_members":
        # Get all schedules with missing members
        all_active = frappe.get_all(
            "Membership Dues Schedule",
            filters={"status": "Active", "is_template": 0},
            fields=["name", "member", "schedule_name"],
        )
        problem_schedules = [s for s in all_active if s.member and not frappe.db.exists("Member", s.member)]

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
                frappe.get_doc(
                    {
                        "doctype": "Comment",
                        "comment_type": "Comment",
                        "reference_doctype": "Membership Dues Schedule",
                        "reference_name": schedule_data["name"],
                        "content": f'Automatically cancelled by schedule maintenance tool. Reason: {action["reason"]}. Original status: {original_status}.',
                    }
                ).insert(ignore_permissions=True)

            cleanup_actions.append(action)

        if not dry_run:
            frappe.db.commit()

        return {
            "success": True,
            "message": f'{action_description}: {"Would cancel" if dry_run else "Cancelled"} {len(cleanup_actions)} schedules',
            "processed": len(cleanup_actions),
            "actions": cleanup_actions[:20],  # Limit response size
            "dry_run": dry_run,
            "total_found": len(problem_schedules),
        }

    except Exception as e:
        if not dry_run:
            frappe.db.rollback()

        return {
            "success": False,
            "message": f"Error during cleanup: {str(e)}",
            "processed": 0,
            "actions": cleanup_actions,
        }


@frappe.whitelist()
def prevent_orphaned_schedules():
    """
    Check for potential issues before they become orphaned schedules
    Returns warnings about at-risk schedules
    """

    if not frappe.has_permission("Membership Dues Schedule", "read"):
        frappe.throw("Insufficient permissions to view schedule maintenance")

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
                "Membership", filters={"member": schedule.member, "status": "Active", "docstatus": 1}, limit=1
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

    return {
        "check_date": now_datetime(),
        "warnings": warnings,
        "total_warnings": sum(w["count"] for w in warnings),
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
