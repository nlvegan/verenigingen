"""
Utility functions for member portal home page management
"""

import frappe
from frappe import _
from frappe.utils import getdate

from verenigingen.utils.constants import Roles


@frappe.whitelist()
def get_member_portal_stats():
    """
    Get statistics about member portal usage.

    Portal landing-page routing is handled by ``auth_hooks`` (server) and
    ``member_portal_redirect.js`` (client), not by a per-user field, so we
    only report the meaningful population counts here.
    """
    try:
        # Count all member users (by the role members actually hold).
        total_members = frappe.db.sql(
            """
            SELECT COUNT(DISTINCT u.name) as count
            FROM `tabUser` u
            JOIN `tabHas Role` hr ON hr.parent = u.name
            WHERE hr.role = %s
            AND u.enabled = 1
            AND u.name != 'Guest'
        """,
            (Roles.VERENIGINGEN_MEMBER,),
        )[0][0]

        # Count members with linked member records
        linked_members = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabMember` m
            WHERE m.user IS NOT NULL
        """
        )[0][0]

        return {
            "total_member_users": total_members,
            "members_with_linked_records": linked_members,
        }

    except Exception as e:
        frappe.logger().error(f"Error getting member portal stats: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
def get_user_appropriate_home_page():
    """
    Get the appropriate home page for the current user
    """
    user = frappe.session.user

    if user == "Guest":
        return "/web"

    # Check user roles
    user_roles = frappe.get_roles(user)

    # Check if user is linked to a member record
    member_record = frappe.db.get_value("Member", {"user": user}, "name")

    if member_record or Roles.VERENIGINGEN_MEMBER in user_roles:
        return "/member_portal"

    # Check if user is a volunteer
    volunteer_record = frappe.db.get_value("Volunteer", {"user": user}, "name")
    volunteer_roles = [
        "Verenigingen Volunteer",
        "Verenigingen Volunteer",
        "Verenigingen Chapter Board Member",
    ]

    if volunteer_record or any(role in user_roles for role in volunteer_roles):
        return "/member_portal"  # Could be a volunteer-specific portal later

    # System users get the app
    system_roles = Roles.ADMIN_ROLES
    if any(role in user_roles for role in system_roles):
        return "/app"

    # Default fallback
    return "/web"


def format_coverage_period(start_date, end_date, billing_frequency):
    """
    Format coverage period based on billing frequency and date alignment.

    Args:
        start_date: Coverage start date (string or date)
        end_date: Coverage end date (string or date)
        billing_frequency: Billing frequency (Daily, Monthly, Quarterly, Annual, etc.)

    Returns:
        Formatted string representing the coverage period
    """
    if not start_date or not end_date:
        return None

    try:
        start = getdate(start_date)
        end = getdate(end_date)
    except:
        return None

    # For daily billing, keep current due date format
    if billing_frequency.lower() in ["daily"]:
        return frappe.utils.formatdate(end)

    # For yearly billing
    if billing_frequency.lower() in ["annual", "annually", "yearly"]:
        # Check if it's a full calendar year
        if start.month == 1 and start.day == 1 and end.month == 12 and end.day == 31:
            return str(start.year)
        elif start.year == end.year:
            return str(start.year)
        else:
            return f"{frappe.utils.formatdate(start)} - {frappe.utils.formatdate(end)}"

    # For quarterly billing
    if billing_frequency.lower() in ["quarterly", "quarter"]:
        # Check if aligned with calendar quarters
        quarter_starts = {(1, 1): "Quarter 1", (4, 1): "Quarter 2", (7, 1): "Quarter 3", (10, 1): "Quarter 4"}

        if (start.month, start.day) in quarter_starts:
            quarter_name = quarter_starts[(start.month, start.day)]
            return f"{quarter_name} {start.year}"
        else:
            return f"{frappe.utils.formatdate(start)} - {frappe.utils.formatdate(end)}"

    # For monthly billing
    if billing_frequency.lower() in ["monthly", "month"]:
        # Check if it aligns closely with a calendar month (within 5 days)
        import calendar

        # Get the first and last day of the start month
        month_start = start.replace(day=1)
        month_end = start.replace(day=calendar.monthrange(start.year, start.month)[1])

        # Check alignment with tolerance of 5 days
        start_diff = abs((start - month_start).days)
        end_diff = abs((end - month_end).days)

        if start_diff <= 5 and end_diff <= 5:
            # Use month name
            return f"{start.strftime('%B %Y')}"
        else:
            # Use date range format
            return f"{frappe.utils.formatdate(start)} - {frappe.utils.formatdate(end)}"

    # Default fallback: show date range
    return f"{frappe.utils.formatdate(start)} - {frappe.utils.formatdate(end)}"


def enhance_outstanding_invoices_with_coverage(outstanding_invoices, billing_frequency):
    """
    Enhance outstanding invoices with formatted coverage periods.

    Args:
        outstanding_invoices: List of invoice dictionaries
        billing_frequency: Billing frequency string

    Returns:
        Enhanced list with coverage_period field added
    """
    if not outstanding_invoices:
        return outstanding_invoices

    enhanced_invoices = []

    for invoice in outstanding_invoices:
        enhanced_invoice = invoice.copy()

        # Get coverage dates from Sales Invoice
        try:
            coverage_data = frappe.db.get_value(
                "Sales Invoice",
                invoice["name"],
                ["custom_coverage_start_date", "custom_coverage_end_date"],
                as_dict=True,
            )

            if (
                coverage_data
                and coverage_data.custom_coverage_start_date
                and coverage_data.custom_coverage_end_date
            ):
                coverage_period = format_coverage_period(
                    coverage_data.custom_coverage_start_date,
                    coverage_data.custom_coverage_end_date,
                    billing_frequency,
                )
                enhanced_invoice["coverage_period"] = coverage_period
            else:
                # Fallback to due date if no coverage data
                enhanced_invoice["coverage_period"] = (
                    frappe.utils.formatdate(invoice.get("due_date"))
                    if invoice.get("due_date")
                    else _("No due date")
                )

        except Exception as e:
            frappe.log_error(f"Error getting coverage data for invoice {invoice['name']}: {str(e)}")
            enhanced_invoice["coverage_period"] = (
                frappe.utils.formatdate(invoice.get("due_date"))
                if invoice.get("due_date")
                else _("No due date")
            )

        enhanced_invoices.append(enhanced_invoice)

    return enhanced_invoices


def setup_portal_context(context, page_title):
    """Standard portal page context setup with graceful member lookup.

    Sets: context.no_cache, context.show_sidebar, context.title
    Returns: member_name (str) or None if no member found.
    When None, context.no_member_record/error_title/error_message are set.
    """
    from verenigingen.utils.error_handling import validate_user_logged_in
    from verenigingen.utils.member_utils import get_current_user_member_name

    validate_user_logged_in()
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _(page_title)

    member = get_current_user_member_name()
    if not member:
        context.no_member_record = True
        context.error_title = _("Member Record Not Found")
        context.error_message = _("No member record found for your account. Please contact support.")
        try:
            context.support_email = frappe.db.get_single_value("Verenigingen Settings", "support_email")
        except Exception:
            frappe.log_error("Failed to fetch support_email from Verenigingen Settings")
            context.support_email = None
        return None

    context.no_member_record = False
    return member
