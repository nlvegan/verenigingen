"""
Get user's chapter memberships
"""

import frappe

# Import security decorators
from verenigingen.utils.security.api_security_framework import OperationType, public_api


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)  # Public chapter listing with user membership status
def get_user_chapter_data():
    """Get current user's chapter memberships"""

    user = frappe.session.user

    if user == "Guest":
        return {"success": True, "user": user, "member": None, "chapters": [], "user_chapters": []}

    # Get member record
    member = frappe.db.get_value("Member", {"email": user}, "name")

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

    return {
        "success": True,
        "user": user,
        "member": member,
        "chapters": all_chapters,
        "user_chapters": user_chapters,
    }
