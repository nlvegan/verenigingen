"""
Context for member dashboard page
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

from verenigingen.utils.member_utils import (
    get_active_membership_for_member,
    get_current_user_chapters,
    get_current_user_member_doc,
    get_member_customer,
    get_volunteer_for_member,
)


def get_context(context):
    """Get context for member dashboard"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access your dashboard"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Member Dashboard")

    # Get member record using standardized utility
    context.member = get_current_user_member_doc()

    # Get member chapters using standardized utility
    context.member_chapters = get_current_user_chapters()

    # Get active membership with grace period information using standardized utility
    membership = get_active_membership_for_member(
        context.member.name,
        [
            "name",
            "membership_type",
            "start_date",
            "renewal_date",
            "status",
            "grace_period_status",
            "grace_period_expiry_date",
            "grace_period_reason",
        ],
    )
    context.membership = membership

    # Add grace period status helpers
    if membership:
        context.in_grace_period = membership.grace_period_status == "Grace Period"
        if context.in_grace_period and membership.grace_period_expiry_date:
            days_until_expiry = (getdate(membership.grace_period_expiry_date) - getdate(today())).days
            context.grace_period_days_remaining = max(0, days_until_expiry)
            context.grace_period_expiring_soon = days_until_expiry <= 7
        else:
            context.grace_period_days_remaining = 0
            context.grace_period_expiring_soon = False

    # Get volunteer record if exists using standardized utility
    volunteer = get_volunteer_for_member(context.member.name)
    if volunteer:
        context.volunteer = frappe.get_doc("Volunteer", volunteer)

        # Calculate volunteer hours this year
        try:
            year_start = getdate(today()).replace(month=1, day=1)
            volunteer_hours = frappe.db.sql(
                """
                SELECT SUM(actual_hours) as total_hours
                FROM `tabVolunteer Assignment`
                WHERE parent = %s
                AND start_date >= %s
                AND status = 'Completed'
                AND actual_hours IS NOT NULL
            """,
                (volunteer, year_start),
                as_dict=True,
            )

            context.volunteer_hours = (
                volunteer_hours[0].total_hours if volunteer_hours and volunteer_hours[0].total_hours else 0
            )
        except Exception as e:
            frappe.log_error(f"Error calculating volunteer hours: {str(e)}")
            context.volunteer_hours = 0
    else:
        context.volunteer = None
        context.volunteer_hours = 0

    # Get recent activity
    context.recent_activity = get_member_activity(context.member.name)

    # Add member portal links
    context.portal_links = [
        {"title": _("Member Portal"), "route": "/member_portal", "featured": True},
        {"title": _("Personal Details"), "route": "/personal_details"},
        {"title": _("Account Settings"), "route": "/member_portal"},
        {"title": _("Update Address"), "route": "/address_change"},
        {"title": _("Bank Details"), "route": "/bank_details"},
        {"title": _("Adjust Fee"), "route": "/membership_fee_adjustment"},
    ]

    return context


def get_member_activity(member_name):
    """Get recent activity for member"""
    activities = []

    # Get recent payments
    payments = frappe.get_all(
        "Payment Entry",
        filters={
            "party_type": "Customer",
            "party": get_member_customer(member_name),
            "docstatus": 1,
        },
        fields=["name", "posting_date", "paid_amount"],
        order_by="posting_date desc",
        limit=3,
    )

    for payment in payments:
        activities.append(
            {
                "icon": "fa-credit-card",
                "description": _("Payment of {0} received").format(
                    frappe.format_value(payment.paid_amount, {"fieldtype": "Currency"})
                ),
                "date": payment.posting_date,
            }
        )

    # Get recent volunteer assignments if applicable using standardized utility
    volunteer = get_volunteer_for_member(member_name)
    if volunteer:
        assignments = frappe.get_all(
            "Volunteer Assignment",
            filters={"parent": volunteer},
            fields=["assignment_type", "start_date", "role"],
            order_by="start_date desc",
            limit=2,
        )

        for assignment in assignments:
            activities.append(
                {
                    "icon": "fa-heart",
                    "description": _("Volunteer assignment: {0}").format(
                        assignment.role or assignment.assignment_type
                    ),
                    "date": assignment.start_date,
                }
            )

    # Sort by date
    activities.sort(key=lambda x: x["date"], reverse=True)

    # Limit to 5 most recent
    return activities[:5]
