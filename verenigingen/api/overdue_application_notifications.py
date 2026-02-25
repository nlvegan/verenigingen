"""
Overdue membership application notification system.

Handles sending notifications for membership applications that have been pending
for more than 2 weeks. Called by scheduled tasks and report UI.
Extracted from membership_application_review.py for separation of concerns.
"""

import frappe
from frappe.utils import add_days, today

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
