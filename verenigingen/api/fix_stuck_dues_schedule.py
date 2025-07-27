"""
Fix stuck dues schedules where last_invoice_date equals next_invoice_date
preventing invoice generation despite no actual invoice existing.
"""

import frappe
from frappe.utils import add_days, getdate, today

# Import security framework
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    high_security_api,
    standard_api,
    utility_api,
)


@high_security_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def diagnose_stuck_schedule(schedule_name):
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
        "dates_equal": schedule.last_invoice_date == schedule.next_invoice_date
        if schedule.last_invoice_date and schedule.next_invoice_date
        else False,
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


@high_security_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def fix_stuck_schedule(schedule_name, force=False):
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
                        "new_last_invoice_date": str(schedule.last_invoice_date)
                        if schedule.last_invoice_date
                        else None,
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


@standard_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def find_all_stuck_schedules():
    """
    Find all schedules that are stuck with last_invoice_date = next_invoice_date
    """
    # Optimized query with JOIN to avoid N+1 queries
    stuck_schedules = frappe.db.sql(
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
            CASE
                WHEN m.customer IS NOT NULL AND EXISTS (
                    SELECT 1 FROM `tabSales Invoice` si
                    WHERE si.customer = m.customer
                    AND si.posting_date = s.last_invoice_date
                    AND si.docstatus != 2
                ) THEN 1
                ELSE 0
            END as invoice_exists
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

    # Convert invoice_exists from int to boolean for clarity
    for schedule in stuck_schedules:
        schedule["invoice_exists"] = bool(schedule["invoice_exists"]) if schedule["customer"] else None

    return {
        "total_stuck": len(stuck_schedules),
        "schedules": stuck_schedules,
        "recommendation": "Run fix_stuck_schedule for each schedule where invoice_exists is False",
    }


@utility_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def check_and_notify_stuck_schedules():
    """
    Scheduled job to check for stuck schedules and notify administrators.
    To be run daily by the scheduler.
    """
    try:
        # Find all stuck schedules
        result = find_all_stuck_schedules()

        stuck_count = result["total_stuck"]
        stuck_schedules = result["schedules"]

        # Filter to only schedules where no invoice exists
        truly_stuck = [s for s in stuck_schedules if not s.get("invoice_exists")]
        truly_stuck_count = len(truly_stuck)

        if truly_stuck_count == 0:
            # No stuck schedules found - log success
            frappe.log_error(
                f"Daily stuck schedule check completed. Found {stuck_count} with matching dates, "
                f"but all have existing invoices. No action needed.",
                "Stuck Schedule Check - All Clear",
            )
            return {"success": True, "stuck_count": 0, "notifications_sent": 0}

        # Generate notification content using template
        notification_html = frappe.render_template(
            "verenigingen/templates/emails/stuck_dues_schedules_alert.html",
            {"truly_stuck_count": truly_stuck_count, "truly_stuck": truly_stuck},
        )

        # Get notification recipients from settings
        from verenigingen.utils.notification_helpers import get_notification_recipients

        admin_emails = get_notification_recipients("stuck_schedule_notification_emails")

        if admin_emails:
            # Send email notification
            frappe.sendmail(
                recipients=admin_emails,
                subject=f"[URGENT] {truly_stuck_count} Stuck Dues Schedules Found - Action Required",
                message=notification_html,
                now=True,
            )

            # Create in-app notifications
            for user in admin_users:
                if user.email:
                    try:
                        notification = frappe.new_doc("Notification Log")
                        notification.subject = f"🚨 {truly_stuck_count} Stuck Dues Schedules"
                        notification.for_user = user.email
                        notification.type = "Alert"
                        notification.document_type = "Membership Dues Schedule"
                        notification.from_user = "Administrator"
                        notification.email_content = notification_html
                        notification.insert(ignore_permissions=True)
                    except Exception as e:
                        frappe.log_error(f"Failed to create notification for {user.email}: {str(e)}")

        # Log the event for monitoring
        schedule_names = [s["name"] for s in truly_stuck]
        frappe.log_error(
            f"ALERT: Found {truly_stuck_count} stuck dues schedules requiring immediate attention.\n\n"
            f"Schedules: {', '.join(schedule_names)}\n\n"
            f"Notifications sent to {len(admin_emails)} administrators: {', '.join(admin_emails)}",
            "Stuck Schedule Alert Sent",
        )

        # Commit to ensure notifications are saved
        frappe.db.commit()

        return {
            "success": True,
            "stuck_count": truly_stuck_count,
            "notifications_sent": len(admin_emails),
            "stuck_schedule_names": schedule_names,
        }

    except Exception as e:
        error_msg = f"Error in scheduled stuck schedule check: {str(e)}\n\n{frappe.get_traceback()}"
        frappe.log_error(error_msg, "Stuck Schedule Check Error")

        # Try to notify admins about the error too
        try:
            admin_emails = frappe.get_all(
                "User", filters=[["Has Role", "role", "=", "System Manager"]], pluck="email"
            )
            if admin_emails:
                frappe.sendmail(
                    recipients=admin_emails,
                    subject="[ERROR] Stuck Schedule Check Failed",
                    message=f"<p>The daily stuck schedule check failed with error:</p><pre>{str(e)}</pre>",
                    now=True,
                )
        except:
            pass  # Don't let notification failure prevent error logging

        return {"success": False, "error": str(e)}
