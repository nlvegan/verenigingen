"""
Get user's chapter memberships
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.member_utils import get_member_name_for_user
from verenigingen.utils.operation_result import OperationResult

# Import security decorators
from verenigingen.utils.security.api_security_framework import OperationType, public_api


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)  # Public chapter listing with user membership status
def get_user_chapter_data() -> OperationResult[Dict[str, Any]]:
    """Get current user's chapter memberships"""
    try:
        user = frappe.session.user

        if user == "Guest":
            return OperationResult.ok(
                {"user": user, "member": None, "chapters": [], "user_chapters": []},
                message=_("Retrieved chapter data for guest user"),
            )

        # Get member record
        member = get_member_name_for_user(user)

        # Get all chapters with user membership status
        if member:
            # User has a member record - check their chapter memberships
            all_chapters = frappe.db.sql(
                """
                SELECT
                    c.name,
                    c.published,
                    COALESCE(c.route, CONCAT('chapters/', LOWER(REPLACE(c.name, ' ', '-')))) as route,
                    c.introduction,
                    c.region,
                    c.address,
                    CASE WHEN cm.member IS NOT NULL AND cm.enabled = 1 AND (cm.status = 'Active' OR cm.status IS NULL) THEN 1 ELSE 0 END as is_member,
                    CASE WHEN cm.member IS NOT NULL AND cm.enabled = 1 AND cm.status = 'Pending' THEN 1 ELSE 0 END as is_pending
                FROM `tabChapter` c
                LEFT JOIN `tabChapter Member` cm ON cm.parent = c.name AND cm.member = %s
                WHERE c.published = 1
                ORDER BY c.name
            """,
                member,
                as_dict=True,
            )
        else:
            # User has no member record - show all chapters without membership status
            all_chapters = frappe.db.sql(
                """
                SELECT
                    c.name,
                    c.published,
                    COALESCE(c.route, CONCAT('chapters/', LOWER(REPLACE(c.name, ' ', '-')))) as route,
                    c.introduction,
                    c.region,
                    c.address,
                    0 as is_member,
                    0 as is_pending
                FROM `tabChapter` c
                WHERE c.published = 1
                ORDER BY c.name
            """,
                as_dict=True,
            )

        # Get list of chapters user is member of
        user_chapters = [ch["name"] for ch in all_chapters if ch["is_member"]]

        return OperationResult.ok(
            {
                "user": user,
                "member": member,
                "chapters": all_chapters,
                "user_chapters": user_chapters,
            },
            message=_("Successfully retrieved user chapter data"),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Get User Chapters Failed"),
            message=f"Error retrieving chapter data for user {frappe.session.user}: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(_("Failed to retrieve user chapter data"), errors=[str(e)])
