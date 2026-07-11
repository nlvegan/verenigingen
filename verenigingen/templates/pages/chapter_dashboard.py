"""
Chapter Board Dashboard - Simplified interface for chapter board members
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.query_builder import DocType, Order
from frappe.utils import now_datetime

from verenigingen.templates.pages import serialize_dates
from verenigingen.utils.api_response import api_response_handler
from verenigingen.utils.constants import Roles
from verenigingen.utils.error_handling import cache_with_ttl, validate_user_logged_in
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api

# Business rule constants for overdue categorization
OVERDUE_THRESHOLD_CRITICAL = 90  # Days overdue: critical (90+ days)
OVERDUE_THRESHOLD_SEVERE = 60  # Days overdue: severe (60-89 days)
OVERDUE_THRESHOLD_MODERATE = 30  # Days overdue: moderate (30-59 days)
OVERDUE_APPLICATION_DAYS = 7  # Applications pending > 7 days are considered overdue


def get_context(context):
    """Get context for chapter dashboard page"""

    # Modernized login validation
    validate_user_logged_in("Please login to access the chapter dashboard")

    # Handle both dict and object context
    if hasattr(context, "no_cache"):
        context.no_cache = 1
        context.show_sidebar = False
        context.title = _("Chapter Dashboard")
    else:
        # For direct dictionary access (debugging/testing)
        context["no_cache"] = 1
        context["show_sidebar"] = False
        context["title"] = _("Chapter Dashboard")

    # Get user's board chapters
    user_chapters = get_user_board_chapters()

    if not user_chapters:
        error_msg = _(
            "You must be a board member to access this dashboard. Please contact your chapter administrator."
        )
        user_roles = frappe.get_roles()

        if hasattr(context, "error_message"):
            context.error_message = error_msg
            context.user_roles = user_roles
        else:
            context["error_message"] = error_msg
            context["user_roles"] = user_roles
        return context

    # Handle chapter selection with explicit fallback logic
    selected_chapter = frappe.form_dict.get("chapter")

    if not selected_chapter and user_chapters:
        selected_chapter = user_chapters[0].get("chapter_name")

    # Verify user has access to selected chapter
    if not any(ch.get("chapter_name") == selected_chapter for ch in user_chapters):
        selected_chapter = user_chapters[0].get("chapter_name") if user_chapters else None

    # Get company from Verenigingen Settings
    company = frappe.db.get_single_value("Verenigingen Settings", "company")

    # Set context variables
    if hasattr(context, "selected_chapter"):
        context.selected_chapter = selected_chapter
        context.chapter_name = selected_chapter  # Add for template URL generation
        context.user_chapters = user_chapters
        context.user_board_role = get_user_board_role(selected_chapter)
        context.company = company
    else:
        context["selected_chapter"] = selected_chapter
        context["chapter_name"] = selected_chapter  # Add for template URL generation
        context["user_chapters"] = user_chapters
        context["user_board_role"] = get_user_board_role(selected_chapter)
        context["company"] = company

    # Get dashboard data (use internal function to avoid API wrapper)
    try:
        dashboard_data = _get_chapter_dashboard_data_internal(selected_chapter) if selected_chapter else None
        has_data = dashboard_data is not None
    except Exception as e:
        frappe.log_error(f"Error loading dashboard data: {str(e)}", "Chapter Dashboard")
        dashboard_data = None
        has_data = False

    if hasattr(context, "dashboard_data"):
        context.dashboard_data = dashboard_data
        context.has_data = has_data
        if not has_data:
            context.error_message = _("Error loading dashboard data. Please try again.")
    else:
        context["dashboard_data"] = dashboard_data
        context["has_data"] = has_data
        if not has_data:
            context["error_message"] = _("Error loading dashboard data. Please try again.")

    return context


def get_user_board_chapters() -> List[Dict[str, Any]]:
    """Get chapters where current user is a board member"""
    user_email = frappe.session.user

    # Admin users can see all chapters (published or not)
    admin_roles = [Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN]
    if any(role in frappe.get_roles() for role in admin_roles):
        chapters = frappe.get_all("Chapter", fields=["name", "region"], order_by="name")
        # Transform to match the structure expected by the rest of the code
        return [{"chapter_name": ch["name"], "region": ch.get("region")} for ch in chapters]

    # Find member record for current user
    member = frappe.db.get_value("Member", {"email": user_email}, "name")
    if not member:
        return []

    # Find volunteer record linked to member
    volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
    if not volunteer:
        return []

    # Get chapters where this volunteer is a board member - modernized with Query Builder
    ChapterBoardMember = DocType("Chapter Board Member")
    Chapter = DocType("Chapter")

    try:
        query = (
            frappe.qb.from_(ChapterBoardMember)
            .inner_join(Chapter)
            .on(ChapterBoardMember.parent == Chapter.name)
            .select(
                ChapterBoardMember.parent.as_("chapter_name"),
                Chapter.region,
                ChapterBoardMember.chapter_role,
                ChapterBoardMember.from_date,
                ChapterBoardMember.to_date,
                ChapterBoardMember.is_active,
            )
            .where((ChapterBoardMember.volunteer == volunteer) & (ChapterBoardMember.is_active == 1))
            .orderby(ChapterBoardMember.from_date, order=Order.desc)
            .distinct()
        )

        board_chapters = query.run(as_dict=True)
    except Exception as e:
        frappe.log_error(f"Error fetching board chapters for volunteer {volunteer}: {str(e)}")
        board_chapters = []

    return board_chapters


def get_user_board_role(chapter_name: str) -> Optional[Dict[str, Any]]:
    """Get user's board role for specific chapter"""
    user_email = frappe.session.user

    # Admin users have full access
    admin_roles = [Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN]
    if any(role in frappe.get_roles() for role in admin_roles):
        return {
            "role": "System Administrator",
            "permissions": {
                "can_approve_members": True,
                "can_approve_expenses": True,
                "can_manage_board": True,
                "can_view_finances": True,
                "expense_limit": None,  # No limit for admins
            },
        }

    member = frappe.db.get_value("Member", {"email": user_email}, "name")
    if not member:
        return None

    volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
    if not volunteer:
        return None

    board_role = frappe.db.get_value(
        "Chapter Board Member",
        {"parent": chapter_name, "volunteer": volunteer, "is_active": 1},
        ["chapter_role", "from_date"],
        as_dict=True,
    )

    if board_role:
        # Get role permissions based on chapter role
        role_permissions = get_role_permissions(board_role.chapter_role)
        return {
            "role": board_role.chapter_role,
            "since": board_role.from_date,
            "since_formatted": board_role.from_date.strftime("%B %Y") if board_role.from_date else "",
            "permissions": role_permissions,
        }

    return None


def get_role_permissions(role_name: str) -> Dict[str, Any]:
    """Get permissions based on board role"""
    role_permissions = {
        "Chapter Head": {
            "can_approve_members": True,
            "can_approve_expenses": True,
            "can_manage_board": True,
            "can_view_finances": True,
            "expense_limit": 1000,
        },
        "Treasurer": {
            "can_approve_members": True,
            "can_approve_expenses": True,
            "can_manage_board": False,
            "can_view_finances": True,
            "expense_limit": 500,
        },
        "Secretary": {
            "can_approve_members": True,
            "can_approve_expenses": False,
            "can_manage_board": False,
            "can_view_finances": False,
            "expense_limit": 0,
        },
    }

    # Default permissions for other roles
    default_permissions = {
        "can_approve_members": False,
        "can_approve_expenses": False,
        "can_manage_board": False,
        "can_view_finances": False,
        "expense_limit": 0,
    }

    return role_permissions.get(role_name, default_permissions)


def _get_chapter_dashboard_data_internal(chapter_name: str) -> Dict[str, Any]:
    """Internal function to get dashboard data without API wrapper"""

    if not chapter_name:
        frappe.throw(_("Chapter name is required"))

    # Verify user has access to this chapter
    user_chapters = get_user_board_chapters()
    if not any(ch["chapter_name"] == chapter_name for ch in user_chapters):
        frappe.throw(_("You don't have access to this chapter"))

    dashboard_data = {
        "chapter_info": get_chapter_basic_info(chapter_name),
        "key_metrics": get_chapter_key_metrics(chapter_name),
        "member_overview": get_member_overview(chapter_name),
        "pending_actions": get_pending_actions(chapter_name),
        "financial_summary": get_financial_summary(chapter_name),
        "dues_payment_status": get_dues_payment_status(chapter_name),
        "board_info": get_board_information(chapter_name),
        "board_documents": get_chapter_board_documents(chapter_name),
        "recent_activity": get_recent_activity(chapter_name),
        "last_updated": now_datetime().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Serialize all date/datetime objects for JSON compatibility
    return serialize_dates(dashboard_data)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
@api_response_handler
@cache_with_ttl(ttl=120)  # Cache for 2 minutes - balance between freshness and performance
def get_chapter_dashboard_data(chapter_name: str) -> Dict[str, Any]:
    """Get comprehensive dashboard data for chapter board members (API endpoint)"""
    return _get_chapter_dashboard_data_internal(chapter_name)


def get_chapter_basic_info(chapter_name: str) -> Dict[str, Any]:
    """Get basic chapter information"""
    chapter = frappe.get_doc("Chapter", chapter_name)

    return {
        "name": chapter.name,
        "region": getattr(chapter, "region", ""),
        "head": getattr(chapter, "chapter_head", ""),
        "published": getattr(chapter, "published", 0),
        "introduction": getattr(chapter, "introduction", ""),
        "total_board_members": len([m for m in chapter.board_members if m.is_active]),
    }


def get_chapter_key_metrics(chapter_name: str) -> Dict[str, Any]:
    """Get key metrics for dashboard cards"""

    # Member statistics - modernized with Query Builder and proper aggregation
    try:
        # Get all chapter members first to handle complex conditional aggregation
        members = frappe.get_all(
            "Chapter Member",
            filters={"parent": chapter_name},
            fields=["status", "enabled", "chapter_join_date"],
        )

        # Calculate statistics in Python for better maintainability
        total_members = len(members)
        active_members = sum(1 for m in members if m.status == "Active" and m.enabled == 1)
        pending_members = sum(1 for m in members if m.status == "Pending")
        inactive_members = sum(1 for m in members if m.enabled == 0)
        # Terminated members are those who left (enabled=0)
        terminated_members = inactive_members

        # Calculate new members (last 30 days)
        from frappe.utils import add_days, getdate

        thirty_days_ago = add_days(getdate(), -30)
        new_this_month = sum(
            1 for m in members if m.chapter_join_date and getdate(m.chapter_join_date) >= thirty_days_ago
        )

        member_stats = {
            "total_members": total_members,
            "active_members": active_members,
            "pending_members": pending_members,
            "new_this_month": new_this_month,
            "inactive_members": inactive_members,
            "terminated_members": terminated_members,
        }
    except Exception as e:
        frappe.log_error(f"Error calculating member statistics for {chapter_name}: {str(e)}")
        member_stats = {
            "total_members": 0,
            "active_members": 0,
            "pending_members": 0,
            "new_this_month": 0,
            "inactive_members": 0,
            "terminated_members": 0,
        }

    # Expense statistics (basic for now)
    expense_stats = get_basic_expense_stats(chapter_name)

    return {
        "members": {
            "active": int(member_stats["active_members"] or 0),
            "pending": int(member_stats["pending_members"] or 0),
            "inactive": int(member_stats["inactive_members"] or 0),
            "terminated": int(member_stats["terminated_members"] or 0),
            "new_this_month": int(member_stats["new_this_month"] or 0),
            "total": int(member_stats["total_members"] or 0),
        },
        "expenses": expense_stats,
    }


def get_basic_expense_stats(chapter_name: str) -> Dict[str, Any]:
    """Get basic expense statistics for the chapter"""
    try:
        # Get pending expense amount and count for this chapter
        pending_expenses = frappe.get_all(
            "Expense Claim",
            filters={"custom_chapter": chapter_name, "approval_status": "Draft", "docstatus": 0},
            fields=["total_claimed_amount"],
        )

        pending_amount = sum(exp.total_claimed_amount or 0 for exp in pending_expenses)
        pending_count = len(pending_expenses)

        # Get YTD total for this chapter
        from frappe.utils import getdate

        today = getdate()
        year_start = today.replace(month=1, day=1)

        ytd_expenses = frappe.get_all(
            "Expense Claim",
            filters={
                "custom_chapter": chapter_name,
                "approval_status": "Approved",
                "posting_date": [">=", year_start],
            },
            fields=["total_claimed_amount"],
        )

        ytd_total = sum(exp.total_claimed_amount or 0 for exp in ytd_expenses)

        # Get this month's total
        month_start = today.replace(day=1)

        month_expenses = frappe.get_all(
            "Expense Claim",
            filters={
                "custom_chapter": chapter_name,
                "approval_status": ["in", ["Draft", "Approved"]],
                "posting_date": [">=", month_start],
            },
            fields=["total_claimed_amount"],
        )

        this_month = sum(exp.total_claimed_amount or 0 for exp in month_expenses)

        return {
            "pending_amount": pending_amount,
            "pending_count": pending_count,
            "ytd_total": ytd_total,
            "this_month": this_month,
        }
    except Exception as e:
        frappe.log_error(f"Error calculating expense statistics for {chapter_name}: {str(e)}")
        return {"pending_amount": 0, "pending_count": 0, "ytd_total": 0, "this_month": 0}


def get_member_overview(chapter_name: str) -> Dict[str, Any]:
    """Get member overview with all members"""

    # Get all chapter members - modernized with efficient batch queries
    try:
        # Get all active chapter members (exclude terminated) ordered by name
        recent_chapter_members = frappe.get_all(
            "Chapter Member",
            filters={"parent": chapter_name, "enabled": 1},
            fields=["member", "status", "chapter_join_date", "enabled", "leave_reason"],
            order_by="member asc",
            limit_page_length=0,
        )

        # Batch fetch member names to avoid N+1 queries
        member_ids = [rcm.member for rcm in recent_chapter_members if rcm.member]
        if member_ids:
            members_data = frappe.get_all(
                "Member",
                filters={"name": ["in", member_ids]},
                fields=["name", "full_name"],
                limit_page_length=0,
            )
            member_names = {m.name: m.full_name for m in members_data}
        else:
            member_names = {}

        # Combine the data, skipping orphaned records
        recent_members = []
        for rcm in recent_chapter_members:
            # Skip orphaned Chapter Member records (Member was deleted)
            if rcm.member not in member_names:
                frappe.logger().warning(
                    f"Orphaned Chapter Member record found: {rcm.member} in chapter {chapter_name}. "
                    f"The linked Member record no longer exists."
                )
                continue

            recent_members.append(
                {
                    "member": rcm.member,
                    "full_name": member_names.get(rcm.member, "Unknown"),
                    "status": rcm.status,
                    "chapter_join_date": rcm.chapter_join_date,
                    "enabled": rcm.enabled,
                    "leave_reason": rcm.leave_reason,
                }
            )
    except Exception as e:
        frappe.log_error(f"Error fetching recent members for {chapter_name}: {str(e)}")
        recent_members = []

    # Get pending applications - modernized with efficient ORM queries
    try:
        # Get pending chapter members
        pending_chapter_members = frappe.get_all(
            "Chapter Member",
            filters={"parent": chapter_name, "status": "Pending"},
            fields=["member", "chapter_join_date"],
            order_by="chapter_join_date asc",
            limit_page_length=0,
        )

        # Batch fetch member details
        member_ids = [pcm.member for pcm in pending_chapter_members if pcm.member]
        if member_ids:
            members_data = frappe.get_all(
                "Member",
                filters={"name": ["in", member_ids]},
                fields=["name", "full_name", "application_date"],
                limit_page_length=0,
            )
            member_details = {m.name: m for m in members_data}
        else:
            member_details = {}

        # Calculate days pending and combine data
        from frappe.utils import date_diff, getdate

        pending_applications = []
        for pcm in pending_chapter_members:
            member_data = member_details.get(pcm.member, {})

            # Skip orphaned Chapter Member records (Member was deleted)
            if not member_data:
                frappe.logger().warning(
                    f"Orphaned Chapter Member record found: {pcm.member} in chapter {chapter_name}. "
                    f"The linked Member record no longer exists."
                )
                continue

            # Calculate days pending using frappe utilities
            reference_date = member_data.get("application_date") or pcm.chapter_join_date
            days_pending = 0
            if reference_date:
                days_pending = date_diff(getdate(), getdate(reference_date))

            pending_applications.append(
                {
                    "member": pcm.member,
                    "full_name": member_data.get("full_name", "Unknown"),
                    "chapter_join_date": pcm.chapter_join_date,
                    "application_date": member_data.get("application_date"),
                    "days_pending": days_pending,
                }
            )
    except Exception as e:
        frappe.log_error(f"Error fetching pending applications for {chapter_name}: {str(e)}")
        pending_applications = []

    return {
        "recent_members": recent_members,  # Return all members (no limit)
        "pending_applications": pending_applications,
        "total_pending": len(pending_applications),
    }


def get_pending_actions(chapter_name: str) -> Dict[str, Any]:
    """Get items requiring board attention"""

    # Get pending membership applications
    pending_apps = get_member_overview(chapter_name)["pending_applications"]

    # Mark overdue applications (more than threshold days)
    for app in pending_apps:
        app["is_overdue"] = (app.get("days_pending", 0) or 0) > OVERDUE_APPLICATION_DAYS

    # Get pending expense approvals awaiting board action
    pending_expenses = get_pending_expense_approvals(chapter_name)

    # Get board tasks (placeholder)
    board_tasks = []  # Will be implemented with task management

    return {
        "membership_applications": pending_apps,
        "expense_approvals": pending_expenses,
        "board_tasks": board_tasks,
        "total_pending": len(pending_apps) + len(pending_expenses) + len(board_tasks),
    }


def get_pending_expense_approvals(chapter_name: str) -> List[Dict[str, Any]]:
    """Get expense claims awaiting board approval for this chapter.

    Uses the same "pending" filter as get_basic_expense_stats (unsubmitted
    Draft claims), but returns actionable rows for the dashboard's "Requires
    Your Attention" list instead of just aggregate totals.
    """
    try:
        return frappe.get_all(
            "Expense Claim",
            filters={"custom_chapter": chapter_name, "approval_status": "Draft", "docstatus": 0},
            fields=[
                "name",
                "employee_name",
                "custom_volunteer",
                "total_claimed_amount",
                "posting_date",
            ],
            order_by="posting_date asc",
        )
    except Exception as e:
        frappe.log_error(f"Error fetching pending expenses for {chapter_name}: {str(e)}")
        return []


def get_financial_summary(chapter_name: str) -> Dict[str, Any]:
    """Get financial summary for the chapter"""
    try:
        from frappe.utils import getdate

        today = getdate()
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)

        # This month's expenses
        submitted_this_month = frappe.get_all(
            "Expense Claim",
            filters={
                "custom_chapter": chapter_name,
                "approval_status": "Draft",
                "docstatus": 0,
                "posting_date": [">=", month_start],
            },
            fields=["total_claimed_amount"],
        )

        approved_this_month = frappe.get_all(
            "Expense Claim",
            filters={
                "custom_chapter": chapter_name,
                "approval_status": "Approved",
                "posting_date": [">=", month_start],
            },
            fields=["total_claimed_amount"],
        )

        pending_this_month = frappe.get_all(
            "Expense Claim",
            filters={
                "custom_chapter": chapter_name,
                "approval_status": "Draft",
                "docstatus": 0,
                "posting_date": [">=", month_start],
            },
            fields=["total_claimed_amount"],
        )

        # YTD expenses
        ytd_expenses = frappe.get_all(
            "Expense Claim",
            filters={
                "custom_chapter": chapter_name,
                "approval_status": "Approved",
                "posting_date": [">=", year_start],
            },
            fields=["total_claimed_amount"],
        )

        expenses_submitted = sum(exp.total_claimed_amount or 0 for exp in submitted_this_month)
        expenses_approved = sum(exp.total_claimed_amount or 0 for exp in approved_this_month)
        pending_approval = sum(exp.total_claimed_amount or 0 for exp in pending_this_month)

        ytd_total = sum(exp.total_claimed_amount or 0 for exp in ytd_expenses)
        ytd_count = len(ytd_expenses)
        average_claim = ytd_total / ytd_count if ytd_count > 0 else 0

        # Calculate YTD dues income for this chapter (using Chapter Dues Split logic)
        from verenigingen.verenigingen.domain.chapter_dues import DuesAllocationService

        # Validate custom field exists before querying (per CLAUDE.md guidelines)
        ytd_dues_gross = 0
        ytd_dues_chapter = 0

        if frappe.db.has_column("Sales Invoice", "custom_member_chapter"):
            # Get company from Verenigingen Settings to exclude test company invoices
            verenigingen_settings = frappe.get_single("Verenigingen Settings")
            company = verenigingen_settings.company

            ytd_dues_result = frappe.db.sql(
                """
                SELECT SUM(si.grand_total) as total_amount
                FROM `tabSales Invoice` si
                WHERE si.docstatus = 1
                AND si.custom_member_chapter = %(chapter)s
                AND si.posting_date >= %(year_start)s
                AND si.company = %(company)s
                """,
                {"chapter": chapter_name, "year_start": year_start, "company": company},
                as_dict=True,
            )

            # Safely extract dues total with proper null checks
            if ytd_dues_result and len(ytd_dues_result) > 0:
                ytd_dues_gross = ytd_dues_result[0].get("total_amount") or 0

            # Calculate chapter split using DuesAllocationService
            allocation_service = DuesAllocationService()
            if ytd_dues_gross > 0:
                allocation = allocation_service.calculate_allocation(ytd_dues_gross, chapter_name)
                ytd_dues_chapter = float(allocation.chapter_amount)
        else:
            frappe.logger().warning(
                f"Custom field 'custom_member_chapter' not found on Sales Invoice. "
                f"Dues income calculation skipped for chapter {chapter_name}"
            )

        # Calculate YTD Purchase Invoice totals (vendor bills/expenses)
        ytd_purchase_invoices = frappe.db.sql(
            """
            SELECT SUM(pi.grand_total) as total_amount
            FROM `tabPurchase Invoice` pi
            WHERE pi.docstatus = 1
            AND pi.posting_date >= %(year_start)s
            AND (pi.cost_center LIKE %(chapter_pattern)s OR pi.remarks LIKE %(chapter_pattern)s)
            """,
            {"year_start": year_start, "chapter_pattern": f"%{chapter_name}%"},
            as_dict=True,
        )

        # Safely extract purchase invoice total
        ytd_purchase_total = 0
        if ytd_purchase_invoices and len(ytd_purchase_invoices) > 0:
            ytd_purchase_total = ytd_purchase_invoices[0].get("total_amount") or 0

        return {
            "this_month": {
                "expenses_submitted": expenses_submitted,
                "expenses_approved": expenses_approved,
                "pending_approval": pending_approval,
                "claims_count": len(submitted_this_month) + len(approved_this_month),
            },
            "ytd": {
                "total_expenses": ytd_total,
                "average_claim": average_claim,
                "total_claims": ytd_count,
                "purchase_invoices": ytd_purchase_total,
            },
            "dues_income": {"ytd_gross": ytd_dues_gross, "ytd_chapter": ytd_dues_chapter},
        }
    except Exception as e:
        frappe.log_error(f"Error calculating financial summary for {chapter_name}: {str(e)}")
        return {
            "this_month": {
                "expenses_submitted": 0,
                "expenses_approved": 0,
                "pending_approval": 0,
                "claims_count": 0,
            },
            "ytd": {"total_expenses": 0, "average_claim": 0, "total_claims": 0, "purchase_invoices": 0},
            "dues_income": {"ytd_gross": 0, "ytd_chapter": 0},
        }


def get_members_without_payment_info_count(chapter_name: str) -> int:
    """Count members in chapter without valid payment information"""
    try:
        # Get chapter members
        chapter_members = frappe.get_all(
            "Chapter Member",
            filters={"parent": chapter_name, "enabled": 1, "status": "Active"},
            pluck="member",
        )

        if not chapter_members:
            return 0

        # Query to find members without valid payment info
        result = frappe.db.sql(
            """
            SELECT COUNT(DISTINCT m.name) as count
            FROM `tabMember` m
            WHERE m.name IN %(member_names)s
            AND m.status IN ('Active', 'Pending')
            AND NOT (
                -- Has Mollie with active subscription
                (m.mollie_customer_id IS NOT NULL
                 AND m.mollie_subscription_id IS NOT NULL
                 AND m.subscription_status = 'active')
                OR
                -- Has active SEPA mandate
                EXISTS (
                    SELECT 1 FROM `tabSEPA Mandate` sm
                    WHERE sm.member = m.name
                    AND sm.status = 'Active'
                    AND sm.is_active = 1
                )
                OR
                -- Has complete bank transfer setup
                (m.payment_method = 'Bank Transfer'
                 AND m.iban IS NOT NULL
                 AND m.iban != ''
                 AND m.bank_account_name IS NOT NULL
                 AND m.bank_account_name != '')
            )
            """,
            {"member_names": chapter_members},
            as_dict=True,
        )

        return result[0].count if result else 0

    except Exception as e:
        frappe.log_error(
            f"Error counting members without payment info for {chapter_name}: {str(e)}",
            "Chapter Dashboard Payment Info Count",
        )
        return 0


def get_dues_payment_status(chapter_name: str) -> Dict[str, Any]:
    """Get membership dues payment status for chapter members"""
    try:
        from frappe.utils import getdate

        today = getdate()

        # Get company from Verenigingen Settings for consistent filtering
        company = frappe.db.get_single_value("Verenigingen Settings", "company")

        # Get all chapter members with their payment status, membership, and dues schedule info
        # Note: Sales Invoices link via 'member' field (custom field on Sales Invoice)
        # We use custom_coverage_end_date IS NOT NULL as indicator for membership invoices
        # Company filter ensures we only count invoices from the configured company
        result = frappe.db.sql(
            """
            SELECT
                cm.member,
                m.full_name,
                m.status as member_status,
                MAX(si.custom_coverage_end_date) as latest_coverage_end,
                MIN(CASE WHEN si.status = 'Overdue' AND si.custom_coverage_end_date IS NOT NULL
                    THEN si.due_date END) as earliest_overdue_date,
                SUM(CASE WHEN si.status = 'Overdue' AND si.custom_coverage_end_date IS NOT NULL
                    THEN si.outstanding_amount ELSE 0 END) as overdue_amount,
                SUM(CASE WHEN si.status = 'Unpaid' AND si.custom_coverage_end_date IS NOT NULL
                    THEN si.outstanding_amount ELSE 0 END) as unpaid_amount,
                COUNT(CASE WHEN si.status = 'Overdue' AND si.custom_coverage_end_date IS NOT NULL
                    THEN 1 END) as overdue_invoice_count,
                COUNT(CASE WHEN si.status = 'Unpaid' AND si.custom_coverage_end_date IS NOT NULL
                    THEN 1 END) as unpaid_invoice_count,
                COUNT(CASE WHEN si.custom_coverage_end_date IS NOT NULL THEN 1 END) as total_invoices,
                COUNT(DISTINCT CASE WHEN mem.status = 'Active' AND mem.docstatus = 1
                    THEN mem.name END) as active_memberships,
                COUNT(DISTINCT CASE WHEN mds.status = 'Active'
                    THEN mds.name END) as active_schedules
            FROM `tabChapter Member` cm
            INNER JOIN `tabMember` m ON m.name = cm.member
            LEFT JOIN `tabSales Invoice` si ON si.member = cm.member AND si.docstatus = 1
                AND (%(company)s IS NULL OR si.company = %(company)s)
            LEFT JOIN `tabMembership` mem ON mem.member = cm.member
            LEFT JOIN `tabMembership Dues Schedule` mds ON mds.member = cm.member
            WHERE cm.parent = %(chapter)s AND cm.enabled = 1
            GROUP BY cm.member, m.full_name, m.status
        """,
            {"chapter": chapter_name, "company": company},
            as_dict=True,
        )

        # Categorize members
        up_to_date = 0
        no_active_membership = 0  # Active chapter members without active membership+schedule
        awaiting_invoice = 0  # Members with active membership/schedule but no invoices yet
        unpaid = 0
        overdue = 0
        lapsed = 0  # Members with expired coverage and no unpaid/overdue invoices
        overdue_under_30_days = 0
        overdue_30_days = 0
        overdue_60_days = 0
        overdue_90_plus_days = 0
        total_overdue_amount = 0
        total_unpaid_amount = 0

        for member in result:
            # Priority order for categorization:
            # 1. Active member without membership infrastructure (needs attention)
            if (
                member.member_status == "Active"
                and member.active_memberships == 0
                and member.active_schedules == 0
            ):
                no_active_membership += 1
            # 2. Has overdue invoices (critical)
            elif member.overdue_invoice_count > 0:
                overdue += 1
                total_overdue_amount += member.overdue_amount or 0

                # Calculate overdue severity based on actual due date (not coverage date)
                if member.earliest_overdue_date:
                    days_overdue = (today - member.earliest_overdue_date).days
                    if days_overdue > OVERDUE_THRESHOLD_CRITICAL:
                        overdue_90_plus_days += 1
                    elif days_overdue > OVERDUE_THRESHOLD_SEVERE:
                        overdue_60_days += 1
                    elif days_overdue > OVERDUE_THRESHOLD_MODERATE:
                        overdue_30_days += 1
                    else:
                        overdue_under_30_days += 1
            # 3. Has unpaid invoices (important)
            elif member.unpaid_invoice_count > 0:
                unpaid += 1
                total_unpaid_amount += member.unpaid_amount or 0
            # 4. Coverage is current (good standing)
            elif member.latest_coverage_end and member.latest_coverage_end >= today:
                up_to_date += 1
            # 5. Has invoices but coverage expired (lapsed)
            elif member.total_invoices > 0:
                lapsed += 1
            # 6. Has membership infrastructure but no invoices generated yet
            elif member.active_memberships > 0 or member.active_schedules > 0:
                awaiting_invoice += 1
            # 7. Everything else (terminated, no invoices, no membership, etc.)
            # These are not actionable from the dues perspective
            else:
                # Debug logging disabled - uncomment if needed for troubleshooting
                # frappe.log_warning(
                #     f"Uncategorized member: {member.full_name}, "
                #     f"Status: {member.member_status}, "
                #     f"Total invoices: {member.total_invoices}, "
                #     f"Active memberships: {member.active_memberships}, "
                #     f"Active schedules: {member.active_schedules}",
                #     "Chapter Dashboard - Uncategorized Member",
                # )
                pass

        # Get count of members without payment info
        missing_payment_info_count = get_members_without_payment_info_count(chapter_name)

        return {
            "total_members": len(result),
            "up_to_date": up_to_date,
            "no_active_membership": no_active_membership,
            "awaiting_invoice": awaiting_invoice,
            "unpaid": unpaid,
            "unpaid_amount": total_unpaid_amount,
            "overdue": overdue,
            "lapsed": lapsed,
            "missing_payment_info": missing_payment_info_count,
            "overdue_breakdown": {
                "overdue_under_30_days": overdue_under_30_days,
                "overdue_30_days": overdue_30_days,
                "overdue_60_days": overdue_60_days,
                "overdue_90_plus_days": overdue_90_plus_days,
            },
            "total_overdue_amount": total_overdue_amount,
            # Combined totals for display (includes both unpaid and overdue)
            "all_outstanding": unpaid + overdue,
            "all_outstanding_amount": total_unpaid_amount + total_overdue_amount,
        }
    except Exception as e:
        frappe.log_error(f"Error calculating dues payment status for {chapter_name}: {str(e)}")
        return {
            "total_members": 0,
            "up_to_date": 0,
            "no_active_membership": 0,
            "awaiting_invoice": 0,
            "unpaid": 0,
            "unpaid_amount": 0,
            "overdue": 0,
            "lapsed": 0,
            "missing_payment_info": 0,
            "overdue_breakdown": {
                "overdue_under_30_days": 0,
                "overdue_30_days": 0,
                "overdue_60_days": 0,
                "overdue_90_plus_days": 0,
            },
            "total_overdue_amount": 0,
            "all_outstanding": 0,
            "all_outstanding_amount": 0,
        }


def get_board_information(chapter_name: str) -> Dict[str, Any]:
    """Get board member information"""
    chapter = frappe.get_doc("Chapter", chapter_name)

    board_members = []
    for board_member in chapter.board_members:
        if board_member.is_active:
            member_info = {
                "volunteer": board_member.volunteer,
                "volunteer_name": board_member.volunteer_name,
                "role": board_member.chapter_role,
                "email": board_member.email,
                "from_date": board_member.from_date,
                "to_date": board_member.to_date,
                "is_current_user": False,
            }

            # Check if this is the current user
            current_user_email = frappe.session.user
            if board_member.email == current_user_email:
                member_info["is_current_user"] = True

            board_members.append(member_info)

    return {
        "members": board_members,
        "total_count": len(board_members),
        "next_meeting": None,  # Placeholder for meeting management
    }


def get_available_document_categories() -> Dict[str, str]:
    """Get all available document categories from Verenigingen Settings."""
    from verenigingen.utils.document_categories import get_category_icons

    return get_category_icons()


def get_chapter_board_documents(chapter_name: str) -> Dict[str, Any]:
    """Get board documents from Organization Document doctype, organized by type and year.

    This is a thin wrapper around the service layer function for backward compatibility.
    """
    from verenigingen.services.document.document_portal_service import get_organization_documents_for_template

    return get_organization_documents_for_template(
        organization_type="Chapter",
        organization_name=chapter_name,
    )


def get_recent_activity(chapter_name: str) -> List[Dict[str, Any]]:
    """Get recent chapter activities"""
    activities = []

    # Get member join/leave activities - use actual chapter_join_date, not comment creation time
    try:
        from frappe.utils import add_days, getdate

        # Look back 2 months (60 days) for recent activity
        sixty_days_ago = add_days(getdate(), -60)

        # Get recent chapter member changes (joins, leaves, applications)
        # Get both recent joins AND recent terminations, including member status
        recent_chapter_activities = frappe.db.sql(
            """
            SELECT cm.member, cm.chapter_join_date, cm.status, cm.enabled,
                   cm.leave_reason, cm.modified, m.status as member_status
            FROM `tabChapter Member` cm
            LEFT JOIN `tabMember` m ON m.name = cm.member
            WHERE cm.parent = %(chapter)s
            AND (
                cm.chapter_join_date >= %(sixty_days_ago)s
                OR (cm.enabled = 0 AND cm.modified >= %(sixty_days_ago)s)
            )
            ORDER BY COALESCE(cm.chapter_join_date, cm.modified) DESC
            LIMIT 10
            """,
            {"chapter": chapter_name, "sixty_days_ago": sixty_days_ago},
            as_dict=True,
        )

        # Batch fetch member names
        member_ids = [rcj.member for rcj in recent_chapter_activities if rcj.member]
        if member_ids:
            members_data = frappe.get_all(
                "Member",
                filters={"name": ["in", member_ids]},
                fields=["name", "full_name"],
                limit_page_length=0,
            )
            member_names = {m.name: m.full_name for m in members_data}
        else:
            member_names = {}

        # Combine the data and create activity descriptions
        recent_joins = []
        for rcj in recent_chapter_activities:
            full_name = member_names.get(rcj.member, "Unknown")

            # Determine activity type and description
            if rcj.enabled == 0:
                # Member left the chapter - check if they quit the org or just moved chapters
                member_status = rcj.get("member_status")
                if member_status in ("Quit", "Suspended", "Banned", "Deceased"):
                    # Member quit/left the organization entirely
                    activity_desc = f"{full_name} quit the organization"
                    if rcj.leave_reason:
                        activity_desc += f" ({rcj.leave_reason})"
                    activity_type = "member_quit"
                else:
                    # Member likely moved to another chapter
                    activity_desc = f"{full_name} left the chapter"
                    if rcj.leave_reason:
                        activity_desc += f" ({rcj.leave_reason})"
                    activity_type = "member_leave"
            elif rcj.status == "Pending":
                activity_desc = f"{full_name} applied to join (pending approval)"
                activity_type = "member_application"
            else:
                activity_desc = f"{full_name} joined the chapter"
                activity_type = "member_join"

            # Use chapter_join_date if available, otherwise fall back to modified
            # This ensures we show the actual join date, not when the record was created/updated
            timestamp = rcj.chapter_join_date if rcj.chapter_join_date else rcj.modified

            recent_joins.append(
                {
                    "member": rcj.member,
                    "full_name": full_name,
                    "chapter_join_date": rcj.chapter_join_date,
                    "timestamp": timestamp,
                    "status": rcj.status,
                    "enabled": rcj.enabled,
                    "activity_type": activity_type,
                    "activity_desc": activity_desc,
                }
            )
    except Exception as e:
        frappe.log_error(f"Error fetching recent member activities for {chapter_name}: {str(e)}")
        recent_joins = []

    for join in recent_joins:
        activities.append(
            {
                "type": join.get("activity_type", "member_join"),
                "description": join.get("activity_desc", f"{join['full_name']} joined the chapter"),
                "timestamp": join.get("timestamp"),
                "user": "System",
                "member": join.get("member"),
                "full_name": join.get("full_name"),
            }
        )

    # Sort activities by timestamp (handle both datetime and date objects)
    def get_sort_key(activity):
        timestamp = activity["timestamp"]
        if isinstance(timestamp, str):
            return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        elif hasattr(timestamp, "date"):
            return timestamp  # datetime object
        else:
            return datetime.combine(timestamp, datetime.min.time())  # date object

    activities.sort(key=get_sort_key, reverse=True)

    return activities[:10]  # Return top 10 recent activities
