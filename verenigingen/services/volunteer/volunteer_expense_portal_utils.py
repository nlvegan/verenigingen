"""
Volunteer Expense Portal Utilities

Centralized utility functions for volunteer expense portals.
Consolidates shared logic from:
- templates/pages/volunteer/expenses.py
- templates/pages/volunteer-portal/expense_claim_new.py

This module eliminates ~1000 lines of duplicate code by providing a single
source of truth for expense portal business logic.

Author: Verenigingen Development Team
License: MIT
"""

from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import flt, formatdate, today

from verenigingen.utils.member_utils import get_volunteer_for_current_user
from verenigingen.utils.validation_utilities import DocumentExistenceValidator

# =============================================================================
# Statistics Functions
# =============================================================================


def get_empty_statistics() -> dict:
    """Return empty statistics dictionary for error cases or permission denied scenarios.

    Returns:
        dict: Empty statistics with zero values for all metrics
    """
    return {
        "total_submitted": 0,
        "total_approved": 0,
        "pending_amount": 0,
        "pending_count": 0,
        "approved_count": 0,
        "total_count": 0,
    }


def get_volunteer_expense_statistics(volunteer_name: str) -> tuple[dict, str]:
    """Get expense statistics for a volunteer using optimized single query.

    Args:
        volunteer_name: Volunteer record name

    Returns:
        Tuple of (statistics dict, debug message string)
    """
    try:
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
        if not volunteer_doc.employee_id:
            return get_empty_statistics(), "No employee_id found for volunteer"

        # Single optimized query for statistics
        stats_result = frappe.db.sql(
            """
            SELECT
                COUNT(*) as total_count,
                COALESCE(SUM(total_claimed_amount), 0) as total_submitted,
                COALESCE(SUM(CASE
                    WHEN status IN ('Paid', 'Reimbursed') OR approval_status = 'Approved'
                    THEN COALESCE(total_sanctioned_amount, total_claimed_amount)
                    ELSE 0
                END), 0) as total_approved,
                COUNT(CASE
                    WHEN status IN ('Paid', 'Reimbursed') OR approval_status = 'Approved'
                    THEN 1
                END) as approved_count
            FROM `tabExpense Claim`
            WHERE employee = %s AND docstatus != 2
        """,
            [volunteer_doc.employee_id],
            as_dict=True,
        )[0]

        total_submitted = flt(stats_result.total_submitted)
        total_approved = flt(stats_result.total_approved)
        approved_count = int(stats_result.approved_count or 0)
        total_count = int(stats_result.total_count or 0)
        pending_count = total_count - approved_count

        debug_msg = (
            f"Optimized query for employee {volunteer_doc.employee_id}: "
            f"{total_count} claims, {total_submitted} submitted, {total_approved} approved"
        )

        return {
            "total_submitted": total_submitted,
            "total_approved": total_approved,
            "pending_amount": total_submitted - total_approved,
            "pending_count": pending_count,
            "approved_count": approved_count,
            "total_count": total_count,
        }, debug_msg

    except frappe.DoesNotExistError:
        return get_empty_statistics(), f"Volunteer {volunteer_name} not found"
    except frappe.PermissionError as e:
        return get_empty_statistics(), f"Permission denied accessing expense data: {str(e)}"
    except Exception as e:
        frappe.log_error(
            f"Error calculating expense statistics for {volunteer_name}: {str(e)}",
            "Expense Statistics Error",
        )
        return get_empty_statistics(), f"Error calculating statistics: {str(e)}"


# =============================================================================
# Organization Functions
# =============================================================================


def get_volunteer_organizations(volunteer_name: str) -> dict:
    """Get chapters and teams the volunteer belongs to.

    Args:
        volunteer_name: Volunteer record name

    Returns:
        dict: {
            "chapters": [{"name": str, "chapter_name": str, "city": str}, ...],
            "teams": [{"name": str, "team_name": str}, ...]
        }
    """
    organizations = {"chapters": [], "teams": []}

    # Check if volunteer exists
    if not DocumentExistenceValidator.check_document_exists("Volunteer", volunteer_name):
        return organizations

    # Get chapters through member relationship
    volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
    if hasattr(volunteer_doc, "member") and volunteer_doc.member:
        # Get chapters where this member is active
        chapter_members = frappe.get_all(
            "Chapter Member",
            filters={"member": volunteer_doc.member, "enabled": 1},
            fields=["parent"],
        )

        for cm in chapter_members:
            chapter_data = frappe.db.get_value("Chapter", cm.parent, ["name"], as_dict=True)
            if chapter_data:
                # Standardize chapter data structure (consistent with dashboard.py)
                chapter_info = {
                    "name": chapter_data["name"],
                    "chapter_name": chapter_data["name"],  # Chapter name is stored in the 'name' field
                    "city": "",  # Chapters don't have city in this system
                }
                organizations["chapters"].append(chapter_info)
                frappe.logger().debug(f"Added chapter to organizations: {chapter_info}")

    # Get teams where volunteer is active
    team_members = frappe.get_all(
        "Team Member",
        filters={"volunteer": volunteer_name, "status": "Active"},
        fields=["parent"],
    )

    for tm in team_members:
        team_info = frappe.db.get_value("Team", tm.parent, ["name"], as_dict=True)
        if team_info:
            # Add team_name field with same value as name for consistency
            team_info["team_name"] = team_info["name"]
            organizations["teams"].append(team_info)

    return organizations


def get_expense_categories() -> list:
    """Get available expense categories.

    Returns:
        list: List of expense category dicts with name, category_name, description
    """
    return frappe.get_all(
        "Expense Category",
        filters={"is_active": 1},
        fields=["name", "category_name", "description"],
        order_by="category_name",
    )


def get_approval_thresholds() -> dict:
    """Get approval thresholds for UI guidance.

    Returns:
        dict: {
            "basic_limit": float,
            "financial_limit": float,
            "admin_limit": float
        }
    """
    return {"basic_limit": 100.0, "financial_limit": 500.0, "admin_limit": 999999.0}


def get_national_chapter() -> Optional[dict]:
    """Get national chapter info from settings.

    Returns:
        dict or None: {"name": str, "chapter_name": str} or None if not configured
    """
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if settings and getattr(settings, "national_board_chapter", None):
            chapter_info = frappe.db.get_value(
                "Chapter", settings.national_board_chapter, ["name"], as_dict=True
            )
            if chapter_info:
                return {
                    "name": chapter_info.name,
                    "chapter_name": chapter_info.name,  # Use name as chapter_name since that field doesn't exist
                }
    except Exception as e:
        frappe.log_error(f"Error getting national chapter: {str(e)}")
        frappe.logger().error(f"National chapter error details: {str(e)}")
        import traceback

        frappe.logger().error(f"National chapter traceback: {traceback.format_exc()}")

    return None


# =============================================================================
# Expense Data Functions
# =============================================================================


def get_volunteer_expenses_from_claims(volunteer_name: str, limit: Optional[int] = None) -> list:
    """Get volunteer's expenses directly from HRMS Expense Claims.

    Args:
        volunteer_name: Volunteer record name
        limit: Maximum number of expenses to return (optional)

    Returns:
        list: List of expense dicts with formatted data for display
    """
    try:
        # Get volunteer's employee_id
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
        if not volunteer_doc.employee_id:
            return []

        # Get expense claims for this employee
        expense_claims = frappe.get_all(
            "Expense Claim",
            filters={"employee": volunteer_doc.employee_id, "docstatus": ["!=", 2]},  # Exclude cancelled
            fields=[
                "name",
                "total_claimed_amount",
                "total_sanctioned_amount",
                "status",
                "approval_status",
                "posting_date",
                "remark",
                "custom_organization_type",
                "custom_chapter",
                "custom_team",
                "custom_expense_category",
            ],
            order_by="posting_date desc",
            limit=limit,
        )

        expenses = []
        for claim in expense_claims:
            # Get first expense detail for description
            expense_details = frappe.get_all(
                "Expense Claim Detail",
                filters={"parent": claim.name},
                fields=["description", "expense_type", "amount"],
                order_by="idx",
                limit=1,
            )

            description = expense_details[0].description if expense_details else f"Expense Claim {claim.name}"

            # Get organization name
            org_name = claim.custom_chapter or claim.custom_team or "National"
            org_type = claim.custom_organization_type or "Unknown"

            # Map HRMS status to volunteer portal status
            status = map_erpnext_status_to_volunteer_status(claim.status, claim.approval_status)

            expense = {
                "name": claim.name,
                "expense_claim_id": claim.name,
                "description": description,
                "amount": claim.total_claimed_amount,
                "currency": "EUR",
                "expense_date": claim.posting_date,
                "status": status,
                "organization_type": org_type,
                "organization_name": org_name,
                "category": claim.custom_expense_category,
                "category_name": (
                    frappe.db.get_value("Expense Category", claim.custom_expense_category, "category_name")
                    if claim.custom_expense_category
                    else "Uncategorized"
                ),
                "formatted_date": formatdate(claim.posting_date),
                "status_class": get_status_class(status),
            }
            expenses.append(expense)

        return expenses

    except frappe.DoesNotExistError:
        frappe.log_error(f"Volunteer {volunteer_name} not found", "Volunteer Not Found")
        return []
    except frappe.PermissionError as e:
        frappe.log_error(
            f"Permission denied accessing expenses for {volunteer_name}: {str(e)}",
            "Expense Access Denied",
        )
        return []
    except Exception as e:
        frappe.log_error(
            f"Error getting volunteer expenses from claims for {volunteer_name}: {str(e)}",
            "Volunteer Expenses from Claims Error",
        )
        return []


def get_status_class(status: str) -> str:
    """Get CSS class for expense status.

    Args:
        status: Expense status string

    Returns:
        str: CSS badge class name
    """
    status_classes = {
        "Draft": "badge-secondary",
        "Submitted": "badge-warning",
        "Approved": "badge-success",
        "Rejected": "badge-danger",
        "Reimbursed": "badge-primary",
    }
    return status_classes.get(status, "badge-secondary")


def map_erpnext_status_to_volunteer_status(status: str, approval_status: Optional[str] = None) -> str:
    """Map ERPNext Expense Claim status to volunteer expense status.

    Args:
        status: ERPNext Expense Claim status
        approval_status: ERPNext approval_status field (optional)

    Returns:
        str: Volunteer portal status string
    """
    if status == "Draft":
        return "Draft"
    elif status == "Submitted":
        if approval_status == "Approved":
            return "Approved"
        elif approval_status == "Rejected":
            return "Rejected"
        else:
            return "Submitted"
    elif status == "Paid":
        return "Reimbursed"
    elif status == "Cancelled":
        return "Rejected"
    else:
        return status  # Fallback to original status


# =============================================================================
# Validation Functions
# =============================================================================


def validate_volunteer_organization_access(
    volunteer_name: str, organization_type: str, organization_name: str
) -> bool:
    """Enhanced validation for volunteer access to organizations.

    Supports direct chapter membership AND indirect access via team membership.

    Args:
        volunteer_name: Volunteer record name
        organization_type: 'Chapter', 'Team', or 'National'
        organization_name: Name of the organization

    Returns:
        bool: True if volunteer has access
    """
    try:
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)

        if organization_type == "Chapter":
            # Direct chapter membership check. Chapter Member is keyed on the
            # MEMBER (it has no `volunteer` column), so resolve the volunteer's
            # member first -- mirroring _validate_chapter_access in
            # expense_submission_service. Filtering on a non-existent `volunteer`
            # column silently matched nothing, denying genuine chapter members.
            member = getattr(volunteer_doc, "member", None)
            direct_membership = (
                frappe.db.exists("Chapter Member", {"parent": organization_name, "member": member})
                if member
                else None
            )

            if direct_membership:
                return True

            # Indirect access via team membership
            # Get teams where volunteer is a member and team's chapter matches
            team_memberships = frappe.get_all(
                "Team Member", filters={"volunteer": volunteer_name}, fields=["parent"]
            )

            for membership in team_memberships:
                team_doc = frappe.get_doc("Team", membership.parent)
                if hasattr(team_doc, "chapter") and team_doc.chapter == organization_name:
                    frappe.logger().info(
                        f"Volunteer {volunteer_name} has access to chapter {organization_name} "
                        f"via team {team_doc.name}"
                    )
                    return True

            return False

        elif organization_type == "Team":
            # Direct team membership check
            team_membership = frappe.db.exists(
                "Team Member", {"parent": organization_name, "volunteer": volunteer_name}
            )
            return bool(team_membership)

        elif organization_type == "National":
            # All volunteers have access to national expenses
            return True

        return False

    except Exception as e:
        frappe.log_error(
            f"Error validating volunteer organization access: {str(e)}",
            "Access Validation Error",
        )
        # In case of error, allow access to prevent blocking legitimate requests
        return True


def is_policy_covered_expense(category: str) -> bool:
    """Check if expense category is covered by organizational policy for all volunteers.

    Args:
        category: Expense category name

    Returns:
        bool: True if covered by policy
    """
    try:
        # Get expense category details
        category_doc = frappe.get_doc("Expense Category", category)

        # Policy-covered categories (configurable via category settings)
        if hasattr(category_doc, "policy_covered") and category_doc.policy_covered:
            return True

        # Fallback: Check by category name for common policy-covered expenses
        policy_covered_categories = [
            "Travel",  # Travel expenses
            "Materials",  # Materials for campaigns/events
            "Office Supplies",  # Basic office supplies
            "events",  # Event materials
        ]

        category_name = getattr(category_doc, "category_name", category).lower()
        return any(policy_cat.lower() in category_name for policy_cat in policy_covered_categories)

    except Exception as e:
        frappe.log_error(
            f"Error checking policy coverage for category {category}: {str(e)}",
            "Policy Coverage Check",
        )
        # Default to requiring permission if we can't determine policy coverage
        return False


def validate_expense_data(expense_data: dict, line_number: int) -> list:
    """Validate individual expense data.

    Args:
        expense_data: Expense data dictionary
        line_number: Line number for error messages (1-indexed)

    Returns:
        list: List of error dicts with index, field, and error message
    """
    errors = []

    # Required fields validation
    required_fields = {
        "description": _("Description"),
        "amount": _("Amount"),
        "expense_date": _("Expense Date"),
        "organization_type": _("Organization Type"),
        "category": _("Category"),
    }

    for field, label in required_fields.items():
        if not expense_data.get(field):
            errors.append(
                {
                    "index": line_number - 1,
                    "field": field,
                    "error": _("Line {0}: {1} is required").format(line_number, label),
                }
            )

    # Amount validation
    try:
        amount = float(expense_data.get("amount", 0))
        if amount <= 0:
            errors.append(
                {
                    "index": line_number - 1,
                    "field": "amount",
                    "error": _("Line {0}: Amount must be greater than 0").format(line_number),
                }
            )
        if amount > 5000:  # Individual expense limit
            errors.append(
                {
                    "index": line_number - 1,
                    "field": "amount",
                    "error": _("Line {0}: Amount cannot exceed 5,000 per expense").format(line_number),
                }
            )
    except (ValueError, TypeError):
        errors.append(
            {
                "index": line_number - 1,
                "field": "amount",
                "error": _("Line {0}: Invalid amount format").format(line_number),
            }
        )

    # Date validation
    if expense_data.get("expense_date"):
        try:
            from frappe.utils import getdate

            expense_date = getdate(expense_data.get("expense_date"))
            today_date = getdate(today())

            if expense_date > today_date:
                errors.append(
                    {
                        "index": line_number - 1,
                        "field": "expense_date",
                        "error": _("Line {0}: Expense date cannot be in the future").format(line_number),
                    }
                )

            # Check if date is too old (e.g., older than 1 year)
            days_old = (today_date - expense_date).days
            if days_old > 365:
                errors.append(
                    {
                        "index": line_number - 1,
                        "field": "expense_date",
                        "error": _("Line {0}: Expense date is too old (older than 1 year)").format(
                            line_number
                        ),
                    }
                )
        except (ValueError, TypeError):
            errors.append(
                {
                    "index": line_number - 1,
                    "field": "expense_date",
                    "error": _("Line {0}: Invalid date format").format(line_number),
                }
            )

    # Description validation
    description = expense_data.get("description", "").strip()
    if description and len(description) > 200:
        errors.append(
            {
                "index": line_number - 1,
                "field": "description",
                "error": _("Line {0}: Description is too long (maximum 200 characters)").format(line_number),
            }
        )

    # Organization validation
    org_type = expense_data.get("organization_type")
    if org_type == "Chapter" and not expense_data.get("chapter"):
        errors.append(
            {
                "index": line_number - 1,
                "field": "chapter",
                "error": _("Line {0}: Chapter selection is required for chapter expenses").format(
                    line_number
                ),
            }
        )
    elif org_type == "Team" and not expense_data.get("team"):
        errors.append(
            {
                "index": line_number - 1,
                "field": "team",
                "error": _("Line {0}: Team selection is required for team expenses").format(line_number),
            }
        )

    # Category validation
    category = expense_data.get("category")
    if category:
        if not frappe.db.exists("Expense Category", category):
            errors.append(
                {
                    "index": line_number - 1,
                    "field": "category",
                    "error": _("Line {0}: Invalid expense category").format(line_number),
                }
            )

    # File validation (if receipt provided)
    receipt = expense_data.get("receipt_attachment")
    if receipt and isinstance(receipt, dict):
        file_name = receipt.get("file_name", "")
        if file_name:
            # Check file extension
            allowed_extensions = [".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp"]
            if not any(file_name.lower().endswith(ext) for ext in allowed_extensions):
                errors.append(
                    {
                        "index": line_number - 1,
                        "field": "receipt_attachment",
                        "error": _("Line {0}: Invalid file type. Allowed: PDF, JPG, PNG, GIF, BMP").format(
                            line_number
                        ),
                    }
                )

            # Check file content size (base64 encoded, so roughly file_size * 1.33)
            file_content = receipt.get("file_content", "")
            if file_content and len(file_content) > 10 * 1024 * 1024:  # ~7.5MB actual file size
                errors.append(
                    {
                        "index": line_number - 1,
                        "field": "receipt_attachment",
                        "error": _("Line {0}: File size too large (maximum 7.5MB)").format(line_number),
                    }
                )

    return errors


# =============================================================================
# User/Volunteer Functions
# =============================================================================


def get_user_volunteer_record() -> Any:
    """Get the volunteer record for the current user.

    Returns:
        Volunteer document or None

    Raises:
        frappe.PermissionError: If user is guest
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access volunteer information"), frappe.PermissionError)

    # Use the existing optimized utility function
    from verenigingen.utils.performance_utils import get_user_volunteer_record_optimized

    return get_user_volunteer_record_optimized(frappe.session.user)


# =============================================================================
# Context Building Functions
# =============================================================================


def build_base_expense_context(context: Any) -> Any:
    """Build base context for expense portal pages.

    Sets common context values and handles no-volunteer case.

    Args:
        context: Frappe context object

    Returns:
        context: Modified context object with error_message if no volunteer found,
                 or populated context if volunteer exists
    """
    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access the volunteer expense portal"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True

    # Get current user's volunteer record
    volunteer_name = get_volunteer_for_current_user()
    if not volunteer_name:
        context.error_message = _(
            "No volunteer record found for your account. Please contact your chapter administrator."
        )
        # Set default values to prevent template errors
        context.volunteer = None
        context.organizations = {"chapters": [], "teams": []}
        context.expense_categories = []
        context.recent_expenses = []
        context.expense_stats = get_empty_statistics()
        context.approval_thresholds = get_approval_thresholds()
        context.national_chapter = None
        return context

    # Get the full volunteer document
    volunteer = frappe.get_doc("Volunteer", volunteer_name)
    context.volunteer = volunteer

    # Get volunteer's organizations (chapters and teams)
    context.organizations = get_volunteer_organizations(volunteer.name)

    # Get expense categories
    context.expense_categories = get_expense_categories()

    # Get volunteer's recent expenses from HRMS Expense Claims
    context.recent_expenses = get_volunteer_expenses_from_claims(volunteer.name, limit=10)

    # Get expense statistics
    context.expense_stats, context.stats_debug = get_volunteer_expense_statistics(volunteer.name)

    # Get approval thresholds for UI guidance
    context.approval_thresholds = get_approval_thresholds()

    # Get national chapter info from settings
    context.national_chapter = get_national_chapter()

    return context


def get_theme_settings() -> Any:
    """Get theme settings for portal pages with fallback defaults.

    Returns:
        Theme settings document or dict with defaults
    """
    try:
        # owl_theme is an optional theme app: absent in CI and in any bench that has
        # not installed it. The except below is the documented behaviour, not an
        # error path, so the unknown doctype here is deliberate.
        # doctype-ok: optional app, handled by the fallback below
        return frappe.get_single("Owl Theme Settings")
    except Exception:
        return frappe._dict(
            {
                "background_image": "",
                "background_color": "#ffffff",
                "navbar_color": "#ffffff",
                "primary_buttons_background_color": "#0066cc",
                "secondary_buttons_background_color": "#6c757d",
            }
        )
