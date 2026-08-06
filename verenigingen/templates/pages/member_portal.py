"""
Member Portal Landing Page - TailwindCSS Version
Provides an overview and easy access to all member portal pages
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

from verenigingen.utils.member_utils import (
    get_active_membership_for_member,
    get_current_user_member_name,
    get_member_customer,
    get_volunteer_for_member,
    require_login,
)
from verenigingen.utils.validation_utilities import DateRangeValidator


def get_context(context):
    """Get context for member portal landing page"""
    require_login()

    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Member Portal")

    # Get organization logo from Brand Settings
    from verenigingen.verenigingen.doctype.brand_settings.brand_settings import get_organization_logo

    context.organization_logo = get_organization_logo()

    # Get company name and abbreviation from Verenigingen Settings
    settings = frappe.get_single("Verenigingen Settings")
    if settings.company:
        company_data = frappe.get_value("Company", settings.company, ["company_name", "abbr"], as_dict=True)
        context.company_name = company_data.get("company_name") if company_data else _("Organization")
        context.organization_abbr = company_data.get("abbr") if company_data else None
    else:
        context.company_name = _("Organization")
        context.organization_abbr = None

    # Get member record using standardized utility
    member = get_current_user_member_name()
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
            from verenigingen.utils.email_utils import get_support_contact_email

            context.support_email = get_support_contact_email()
        return context

    context.member = frappe.get_doc("Member", member)
    context.no_member_record = False

    # Get active membership using standardized utility
    membership = get_active_membership_for_member(
        member, ["name", "membership_type", "start_date", "renewal_date", "status"]
    )
    context.membership = membership

    # Get volunteer record if exists using standardized utility
    volunteer = get_volunteer_for_member(member)
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

    # Check if user is a board member of any chapter
    context.is_board_member = is_user_board_member()

    # Get all chapters for member (includes national chapter + member's chapters)
    # Each chapter includes board members and documents
    context.chapters_info = get_all_member_chapters(member)

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
                "icon": "fa-money",
                "description": _("Payment of {0} made").format(
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

    # National chapter link - always show if configured
    try:
        national_chapter = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        if national_chapter:
            actions.append(
                {
                    "title": _("National Chapter"),
                    "route": f"/chapter?chapter={national_chapter}",
                    "class": "btn-secondary",
                    "icon": "fa-globe",
                }
            )
    except Exception as e:
        frappe.log_error(f"Error getting national chapter: {str(e)}")

    # Chapter dashboard - show for any member who belongs to a chapter
    try:
        from verenigingen.utils.member_utils import get_member_chapters

        member_chapters = get_member_chapters(member.name)
        if member_chapters:
            chapter_name = member_chapters[0]
            actions.append(
                {
                    "title": _("Chapter Dashboard"),
                    "route": f"/chapter_dashboard?chapter={chapter_name}",
                    "class": "btn-primary",
                    "icon": "fa-institution",
                }
            )
    except Exception as e:
        frappe.log_error(f"Error checking chapter membership: {str(e)}")

    # Payment dashboard - always visible
    needs_attention = not membership or (membership and membership.status != "Active") or not member.iban
    actions.append(
        {
            "title": _("Payment Dashboard"),
            "route": "/payment_dashboard",
            "class": "btn-primary" if needs_attention else "btn-secondary",
            "icon": "fa-credit-card",
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
    if volunteer and frappe.db.exists("DocType", "Volunteer Expense"):
        try:
            # Check for pending expense claims
            pending_expenses = frappe.db.count(
                "Volunteer Expense",
                filters={
                    "volunteer": volunteer.name,
                    "status": "Draft",
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
                    "title": _("Change Dues Rate"),
                    "route": "/membership_adjustment",
                    "class": "btn-secondary",
                    "icon": "fa-euro",
                }
            )
    except Exception:
        pass  # Ignore if field doesn't exist

    # Document browser - always available
    actions.append(
        {
            "title": _("Documents"),
            "route": "/board/document_browser",
            "class": "btn-secondary",
            "icon": "fa-book",
        }
    )

    # Volunteer dashboard - show if member is a volunteer
    if volunteer:
        actions.append(
            {
                "title": _("Volunteer Dashboard"),
                "route": "/volunteer/dashboard",
                "class": "btn-secondary",
                "icon": "fa-heart",
            }
        )

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
        # Import the coverage enhancement function
        from verenigingen.services.member.financial.member_fee_calculation_service import (
            get_member_fee_calculation_service,
        )
        from verenigingen.utils.member_portal_utils import enhance_outstanding_invoices_with_coverage

        # Get current fee information
        current_fee_info = get_member_fee_calculation_service().get_current_membership_fee(member)

        # Get membership billing frequency from the Membership Type doctype
        billing_frequency = "Monthly"  # Default fallback
        if membership:
            try:
                # Get the billing period from the Membership Type doctype (optional field)
                membership_type_doc = frappe.get_doc("Membership Type", membership.membership_type)
                billing_period = getattr(membership_type_doc, "billing_period", None) or "Monthly"

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
        customer = get_member_customer(member.name)
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
                        "is_overdue": (
                            DateRangeValidator.is_date_in_past(invoice.due_date)
                            if invoice.due_date
                            else False
                        ),
                    }
                )
                total_outstanding += invoice.outstanding_amount

        # Enhance invoices with coverage period information
        outstanding_invoices = enhance_outstanding_invoices_with_coverage(
            outstanding_invoices, billing_frequency
        )

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
            title="Payment Status Error",
            message=f"Error getting payment status for member {member.name}: {str(e)}",
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


def is_user_board_member():
    """Check if current user is a board member of any chapter"""
    from verenigingen.utils.constants import Roles

    user_email = frappe.session.user

    # Admin users have board access (staff excluded — this is a board-membership check)
    if any(role in frappe.get_roles() for role in Roles.ADMIN_PAIR):
        return True

    # Find member record for current user. Member.user first, then Member.email -
    # resolving by email alone misses a member whose login user differs from their
    # contact address, which is a false denial in a permission check.
    from verenigingen.utils.member_utils import get_member_name_for_user

    member = get_member_name_for_user(user_email)
    if not member:
        return False

    # Get volunteer record
    volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
    if not volunteer:
        return False

    # Check if volunteer is on any chapter board
    board_positions = frappe.db.sql(
        """
        SELECT COUNT(*) as count
        FROM `tabChapter Board Member` cbm
        INNER JOIN `tabChapter` c ON c.name = cbm.parent
        WHERE cbm.volunteer = %(volunteer)s
        AND cbm.is_active = 1
        AND cbm.parenttype = 'Chapter'
    """,
        {"volunteer": volunteer},
        as_dict=True,
    )

    return board_positions and board_positions[0].count > 0


def get_member_chapter_info(member_name):
    """Get the member's primary chapter and its board members.

    Falls back to national chapter if member has no chapter assignment.

    Returns:
        dict: {
            'chapter_name': str,
            'chapter_display_name': str,
            'is_national': bool,
            'board_members': list of dicts with volunteer_name, role, from_date, is_current_user
        }
    """
    try:
        # Try to get member's primary chapter first
        member_chapter = frappe.db.get_value(
            "Chapter Member",
            {"member": member_name, "enabled": 1, "status": "Active"},
            "parent",
            order_by="chapter_join_date desc",
        )

        # Fall back to national chapter if no active chapter membership
        if not member_chapter:
            member_chapter = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")

        if not member_chapter:
            return None

        # Check if this is the national chapter
        national_chapter = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        is_national = member_chapter == national_chapter

        # Get chapter doc for board members
        chapter = frappe.get_doc("Chapter", member_chapter)

        # Build board members list
        board_members = []
        current_user_email = frappe.session.user

        for board_member in chapter.board_members:
            if board_member.is_active:
                board_members.append(
                    {
                        "volunteer": board_member.volunteer,
                        "volunteer_name": board_member.volunteer_name,
                        "member_name": board_member.volunteer_name,  # Template uses member_name
                        "role": board_member.chapter_role,
                        "email": board_member.email,
                        "from_date": board_member.from_date,
                        "is_current_user": board_member.email == current_user_email,
                    }
                )

        return {
            "chapter_name": member_chapter,
            "chapter_display_name": chapter.name,
            "is_national": is_national,
            "board_members": board_members,
            "total_count": len(board_members),
        }

    except Exception as e:
        frappe.log_error(f"Error getting member chapter info: {str(e)}")
        return None


def get_all_member_chapters(member_name):
    """Get all chapters the member belongs to, plus the national chapter.

    The national chapter is intentionally visible to ALL members per business rules,
    as it contains organization-wide information (see DocumentPortalService._get_viewable_organizations).

    Returns a list of chapter info dictionaries, each containing board members and documents.

    Returns:
        list: List of dicts, each with:
            - chapter_name: str
            - chapter_display_name: str
            - is_national: bool
            - board_members: list
            - documents: dict (from document_portal_service)
    """
    chapters_info = []
    seen_chapters = set()
    current_user_email = frappe.session.user

    try:
        # Get national chapter first
        national_chapter = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")

        # Get all active chapter memberships for this member
        member_chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": member_name, "enabled": 1, "status": "Active"},
            fields=["parent"],
            order_by="chapter_join_date desc",
        )

        # National chapter is intentionally shown to ALL members (organization-wide info)
        if national_chapter:
            seen_chapters.add(national_chapter)
            _add_chapter_with_documents(
                chapters_info, national_chapter, is_national=True, current_user_email=current_user_email
            )

        # Add member's chapters (excluding national if already added)
        # Note: Members typically belong to 1-2 chapters max, so N+1 query pattern
        # is acceptable here. If usage grows, consider bulk fetching chapters.
        for cm in member_chapters:
            chapter_name = cm.parent
            if chapter_name not in seen_chapters:
                seen_chapters.add(chapter_name)
                _add_chapter_with_documents(
                    chapters_info,
                    chapter_name,
                    is_national=(chapter_name == national_chapter),
                    current_user_email=current_user_email,
                )

        return chapters_info

    except Exception as e:
        frappe.log_error(f"Error getting all member chapters: {str(e)}")
        return []


def _add_chapter_with_documents(chapters_info, chapter_name, is_national, current_user_email):
    """Add chapter with documents to chapters_info list.

    Includes permission check and error handling for document fetching.

    Args:
        chapters_info: List to append chapter data to
        chapter_name: Name of the chapter
        is_national: Whether this is the national chapter
        current_user_email: Current user's email for highlighting
    """
    from verenigingen.services.document.document_portal_service import (
        DocumentPortalService,
        get_organization_documents_for_template,
    )

    try:
        chapter_data = _build_chapter_info(chapter_name, is_national, current_user_email)
        if not chapter_data:
            return

        # Explicit permission check before fetching documents (defense in depth)
        doc_service = DocumentPortalService()
        if doc_service.can_view_organization_documents(
            user=current_user_email,
            organization_type="Chapter",
            organization_name=chapter_name,
        ):
            try:
                chapter_data["documents"] = get_organization_documents_for_template(
                    organization_type="Chapter",
                    organization_name=chapter_name,
                )
            except Exception as e:
                frappe.log_error(f"Failed to load documents for chapter {chapter_name}: {str(e)}")
                # Graceful fallback - show chapter without documents
                chapter_data["documents"] = {
                    "by_type_and_year": {},
                    "total_count": 0,
                    "category_icons": {},
                }
        else:
            # User doesn't have permission to view documents
            chapter_data["documents"] = {
                "by_type_and_year": {},
                "total_count": 0,
                "category_icons": {},
            }

        chapters_info.append(chapter_data)

    except Exception as e:
        frappe.log_error(f"Error processing chapter {chapter_name}: {str(e)}")


def _build_chapter_info(chapter_name, is_national, current_user_email):
    """Build chapter info dict with board members.

    Expects Chapter DocType to have:
    - board_members: Table field (Chapter Board Member child table)

    Args:
        chapter_name: Name of the chapter
        is_national: Whether this is the national chapter
        current_user_email: Current user's email for highlighting

    Returns:
        dict: Chapter info with board members, or None if chapter not found
    """
    try:
        chapter = frappe.get_doc("Chapter", chapter_name)

        # Defensive check for board_members field
        if not hasattr(chapter, "board_members"):
            frappe.log_error(f"Chapter {chapter_name} missing board_members field")
            return None

        # Build board members list
        board_members = []
        for board_member in chapter.board_members:
            if board_member.is_active:
                board_members.append(
                    {
                        "volunteer": board_member.volunteer,
                        "volunteer_name": board_member.volunteer_name,
                        "role": board_member.chapter_role,
                        "email": board_member.email,
                        "from_date": board_member.from_date,
                        "is_current_user": board_member.email == current_user_email,
                    }
                )

        # chapter_name is used for both the identifier and display
        # (Chapter doctype uses name as the display name)
        return {
            "chapter_name": chapter_name,
            "is_national": is_national,
            "board_members": board_members,
            "total_count": len(board_members),
        }

    except Exception as e:
        frappe.log_error(f"Error building chapter info for {chapter_name}: {str(e)}")
        return None
