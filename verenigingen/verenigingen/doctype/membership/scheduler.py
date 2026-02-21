import frappe
from frappe import _
from frappe.utils import add_days, today
from frappe.utils.background_jobs import enqueue

from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import OperationType, critical_api
from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config


def setup_membership_scheduler_events():
    """Set up the scheduler events for membership automation"""
    return {
        "daily": [
            "verenigingen.verenigingen.doctype.membership.scheduler.process_expired_memberships",
            "verenigingen.verenigingen.doctype.membership.scheduler.send_renewal_reminders",
            # Note: Auto-renewal removed - renewal is handled by the billing/dues schedule system
        ]
    }


def notify_about_orphaned_records():
    """Send email notifications about orphaned memberships and dues schedules"""
    try:
        # TODO: The orphaned_dues_schedules_report module is missing
        # For now, we'll implement a simple query directly here

        orphaned_data = _get_orphaned_records_data()

        if not orphaned_data:
            return

        # Prepare the email content
        email_content = "<h3>Orphaned Memberships and Dues Schedules Report</h3>"
        email_content += "<p>The following issues were detected in the system:</p>"

        email_content += "<table border='1' cellpadding='5' style='border-collapse: collapse;'>"
        email_content += "<tr><th>Type</th><th>Document</th><th>Status</th><th>Issue</th></tr>"

        for item in orphaned_data:
            email_content += "<tr>"
            email_content += f"<td>{item['record_type']}</td>"
            email_content += f"<td><a href='/app/{item['record_type'].lower()}/{item['document']}'>{item['document']}</a></td>"
            email_content += f"<td>{item['status']}</td>"
            email_content += f"<td>{item['issue']}</td>"
            email_content += "</tr>"

        email_content += "</table>"

        email_content += "<p>Please review these issues and take appropriate action.</p>"

        # Get recipients from Verenigingen Settings
        settings = frappe.get_single("Verenigingen Settings")
        recipients = []

        # Add appropriate roles or specific users as recipients
        membership_managers = frappe.get_all(
            "Has Role", filters={"role": Roles.VERENIGINGEN_STAFF, "parenttype": "User"}, fields=["parent"]
        )

        for manager in membership_managers:
            user = frappe.get_doc("User", manager.parent)
            if user.enabled and user.email:
                recipients.append(user.email)

        # Also add any specific emails configured in settings
        if hasattr(settings, "orphaned_report_recipients") and settings.orphaned_report_recipients:
            recipients.extend([r.strip() for r in settings.orphaned_report_recipients.split(",")])

        if recipients:
            # MIGRATED: Use unified EmailService for orphaned records report
            from verenigingen.services.communication.email_service import get_email_service

            email_service = get_email_service()

            context = {
                "orphaned_data": orphaned_data,
                "company": get_mollie_config().get_default_company(),
            }

            email_service.send_templated_email(
                template_name="orphaned_records_report",
                recipients=recipients,
                context=context,
                reference_doctype="Membership",
                reference_name="Report",
                notification_key="system_stuck_schedules",  # Admin notification about data issues
            )
    except ImportError as e:
        frappe.log_error(
            f"Could not import orphaned dues schedules report: {str(e)}", "Scheduler Import Error"
        )
        return
    except Exception as e:
        frappe.log_error(f"Error in notify_about_orphaned_records: {str(e)}", "Scheduler Error")
        return


def process_expired_memberships():
    """Mark memberships as expired if end date has passed"""
    from verenigingen.utils.db_advisory_lock import get_lock, release_lock

    if not get_lock("sched_process_expired_memberships", timeout=0):
        frappe.logger().info("process_expired_memberships already running, skipping")
        return 0

    try:
        return _process_expired_memberships_impl()
    finally:
        release_lock("sched_process_expired_memberships")


def _process_expired_memberships_impl():
    batch_size = 500

    memberships = frappe.get_all(
        "Membership",
        filters={"status": "Active", "renewal_date": ["<", today()], "docstatus": 1},
        fields=["name"],
        limit_page_length=batch_size,
    )

    count = 0
    for membership in memberships:
        try:
            doc = frappe.get_doc("Membership", membership.name)
            doc.status = "Expired"
            doc.save()

            # Log the change
            frappe.logger().info(f"Membership {doc.name} marked as Expired")

            # Update member status
            doc.update_member_status()
            count += 1
        except Exception as e:
            frappe.logger().error(f"Error updating membership {membership.name}: {str(e)}")

    if count:
        frappe.logger().info(f"Processed {count} expired memberships")
        if count >= batch_size:
            frappe.logger().warning(
                f"Batch limit ({batch_size}) reached — more expired memberships may remain for next run"
            )

    return count


def send_renewal_reminders():
    """Send renewal reminders for memberships expiring soon"""
    from verenigingen.utils.db_advisory_lock import get_lock, release_lock

    if not get_lock("sched_send_renewal_reminders", timeout=0):
        frappe.logger().info("send_renewal_reminders already running, skipping")
        return 0

    try:
        return _send_renewal_reminders_impl()
    finally:
        release_lock("sched_send_renewal_reminders")


def _send_renewal_reminders_impl():
    # Look for memberships expiring in the next 30, 15, and 7 days
    upcoming_expiry = []

    for days in [30, 15, 7, 1]:
        expiry_date = add_days(today(), days)

        memberships = frappe.get_all(
            "Membership",
            filters={"status": "Active", "renewal_date": expiry_date, "docstatus": 1},
            fields=["name", "member", "member_name", "email", "membership_type", "renewal_date"],
        )

        for membership in memberships:
            membership.days_to_expiry = days
            upcoming_expiry.append(membership)

    count = 0
    for membership in upcoming_expiry:
        try:
            # Get email template
            template = f"membership_renewal_reminder_{membership.days_to_expiry}_days"
            if not frappe.db.exists("Email Template", template):
                template = "membership_renewal_reminder"

            if not frappe.db.exists("Email Template", template):
                frappe.logger().warning(f"Email template {template} not found")
                continue

            # Get member details
            member = frappe.get_doc("Member", membership.member)

            # Context prepared below as enhanced_context

            # MIGRATED: Use unified EmailService for renewal reminders
            from verenigingen.services.communication.email_service import get_email_service

            email_service = get_email_service()

            # Enhanced context for unified service
            enhanced_context = {
                "member": member.as_dict(),
                "membership": membership,
                "days_to_expiry": membership.days_to_expiry,
                "company": frappe.defaults.get_global_default("company"),
            }

            email_service.send_templated_email(
                template_name=template,
                recipients=[membership.email],
                context=enhanced_context,
                subject_override=f"Membership Renewal Reminder: {membership.days_to_expiry} days left",
                reference_doctype="Membership",
                reference_name=membership.name,
                notification_key="membership_renewal_reminder",
            )

            # Log the email
            frappe.logger().info(
                f"Sent renewal reminder to {membership.email} for membership {membership.name}"
            )
            count += 1

        except Exception as e:
            frappe.logger().error(f"Error sending renewal reminder for {membership.name}: {str(e)}")

    if count:
        frappe.logger().info(f"Sent {count} renewal reminders")

    return count


def process_auto_renewals():
    """DEPRECATED: Auto-renewal is now handled by the billing/dues schedule system"""
    # Auto-renewal functionality has been moved to the dues schedule system
    # This function is kept for backward compatibility but does nothing
    frappe.logger().info("Auto-renewal is now handled by the billing/dues schedule system")
    return 0


def generate_direct_debit_batch():
    """Generate a batch for direct debit payments"""
    # To be implemented for Nederlandse incassobatches
    # This is a placeholder for the Dutch-specific direct debit functionality
    # that doesn't exist in ERPNext yet

    pending_memberships = frappe.get_all(
        "Membership",
        filters={"status": "Pending", "docstatus": 1},
        fields=["name", "member", "member_name"],
    )

    if not pending_memberships:
        frappe.logger().info("No pending memberships for direct debit")
        return 0

    # Create batch header
    # Note: This is placeholder code - actual amounts would come from dues schedules
    batch = {
        "creation_date": today(),
        "total_amount": 0,  # Would be calculated from dues schedules
        "currency": "EUR",  # Default currency
        "entry_count": len(pending_memberships),
        "entries": [],
    }

    # Add entries to batch
    for membership in pending_memberships:
        member = frappe.get_doc("Member", membership.member)

        # Skip if no bank details
        if not hasattr(member, "bank_account") or not member.bank_account:
            frappe.logger().warning(f"No bank account for member {member.name}")
            continue

        batch["entries"].append(
            {
                "membership": membership.name,
                "member": member.name,
                "member_name": member.full_name,
                "bank_account": member.bank_account_name,
                "amount": 0,  # Would be fetched from dues schedule
            }
        )

    # TODO: Implement actual generation of SEPA Direct Debit XML file
    # For now, just return the batch data structure
    return batch


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def enqueue_process_expired_memberships():
    """Enqueue processing of expired memberships as a background job"""
    return enqueue(
        process_expired_memberships, queue="long", timeout=30000, job_name="process_expired_memberships"
    )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def enqueue_send_renewal_reminders():
    """Enqueue sending of renewal reminders as a background job"""
    return enqueue(send_renewal_reminders, queue="long", timeout=30000, job_name="send_renewal_reminders")


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def enqueue_process_auto_renewals():
    """DEPRECATED: Auto-renewal is now handled by the billing/dues schedule system"""
    frappe.logger().info("Auto-renewal is now handled by the billing/dues schedule system")
    return {
        "status": "deprecated",
        "message": "Auto-renewal is now handled by the billing/dues schedule system",
    }


def _get_orphaned_records_data():
    """Get orphaned memberships and dues schedules data"""
    orphaned_records = []

    try:
        # Find memberships without dues schedules
        orphaned_memberships = frappe.db.sql(
            """
            SELECT
                m.name,
                m.member,
                m.membership_type,
                m.status
            FROM `tabMembership` m
            LEFT JOIN `tabMembership Dues Schedule` mds ON mds.membership = m.name
            WHERE m.docstatus = 1
            AND m.status = 'Active'
            AND mds.name IS NULL
        """,
            as_dict=True,
        )

        for membership in orphaned_memberships:
            orphaned_records.append(
                {
                    "record_type": "Membership",
                    "document": membership.name,
                    "status": membership.status,
                    "issue": "No dues schedule found",
                }
            )

        # Find dues schedules without active memberships
        orphaned_schedules = frappe.db.sql(
            """
            SELECT
                mds.name,
                mds.membership,
                mds.status
            FROM `tabMembership Dues Schedule` mds
            LEFT JOIN `tabMembership` m ON m.name = mds.membership
            WHERE mds.docstatus = 1
            AND (m.name IS NULL OR m.status != 'Active')
        """,
            as_dict=True,
        )

        for schedule in orphaned_schedules:
            orphaned_records.append(
                {
                    "record_type": "Membership Dues Schedule",
                    "document": schedule.name,
                    "status": schedule.status,
                    "issue": "Membership not found or inactive",
                }
            )
    except Exception as e:
        frappe.log_error(f"Error getting orphaned records data: {str(e)}", "Orphaned Records Query Error")

    return orphaned_records
