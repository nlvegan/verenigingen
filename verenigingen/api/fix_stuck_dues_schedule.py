"""
Fix stuck dues schedules where last_invoice_date equals next_invoice_date
preventing invoice generation despite no actual invoice existing.
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.utils.constants import Roles
from verenigingen.utils.secure_operations import secure_document_operation

# Import security framework
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    high_security_api,
    standard_api,
    utility_api,
)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def diagnose_stuck_schedule(schedule_name: str):
    """
    Diagnose why a dues schedule is not generating invoices
    """
    schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
    member_doc = frappe.get_doc("Member", schedule.member) if schedule.member else None

    diagnosis = {
        "schedule_name": schedule_name,
        "member": schedule.member,
        "member_name": schedule.member_name,
        "status": schedule.status,
        "auto_generate": schedule.auto_generate,
        "billing_frequency": schedule.billing_frequency,
        "dues_rate": schedule.dues_rate,
        "next_invoice_date": str(schedule.next_invoice_date) if schedule.next_invoice_date else None,
        "last_invoice_date": str(schedule.last_invoice_date) if schedule.last_invoice_date else None,
        "invoice_days_before": schedule.invoice_days_before,
        "dates_equal": (
            schedule.last_invoice_date == schedule.next_invoice_date
            if schedule.last_invoice_date and schedule.next_invoice_date
            else False
        ),
        "customer": member_doc.customer if member_doc else None,
        "member_status": member_doc.status if member_doc else None,
        "issues_found": [],
    }

    # Check for the stuck condition
    if (
        schedule.last_invoice_date
        and schedule.next_invoice_date
        and schedule.last_invoice_date == schedule.next_invoice_date
    ):
        diagnosis["issues_found"].append("STUCK: last_invoice_date equals next_invoice_date")

        # Check if an invoice actually exists for this date
        if member_doc and member_doc.customer:
            existing_invoice = frappe.db.exists(
                "Sales Invoice",
                {
                    "customer": member_doc.customer,
                    "posting_date": schedule.last_invoice_date,
                    "docstatus": ["!=", 2],  # Not cancelled
                },
            )

            if not existing_invoice:
                diagnosis["issues_found"].append("NO INVOICE EXISTS for the last_invoice_date")
                diagnosis["recommended_fix"] = "Reset dates to allow invoice generation"

    # Check if it's time to generate
    if schedule.next_invoice_date:
        days_before = schedule.invoice_days_before if schedule.invoice_days_before is not None else 30
        generate_on_date = add_days(schedule.next_invoice_date, -days_before)
        diagnosis["generate_on_date"] = str(generate_on_date)
        diagnosis["today_date"] = str(today())
        diagnosis["should_generate_today"] = getdate(today()) >= getdate(generate_on_date)

    # Run can_generate_invoice check
    can_generate, reason = schedule.can_generate_invoice()
    diagnosis["can_generate"] = can_generate
    diagnosis["can_generate_reason"] = reason

    # Check for recent invoices
    if member_doc and member_doc.customer:
        recent_invoices = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member_doc.customer, "posting_date": [">=", add_days(today(), -30)]},
            fields=["name", "posting_date", "grand_total", "status"],
            order_by="posting_date desc",
            limit=5,
        )
        diagnosis["recent_invoices"] = recent_invoices

    return diagnosis


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def fix_stuck_schedule(schedule_name: str, force=False):
    """
    Fix a stuck dues schedule by resetting the dates appropriately
    """
    schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

    # Diagnose first
    diagnosis = diagnose_stuck_schedule(schedule_name)

    if not diagnosis.get("issues_found") and not force:
        return {"success": False, "message": "No issues found with this schedule", "diagnosis": diagnosis}

    # Check if we have the stuck condition
    if (
        schedule.last_invoice_date
        and schedule.next_invoice_date
        and schedule.last_invoice_date == schedule.next_invoice_date
    ):
        # Check if an invoice actually exists
        member_doc = frappe.get_doc("Member", schedule.member)
        if member_doc.customer:
            existing_invoice = frappe.db.exists(
                "Sales Invoice",
                {
                    "customer": member_doc.customer,
                    "posting_date": schedule.last_invoice_date,
                    "docstatus": ["!=", 2],
                },
            )

            if not existing_invoice:
                # No invoice exists, so we need to fix the dates
                # Option 1: If last_invoice_date is yesterday or older, set next_invoice_date to today
                # Option 2: Calculate the proper next date based on frequency

                old_last_invoice_date = schedule.last_invoice_date
                old_next_invoice_date = schedule.next_invoice_date

                # For daily billing, if the date is yesterday, we should generate today
                if schedule.billing_frequency == "Daily" and getdate(schedule.last_invoice_date) < getdate(
                    today()
                ):
                    schedule.next_invoice_date = today()
                else:
                    # Calculate the next invoice date based on frequency
                    schedule.next_invoice_date = schedule.calculate_next_invoice_date(
                        schedule.last_invoice_date
                    )

                # Clear the last_invoice_date if no invoice was actually generated
                schedule.last_invoice_date = None

                # Save the schedule
                schedule.save()

                return {
                    "success": True,
                    "message": "Schedule dates have been fixed",
                    "changes": {
                        "old_last_invoice_date": str(old_last_invoice_date),
                        "old_next_invoice_date": str(old_next_invoice_date),
                        "new_last_invoice_date": (
                            str(schedule.last_invoice_date) if schedule.last_invoice_date else None
                        ),
                        "new_next_invoice_date": str(schedule.next_invoice_date),
                    },
                    "can_generate_now": schedule.can_generate_invoice(),
                }
            else:
                # Invoice exists, so we need to advance to the next period
                old_next_invoice_date = schedule.next_invoice_date
                schedule.next_invoice_date = schedule.calculate_next_invoice_date(schedule.next_invoice_date)
                schedule.save()

                return {
                    "success": True,
                    "message": "Schedule advanced to next period",
                    "changes": {
                        "old_next_invoice_date": str(old_next_invoice_date),
                        "new_next_invoice_date": str(schedule.next_invoice_date),
                    },
                    "invoice_exists": existing_invoice,
                }

    return {"success": False, "message": "Unable to determine appropriate fix", "diagnosis": diagnosis}


@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)
def find_all_stuck_schedules():
    """
    Find all schedules that are stuck - enhanced detection for multiple stuck patterns:
    - Type A: last_invoice_date = next_invoice_date (original logic)
    - Type B: next_invoice_date is overdue (validation-blocked schedules)
    - Type C: Missing expected invoices based on billing frequency
    """
    from frappe.utils import date_diff

    # Type A: Original stuck schedules (dates equal)
    type_a_schedules = frappe.db.sql(
        """
        SELECT
            s.name,
            s.member,
            s.member_name,
            s.billing_frequency,
            s.dues_rate,
            s.last_invoice_date,
            s.next_invoice_date,
            s.status,
            s.auto_generate,
            m.customer,
            'Type A: Equal Dates' as stuck_type,
            CASE
                WHEN m.customer IS NOT NULL AND EXISTS (
                    SELECT 1 FROM `tabSales Invoice` si
                    WHERE si.customer = m.customer
                    AND si.posting_date = s.last_invoice_date
                    AND si.docstatus != 2
                ) THEN 1
                ELSE 0
            END as invoice_exists_for_date
        FROM `tabMembership Dues Schedule` s
        LEFT JOIN `tabMember` m ON s.member = m.name
        WHERE s.is_template = 0
            AND s.status = 'Active'
            AND s.auto_generate = 1
            AND s.last_invoice_date IS NOT NULL
            AND s.next_invoice_date IS NOT NULL
            AND s.last_invoice_date = s.next_invoice_date
        ORDER BY s.last_invoice_date DESC
    """,
        as_dict=True,
    )

    # Type B: Overdue schedules (validation-blocked)
    type_b_schedules = frappe.db.sql(
        """
        SELECT
            s.name,
            s.member,
            s.member_name,
            s.billing_frequency,
            s.dues_rate,
            s.last_invoice_date,
            s.next_invoice_date,
            s.status,
            s.auto_generate,
            m.customer,
            'Type B: Overdue Invoice' as stuck_type,
            DATEDIFF(CURDATE(), s.next_invoice_date) as days_overdue,
            CASE
                WHEN m.customer IS NOT NULL AND EXISTS (
                    SELECT 1 FROM `tabSales Invoice` si
                    WHERE si.customer = m.customer
                    AND si.posting_date >= s.next_invoice_date
                    AND si.docstatus != 2
                ) THEN 1
                ELSE 0
            END as invoice_exists_for_date
        FROM `tabMembership Dues Schedule` s
        LEFT JOIN `tabMember` m ON s.member = m.name
        WHERE s.is_template = 0
            AND s.status = 'Active'
            AND s.auto_generate = 1
            AND s.next_invoice_date IS NOT NULL
            AND s.next_invoice_date < CURDATE()
            AND s.last_invoice_date != s.next_invoice_date  -- Exclude Type A
            AND (
                -- Daily schedules: overdue by 2+ days
                (s.billing_frequency = 'Daily' AND DATEDIFF(CURDATE(), s.next_invoice_date) >= 2)
                OR
                -- Weekly schedules: overdue by 2+ days
                (s.billing_frequency = 'Weekly' AND DATEDIFF(CURDATE(), s.next_invoice_date) >= 2)
                OR
                -- Monthly schedules: overdue by 5+ days
                (s.billing_frequency = 'Monthly' AND DATEDIFF(CURDATE(), s.next_invoice_date) >= 5)
                OR
                -- Quarterly schedules: overdue by 7+ days
                (s.billing_frequency = 'Quarterly' AND DATEDIFF(CURDATE(), s.next_invoice_date) >= 7)
                OR
                -- Annual schedules: overdue by 14+ days
                (s.billing_frequency = 'Annual' AND DATEDIFF(CURDATE(), s.next_invoice_date) >= 14)
                OR
                -- Custom frequencies: overdue by 7+ days (conservative)
                (s.billing_frequency = 'Custom' AND DATEDIFF(CURDATE(), s.next_invoice_date) >= 7)
            )
        ORDER BY days_overdue DESC, s.next_invoice_date ASC
    """,
        as_dict=True,
    )

    # Combine all stuck schedules
    all_stuck = type_a_schedules + type_b_schedules

    # Convert invoice_exists from int to boolean for clarity
    for schedule in all_stuck:
        schedule["invoice_exists"] = (
            bool(schedule["invoice_exists_for_date"]) if schedule["customer"] else None
        )
        # Calculate severity based on stuck type and days overdue
        if schedule["stuck_type"].startswith("Type B"):
            days_overdue = schedule.get("days_overdue", 0)
            if days_overdue >= 30:
                schedule["severity"] = "CRITICAL"
            elif days_overdue >= 14:
                schedule["severity"] = "HIGH"
            elif days_overdue >= 7:
                schedule["severity"] = "MEDIUM"
            else:
                schedule["severity"] = "LOW"
        else:
            schedule["severity"] = "MEDIUM"  # Type A schedules

    return {
        "total_stuck": len(all_stuck),
        "type_a_count": len(type_a_schedules),
        "type_b_count": len(type_b_schedules),
        "schedules": all_stuck,
        "recommendation": "Run fix_stuck_schedule for schedules where invoice_exists is False or severity is HIGH/CRITICAL",
    }


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def check_and_notify_stuck_schedules():
    """
    Enhanced scheduled job to check for multiple types of stuck schedules.
    Detects both equal-date issues and validation-blocked overdue schedules.
    """
    try:
        # Find all stuck schedules (enhanced detection)
        result = find_all_stuck_schedules()

        total_stuck = result["total_stuck"]
        type_a_count = result["type_a_count"]
        type_b_count = result["type_b_count"]
        stuck_schedules = result["schedules"]

        # Filter schedules needing immediate attention
        critical_stuck = [
            s
            for s in stuck_schedules
            if not s.get("invoice_exists") or s.get("severity") in ["HIGH", "CRITICAL"]
        ]
        critical_count = len(critical_stuck)

        # Separate reporting for different issue types
        type_a_issues = [s for s in stuck_schedules if s["stuck_type"].startswith("Type A")]
        type_b_issues = [s for s in stuck_schedules if s["stuck_type"].startswith("Type B")]

        type_a_critical = [s for s in type_a_issues if not s.get("invoice_exists")]
        type_b_critical = [s for s in type_b_issues if s.get("severity") in ["HIGH", "CRITICAL"]]

        if critical_count == 0:
            # No critical issues - log informational status
            frappe.log_error(
                f"Daily stuck schedule check completed. Found {total_stuck} potential issues:\n"
                f"- Type A (Equal Dates): {type_a_count} (all have existing invoices)\n"
                f"- Type B (Overdue): {type_b_count} (all low/medium severity)\n"
                f"No critical action needed.",
                "Stuck Schedule Check - All Clear",
            )
            return {
                "success": True,
                "stuck_count": 0,
                "total_found": total_stuck,
                "type_breakdown": {"type_a": type_a_count, "type_b": type_b_count},
                "notifications_sent": 0,
            }

        # Generate enhanced notification content
        notification_html = frappe.render_template(
            "verenigingen/templates/emails/stuck_dues_schedules_alert.html",
            {
                "critical_count": critical_count,
                "critical_stuck": critical_stuck,
                "type_a_critical": type_a_critical,
                "type_b_critical": type_b_critical,
                "total_found": total_stuck,
                "type_breakdown": {"type_a": type_a_count, "type_b": type_b_count},
            },
        )

        # Get notification recipients from settings
        from verenigingen.utils.notification_helpers import get_notification_recipients

        admin_emails = get_notification_recipients("stuck_schedule_notification_emails")

        if admin_emails:
            # Determine urgency level based on critical issues
            urgency_emoji = "🔥" if any(s.get("severity") == "CRITICAL" for s in critical_stuck) else "🚨"

            # Create in-app notifications (email delivery is controlled by user preferences)
            for email in admin_emails:
                if email:
                    try:
                        notification = frappe.new_doc("Notification Log")
                        notification.subject = f"{urgency_emoji} {critical_count} Stuck Dues Schedules"
                        notification.for_user = email
                        notification.type = "Alert"
                        notification.document_type = "Membership Dues Schedule"
                        notification.from_user = "Administrator"
                        notification.email_content = notification_html
                        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                        result = secure_document_operation(
                            operation="insert",
                            doc=notification,
                            justification=f"Create stuck dues schedule notification for user {email} - financial schedule monitoring alert",
                            required_permissions=["Notification Log:create"],
                        )

                        if not result.success:
                            frappe.log_error(
                                f"Failed to create notification for {email}: {'; '.join(result.errors)}"
                            )
                    except Exception as e:
                        frappe.log_error(f"Failed to create notification for {email}: {str(e)}")

        # Enhanced logging with breakdown by issue type
        critical_names = [s["name"] for s in critical_stuck]
        type_a_names = [s["name"] for s in type_a_critical]
        type_b_names = [s["name"] for s in type_b_critical]

        frappe.log_error(
            f"ALERT: Found {critical_count} stuck dues schedules requiring immediate attention.\n\n"
            f"BREAKDOWN:\n"
            f"- Type A Critical (Equal Dates, No Invoice): {len(type_a_critical)}\n"
            f"  Schedules: {', '.join(type_a_names) if type_a_names else 'None'}\n\n"
            f"- Type B Critical (Overdue, Validation-Blocked): {len(type_b_critical)}\n"
            f"  Schedules: {', '.join(type_b_names) if type_b_names else 'None'}\n\n"
            f"Total found: {total_stuck} (Type A: {type_a_count}, Type B: {type_b_count})\n\n"
            f"Notifications sent to {len(admin_emails)} administrators: {', '.join(admin_emails)}",
            "Enhanced Stuck Schedule Alert Sent",
        )

        # Commit to ensure notifications are saved
        frappe.db.commit()

        return {
            "success": True,
            "stuck_count": critical_count,
            "total_found": total_stuck,
            "type_breakdown": {
                "type_a_total": type_a_count,
                "type_a_critical": len(type_a_critical),
                "type_b_total": type_b_count,
                "type_b_critical": len(type_b_critical),
            },
            "notifications_sent": len(admin_emails),
            "critical_schedule_names": critical_names,
        }

    except Exception as e:
        error_msg = f"Error in scheduled stuck schedule check: {str(e)}\n\n{frappe.get_traceback()}"
        frappe.log_error(error_msg, "Stuck Schedule Check Error")

        # Try to notify admins about the error too
        try:
            from verenigingen.utils.notification_helpers import notify_administrators

            notify_administrators(
                subject="[ERROR] Stuck Schedule Check Failed",
                message=f"<p>The daily stuck schedule check failed with error:</p><pre>{str(e)}</pre>",
                default_roles=[Roles.SYSTEM_MANAGER],
                notification_type="Alert",
                document_type="Membership Dues Schedule",
            )
        except:
            pass  # Don't let notification failure prevent error logging

        return {"success": False, "error": str(e)}
