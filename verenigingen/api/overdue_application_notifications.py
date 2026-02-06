"""
Overdue membership application notification system.

Handles sending notifications for membership applications that have been pending
for more than 2 weeks. Called by scheduled tasks and report UI.
Extracted from membership_application_review.py for separation of concerns.
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.services.communication.email_service import get_email_service
from verenigingen.utils.security.api_security_framework import standard_api


@frappe.whitelist()
@standard_api()  # Notification sending utility
def send_overdue_notifications(**kwargs):
    """Send notifications for overdue applications (> 2 weeks)"""
    # This would be called by a scheduled job

    two_weeks_ago = add_days(today(), -14)

    # Get overdue applications
    overdue = frappe.get_all(
        "Member",
        filters={"application_status": "Pending", "application_date": ["<", two_weeks_ago]},
        fields=["name", "full_name", "application_date"],
    )

    if not overdue:
        return

    # Group by chapter


def notify_chapter_of_overdue_applications(chapter_name, applications):
    """Notify chapter board of overdue applications"""
    chapter = frappe.get_doc("Chapter", chapter_name)

    # Get board members with membership permissions
    recipients = []
    for board_member in chapter.board_members:
        if board_member.is_active and board_member.email:
            role = frappe.get_doc("Chapter Role", board_member.chapter_role)
            if role.permissions_level in ["Admin", "Membership"]:
                recipients.append(board_member.email)

    if recipients:
        email_service = get_email_service()
        email_service.send_simple_email(
            recipients=recipients,
            subject=f"Action Required: {len(applications)} Overdue Membership Applications",
            message="""
            <h3>Overdue Membership Applications for {chapter_name}</h3>

            <p>The following membership applications have been pending for more than 2 weeks:</p>

            <ul>
            {app_list}
            </ul>

            <p>Please review these applications as soon as possible.</p>

            <p><a href="{frappe.utils.get_url()}/app/report/pending-membership-applications?chapter={chapter_name}">
            View All Pending Applications</a></p>
            """,
            now=True,
            notification_key="member_application_overdue",
        )


def notify_managers_of_overdue_applications(applications):
    """Notify association managers of overdue applications without chapters"""
    # Get all association managers
    managers = frappe.get_all("Has Role", filters={"role": "Verenigingen Administrator"}, pluck="parent")

    if managers:
        recipients = [
            frappe.get_value("User", m, "email") for m in managers if frappe.get_value("User", m, "enabled")
        ]

        if recipients:
            email_service = get_email_service()
            email_service.send_simple_email(
                recipients=recipients,
                subject=f"Action Required: {len(applications)} Unassigned Overdue Applications",
                message="""
                <h3>Overdue Membership Applications Without Chapter Assignment</h3>

                <p>The following membership applications have been pending for more than 2 weeks
                and have no chapter assignment:</p>

                <ul>
                {app_list}
                </ul>

                <p>Please review and assign these applications to appropriate chapters.</p>

                <p><a href="{frappe.utils.get_url()}/app/report/pending-membership-applications?chapter=Unassigned">
                View Unassigned Applications</a></p>
                """,
                now=True,
                notification_key="member_application_overdue",
            )
