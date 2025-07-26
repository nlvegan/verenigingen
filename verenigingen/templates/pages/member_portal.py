"""
Member Portal Landing Page - TailwindCSS Version
Provides an overview and easy access to all member portal pages
"""

import frappe
from frappe import _
from frappe.utils import getdate, today


def get_context(context):
    """Get context for member portal landing page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access the member portal"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Member Portal")

    # Get brand settings for logo (needed even if no member record)
    try:
        brand_settings = frappe.get_all(
            "Brand Settings", fields=["name", "logo", "primary_color"], limit=1, order_by="modified desc"
        )
        if brand_settings:
            context.brand_logo = brand_settings[0].logo
        else:
            context.brand_logo = None
    except Exception:
        context.brand_logo = None

    # Get member record
    member = frappe.db.get_value("Member", {"email": frappe.session.user})
    if not member:
        # Show a graceful error message instead of throwing
        context.no_member_record = True
        context.error_title = _("Member Record Not Found")
        context.error_message = _(
            "No member record found for your account. Please contact support if you believe this is an error."
        )
        # Try to get support email from settings, with fallback
        try:
            context.support_email = frappe.db.get_single_value("Verenigingen Settings", "support_email")
        except Exception:
            # If field doesn't exist, try company email or use default
            try:
                company = frappe.db.get_single_value("Verenigingen Settings", "company")
                if company:
                    context.support_email = (
                        frappe.db.get_value("Company", company, "email") or "support@example.com"
                    )
                else:
                    context.support_email = "support@example.com"
            except Exception:
                context.support_email = "support@example.com"
        return context

    context.member = frappe.get_doc("Member", member)
    context.no_member_record = False

    # Get active membership
    membership = frappe.db.get_value(
        "Membership",
        {"member": member, "status": "Active", "docstatus": 1},
        ["name", "membership_type", "start_date", "renewal_date", "status"],
        as_dict=True,
    )
    context.membership = membership

    # Get volunteer record if exists
    volunteer = frappe.db.get_value("Volunteer", {"member": member})
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
    context.recent_activity = get_member_activity(member)

    # Get user teams if volunteer exists
    if context.volunteer:
        context.user_teams = get_user_teams(context.volunteer.name)
    else:
        context.user_teams = []

    # Get payment status information
    context.payment_status = get_payment_status(context.member, membership)

    # Get quick actions based on member status
    context.quick_actions = get_quick_actions(context.member, membership, context.volunteer)

    return context


def has_website_permission(doc, ptype, user, verbose=False):
    """Check website permission for member portal page"""
    # Only logged-in users can access
    if user == "Guest":
        return False

    # Check if user has a member record
    member = frappe.db.get_value("Member", {"email": user})
    return bool(member)


def get_member_activity(member_name):
    """Get recent activity for member"""
    activities = []

    # Get recent payments
    payments = frappe.get_all(
        "Payment Entry",
        filters={
            "party_type": "Customer",
            "party": frappe.db.get_value("Member", member_name, "customer"),
            "docstatus": 1,
        },
        fields=["name", "posting_date", "paid_amount"],
        order_by="posting_date desc",
        limit=3,
    )

    for payment in payments:
        activities.append(
            {
                "icon": "fa-money",
                "description": _("Payment of {0} received").format(
                    frappe.format_value(payment.paid_amount, {"fieldtype": "Currency"})
                ),
                "date": payment.posting_date,
            }
        )

    # Get recent volunteer assignments if applicable
    volunteer = frappe.db.get_value("Volunteer", {"member": member_name})
    if volunteer:
        assignments = frappe.get_all(
            "Volunteer Assignment",
            filters={"parent": volunteer},
            fields=["assignment_type", "start_date", "role", "reference_doctype", "reference_name"],
            order_by="start_date desc",
            limit=2,
        )

        for assignment in assignments:
            # Build description with organization info
            assignment_desc = assignment.role or assignment.assignment_type

            # Add organization context based on reference
            if assignment.reference_name and assignment.reference_doctype:
                if assignment.reference_doctype == "Chapter":
                    # For Chapter, the name itself is the chapter name
                    assignment_desc += f" ({_('Chapter')}: {assignment.reference_name})"
                elif assignment.reference_doctype == "Team":
                    # For Team, get the team_name field
                    org_name = (
                        frappe.db.get_value("Team", assignment.reference_name, "team_name")
                        or assignment.reference_name
                    )
                    assignment_desc += f" ({_('Team')}: {org_name})"
                else:
                    assignment_desc += f" ({assignment.reference_name})"

            activities.append(
                {
                    "icon": "fa-heart",
                    "description": _("Volunteer assignment: {0}").format(assignment_desc),
                    "date": assignment.start_date,
                }
            )

    # Get recent membership changes
    member_doc = frappe.get_doc("Member", member_name)
    if member_doc.modified:
        # Add chapter context if member belongs to chapters
        description = _("Profile updated")

        # Get member's chapters
        member_chapters = frappe.get_all(
            "Chapter Member", filters={"member": member_name, "enabled": 1}, fields=["parent"], limit=2
        )

        if member_chapters:
            chapter_names = []
            for chapter_member in member_chapters:
                # For Chapter, the name itself is the chapter name
                chapter_name = chapter_member.parent
                chapter_names.append(chapter_name)

            if len(chapter_names) == 1:
                description += f" ({_('Chapter')}: {chapter_names[0]})"
            elif len(chapter_names) > 1:
                description += f" ({_('Chapters')}: {', '.join(chapter_names)})"

        activities.append(
            {"icon": "fa-user", "description": description, "date": getdate(member_doc.modified)}
        )

    # Get recent SEPA mandate changes
    recent_mandate = frappe.get_all(
        "SEPA Mandate",
        filters={"member": member_name},
        fields=["creation", "status", "mandate_id"],
        order_by="creation desc",
        limit=1,
    )

    if recent_mandate:
        mandate = recent_mandate[0]
        activities.append(
            {
                "icon": "fa-bank",
                "description": _("SEPA mandate {0} {1}").format(
                    mandate.mandate_id, _("activated") if mandate.status == "Active" else _("updated")
                ),
                "date": getdate(mandate.creation),
            }
        )

    # Sort by date and limit to 5 most recent
    activities.sort(key=lambda x: x["date"], reverse=True)
    return activities[:5]


def get_quick_actions(member, membership, volunteer):
    """Get quick actions based on member status"""
    actions = []

    # Payment-related actions
    if not membership:
        actions.append(
            {
                "title": _("Update Payment Details"),
                "route": "/bank_details",
                "class": "btn-primary",
                "icon": "fa-id-card",
            }
        )
    elif membership.status != "Active":
        actions.append(
            {
                "title": _("Update Payment Details"),
                "route": "/bank_details",
                "class": "btn-primary",
                "icon": "fa-refresh",
            }
        )

    # Bank details setup
    if not member.iban:
        actions.append(
            {
                "title": _("Set Up Bank Details"),
                "route": "/bank_details",
                "class": "btn-primary",
                "icon": "fa-university",
            }
        )
    elif member.payment_method != "SEPA Direct Debit":
        actions.append(
            {
                "title": _("Enable Auto-Pay"),
                "route": "/bank_details",
                "class": "btn-secondary",
                "icon": "fa-magic",
            }
        )

    # Address updates
    address_incomplete = False
    try:
        if not member.primary_address:
            address_incomplete = True
        else:
            # Check if the linked address has required fields
            address_doc = frappe.get_doc("Address", member.primary_address)
            if not address_doc.address_line1 or not address_doc.city:
                address_incomplete = True
    except Exception:
        address_incomplete = True

    if address_incomplete:
        actions.append(
            {
                "title": _("Complete Address"),
                "route": "/address_change",
                "class": "btn-secondary",
                "icon": "fa-map-marker",
            }
        )

    # Volunteer-specific actions
    if volunteer:
        try:
            # Check for pending expense claims
            pending_expenses = frappe.db.count(
                "Volunteer Expense",
                filters={
                    "volunteer": volunteer.name,
                    "status": "Draft",  # Now all pending expenses are in Draft status
                },
            )

            if pending_expenses:
                actions.append(
                    {
                        "title": _("Review Expense Claims ({0})").format(pending_expenses),
                        "route": "/volunteer/expenses",
                        "class": "btn-secondary",
                        "icon": "fa-receipt",
                    }
                )
            else:
                actions.append(
                    {
                        "title": _("Submit Expenses"),
                        "route": "/volunteer/expenses",
                        "class": "btn-secondary",
                        "icon": "fa-plus",
                    }
                )
        except Exception as e:
            frappe.log_error(f"Error checking volunteer expenses: {str(e)}")
            # Add a generic volunteer expenses link if error occurs
            actions.append(
                {
                    "title": _("Volunteer Expenses"),
                    "route": "/volunteer/expenses",
                    "class": "btn-secondary",
                    "icon": "fa-receipt",
                }
            )

    # Fee adjustment if needed
    try:
        if getattr(member, "dues_rate", None):
            actions.append(
                {
                    "title": _("Review Fee Adjustment"),
                    "route": "/membership_fee_adjustment",
                    "class": "btn-secondary",
                    "icon": "fa-euro",
                }
            )
    except Exception:
        pass  # Ignore if field doesn't exist

    # Contact request action - always available
    actions.append(
        {
            "title": _("Contact Support"),
            "route": "/contact_request",
            "class": "btn-secondary",
            "icon": "fa-envelope",
        }
    )

    return actions


def get_payment_status(member, membership):
    """Get comprehensive payment status for member"""
    if not member:
        return None

    try:
        # Get current fee information
        current_fee_info = member.get_current_membership_fee()

        # Get membership billing frequency from the Membership Type doctype
        billing_frequency = "Monthly"  # Default fallback
        if membership:
            try:
                # Get the billing period from the Membership Type doctype
                membership_type_doc = frappe.get_doc("Membership Type", membership.membership_type)
                billing_period = getattr(membership_type_doc, "billing_period", "Monthly")

                # Map billing periods to display names
                billing_frequency_map = {
                    "Daily": "Daily",
                    "Monthly": "Monthly",
                    "Quarterly": "Quarterly",
                    "Biannual": "Biannually",
                    "Annual": "Annually",
                    "Lifetime": "Lifetime",
                    "Custom": "Custom",
                }

                billing_frequency = billing_frequency_map.get(billing_period, billing_period)
            except Exception as e:
                frappe.log_error(
                    f"Error getting billing frequency for membership {membership.name}: {str(e)}"
                )
                # Use explicit default with better error handling
                billing_frequency = "Monthly"  # Explicit default
                frappe.log_error(
                    f"Using fallback billing frequency 'Monthly' for membership {membership.name} due to error: {str(e)}",
                    "Member Portal Billing Frequency Fallback",
                )

        # Get outstanding invoices
        customer = frappe.db.get_value("Member", member.name, "customer")
        outstanding_invoices = []
        total_outstanding = 0

        if customer:
            invoices = frappe.db.sql(
                """
                SELECT name, posting_date, due_date, grand_total, outstanding_amount, status
                FROM `tabSales Invoice`
                WHERE customer = %(customer)s
                AND outstanding_amount > 0
                AND docstatus = 1
                ORDER BY due_date ASC
            """,
                {"customer": customer},
                as_dict=True,
            )

            for invoice in invoices:
                outstanding_invoices.append(
                    {
                        "name": invoice.name,
                        "posting_date": invoice.posting_date,
                        "due_date": invoice.due_date,
                        "amount": invoice.grand_total,
                        "outstanding": invoice.outstanding_amount,
                        "status": invoice.status,
                        "is_overdue": getdate(invoice.due_date) < getdate(today())
                        if invoice.due_date
                        else False,
                    }
                )
                total_outstanding += invoice.outstanding_amount

        # Get next billing date from dues schedule (not membership renewal date)
        next_billing = None

        # First, try to get from the member's current dues schedule
        if hasattr(member, "current_dues_schedule") and member.current_dues_schedule:
            try:
                schedule_doc = frappe.get_doc("Membership Dues Schedule", member.current_dues_schedule)
                next_billing = getattr(schedule_doc, "next_invoice_date", None)
            except Exception as e:
                frappe.log_error(f"Error getting next invoice date from dues schedule: {str(e)}")

        # Fallback: if no schedule or no next_invoice_date, try member's next_invoice_date field
        if not next_billing and hasattr(member, "next_invoice_date"):
            next_billing = member.next_invoice_date

        # Last resort: use membership renewal date (but this should rarely be needed)
        if not next_billing and membership and hasattr(membership, "renewal_date"):
            next_billing = membership.renewal_date

        # Determine current fee amount based on billing frequency
        current_fee_amount = current_fee_info.get("amount", 0)
        if billing_frequency == "Quarterly" and current_fee_amount:
            # If we have a quarterly membership but the override is showing monthly,
            # we need to get the actual quarterly amount from the membership
            if membership:
                membership_doc = frappe.get_doc("Membership", membership.name)
                if getattr(membership_doc, "uses_custom_amount", False):
                    current_fee_amount = getattr(membership_doc, "custom_amount", current_fee_amount)

        return {
            "current_fee": current_fee_amount,
            "billing_frequency": billing_frequency,
            "fee_source": current_fee_info.get("source", "unknown"),
            "outstanding_amount": total_outstanding,
            "outstanding_invoices": outstanding_invoices,
            "next_invoice_date": next_billing,
            "payment_up_to_date": total_outstanding == 0,
            "has_overdue": any(inv["is_overdue"] for inv in outstanding_invoices),
        }

    except Exception as e:
        frappe.log_error(
            f"Error getting payment status for member {member.name}: {str(e)}", "Payment Status Error"
        )
        return None


def get_user_teams(volunteer_name):
    """Get teams where user is a member"""
    teams = frappe.db.sql(
        """
        SELECT DISTINCT
            t.name,
            t.team_name,
            t.team_type,
            t.status,
            tm.role_type,
            tm.role,
            tm.status as member_status
        FROM `tabTeam` t
        INNER JOIN `tabTeam Member` tm ON t.name = tm.parent
        WHERE tm.volunteer = %(volunteer)s
        AND tm.is_active = 1
        AND t.status = 'Active'
        ORDER BY t.team_name
    """,
        {"volunteer": volunteer_name},
        as_dict=True,
    )

    return teams
