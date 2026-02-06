"""
Notification utilities for membership applications

.. deprecated:: 2.0
    This module contains inline HTML notification functions that are being migrated
    to Frappe's native Notification DocType. New code should use Frappe Notifications
    instead for document-triggered notifications.
    See: Setup > Email > Notification in Frappe Desk
"""

import warnings

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.services.communication.email_service import get_email_service


def send_approval_email(member, invoice):
    """Send email when application is approved with payment instructions.

    .. deprecated:: 2.0
        Uses inline HTML. Consider using 'Member Application Approved'
        Frappe Notification for automatic triggering on application_status change.
    """
    warnings.warn(
        "send_approval_email() uses inline HTML. "
        "Consider using Frappe Notification 'Member Application Approved'.",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        payment_url = frappe.utils.get_url() + f"/payment?invoice={invoice.name}"

        message = f"""
        <h3>Your membership application has been approved!</h3>

        <p>Dear {member.first_name},</p>

        <p>Congratulations! Your membership application has been approved.</p>

        <div style="background: #d4edda; border: 1px solid #c3e6cb; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h4>Next Steps:</h4>
            <ol>
                <li>Complete your membership payment</li>
                <li>Receive your membership confirmation</li>
                <li>Access member benefits and resources</li>
            </ol>
        </div>

        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h4>Payment Details:</h4>
            <ul>
                <li><strong>Amount:</strong> {frappe.utils.fmt_money(invoice.grand_total, currency=invoice.currency)}</li>
                <li><strong>Invoice:</strong> {invoice.name}</li>
                <li><strong>Due Date:</strong> {frappe.format_date(invoice.due_date)}</li>
            </ul>
        </div>

        <p><a href="{payment_url}"
             style="background: #28a745; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">
            Complete Payment
        </a></p>

        <p>If you have any questions, please don't hesitate to contact us.</p>

        <p>Best regards,<br>The Membership Team</p>
        """

        email_service = get_email_service()
        email_service.send_simple_email(
            recipients=[member.email],
            subject="Membership Approved - Payment Required",
            message=message,
            now=True,
            reference_doctype="Member",
            reference_name=member.name,
            notification_key="member_application_approved",
        )
    except Exception as e:
        frappe.log_error(f"Error sending approval email: {str(e)}", "Email Error")


def check_overdue_applications():
    """Check for applications pending more than 7 days"""
    seven_days_ago = add_days(today(), -7)

    overdue = frappe.get_all(
        "Member",
        filters={"application_status": "Pending", "application_date": ["<", seven_days_ago]},
        fields=["name", "full_name", "application_date", "email", "current_membership_type"],
    )

    if overdue:
        # Notify national board
        try:
            settings = frappe.get_single("Verenigingen Settings")
            if settings.national_board_chapter:
                national_board = frappe.get_doc("Chapter", settings.national_board_chapter)
                recipients = [bm.email for bm in national_board.board_members if bm.is_active and bm.email]

                if recipients:
                    # Use Email Template if available
                    # Calculate days overdue for each application
                    overdue_with_days = []
                    for app in overdue:
                        days_overdue = (getdate(today()) - getdate(app.application_date)).days
                        overdue_with_days.append({**app, "days_overdue": days_overdue})

                    args = {
                        "overdue_applications": overdue_with_days,
                        "overdue_count": len(overdue),
                        "reviewer_name": "Membership Team",
                        "company": frappe.get_single("Verenigingen Settings").company_name
                        or frappe.get_value(
                            "Company", frappe.get_single("Verenigingen Settings").company, "company_name"
                        ),
                        "base_url": frappe.utils.get_url(),
                    }

                    if frappe.db.exists("Email Template", "membership_applications_overdue"):
                        email_template_doc = frappe.get_doc(
                            "Email Template", "membership_applications_overdue"
                        )
                        email_service = get_email_service()
                        email_service.send_simple_email(
                            recipients=recipients,
                            subject=frappe.render_template(email_template_doc.subject, args),
                            message=frappe.render_template(email_template_doc.response, args),
                            now=True,
                            notification_key="member_application_overdue",
                        )
                    else:
                        # Fallback to simple message
                        app_list = "\n".join(
                            [
                                f"<li>{app['full_name']} (Applied: {app['application_date']}, {app.get('days_overdue', 0)} days overdue)</li>"
                                for app in overdue_with_days
                            ]
                        )
                        message = f"""
                        <h3>Overdue Membership Applications</h3>
                        <p>The following membership applications have been pending for more than 7 days:</p>
                        <ul>
                        {app_list}
                        </ul>
                        <p>Please review these applications as soon as possible.</p>
                        """
                        email_service = get_email_service()
                        email_service.send_simple_email(
                            recipients=recipients,
                            subject="Overdue Membership Applications",
                            message=message,
                            now=True,
                            notification_key="member_application_overdue",
                        )
        except Exception as e:
            frappe.log_error(f"Error notifying about overdue applications: {str(e)}")
