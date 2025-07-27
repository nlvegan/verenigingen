"""
Get user's chapter memberships
"""

import frappe

# Import security decorators
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@frappe.whitelist(allow_guest=True)
@standard_api(operation_type=OperationType.MEMBER_DATA)  # User chapter data - personal membership info
def get_user_chapter_data():
    """Get current user's chapter memberships"""

    user = frappe.session.user

    if user == "Guest":
        return {"success": True, "user": user, "member": None, "chapters": [], "user_chapters": []}

    # Get member record
    member = frappe.db.get_value("Member", {"email": user}, "name")

    # Get all chapters with user membership status
    all_chapters = frappe.db.sql(
        """
        SELECT
            c.name,
            c.published,
            COALESCE(c.route, CONCAT('chapters/', LOWER(REPLACE(c.name, ' ', '-')))) as route,
            c.introduction,
            c.region,
            c.address,
            CASE WHEN cm.member IS NOT NULL AND cm.enabled = 1 THEN 1 ELSE 0 END as is_member
        FROM `tabChapter` c
        LEFT JOIN `tabChapter Member` cm ON cm.parent = c.name AND cm.member = %s
        WHERE c.published = 1
        ORDER BY c.name
    """,
        member,
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
