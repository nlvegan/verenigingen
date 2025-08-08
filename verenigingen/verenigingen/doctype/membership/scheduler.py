import frappe
from frappe import _
from frappe.utils import add_days, today
from frappe.utils.background_jobs import enqueue


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
            "Has Role", filters={"role": "Verenigingen Manager", "parenttype": "User"}, fields=["parent"]
        )

        for manager in membership_managers:
            user = frappe.get_doc("User", manager.parent)
            if user.enabled and user.email:
                recipients.append(user.email)

        # Also add any specific emails configured in settings
        if hasattr(settings, "orphaned_report_recipients") and settings.orphaned_report_recipients:
            recipients.extend([r.strip() for r in settings.orphaned_report_recipients.split(",")])

        if recipients:
            frappe.sendmail(
                recipients=recipients,
                subject="Orphaned Memberships and Dues Schedules Report",
                message=email_content,
                reference_doctype="Membership",
                reference_name="Report",
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
    memberships = frappe.get_all(
        "Membership",
        filters={"status": "Active", "renewal_date": ["<", today()], "docstatus": 1},
        fields=["name"],
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

    return count


def send_renewal_reminders():
    """Send renewal reminders for memberships expiring soon"""
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

            # Prepare context for email
            context = {
                "member": member.as_dict(),
                "membership": membership,
                "days_to_expiry": membership.days_to_expiry,
            }

            # Send email using Email Template
            email_template_doc = frappe.get_doc("Email Template", template)
            frappe.sendmail(
                recipients=membership.email,
                subject=email_template_doc.subject
                or f"Membership Renewal Reminder: {membership.days_to_expiry} days left",
                message=frappe.render_template(email_template_doc.response, context),
                header=[_("Membership Renewal"), "blue"],
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
                "bank_account": member.bank_account,
                "amount": 0,  # Would be fetched from dues schedule
            }
        )

    # TODO: Implement actual generation of SEPA Direct Debit XML file
    # For now, just return the batch data structure
    return batch


@frappe.whitelist()
def enqueue_process_expired_memberships():
    """Enqueue processing of expired memberships as a background job"""
    return enqueue(
        process_expired_memberships, queue="long", timeout=30000, job_name="process_expired_memberships"
    )


@frappe.whitelist()
def enqueue_send_renewal_reminders():
    """Enqueue sending of renewal reminders as a background job"""
    return enqueue(send_renewal_reminders, queue="long", timeout=30000, job_name="send_renewal_reminders")


@frappe.whitelist()
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
