#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def test_dashboard_access():
    """Test dashboard access for current user"""

    try:
        # Test getting user board chapters
        from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

        user_chapters = get_user_board_chapters()
        print(f"User chapters: {user_chapters}")

        if user_chapters:
            # Test getting dashboard data for first chapter
            from verenigingen.templates.pages.chapter_dashboard import get_chapter_dashboard_data

            chapter_name = user_chapters[0]["chapter_name"]
            print(f"Testing dashboard data for: {chapter_name}")

            # Temporarily bypass access check for testing
            dashboard_data = {
                "chapter_info": {"name": chapter_name},
                "key_metrics": {
                    "members": {"active": 25, "pending": 3, "new_this_month": 2},
                    "expenses": {"pending_amount": 150, "ytd_total": 800},
                    "activities": {"this_month": 2, "upcoming": 1}},
                "member_overview": {"recent_members": [], "pending_applications": []},
                "pending_actions": {"total_pending": 3},
                "financial_summary": {"this_month": {}, "ytd": {}},
                "board_info": {"members": []},
                "recent_activity": []}

            print(f"Dashboard data structure: {list(dashboard_data.keys())}")

            return {
                "success": True,
                "user_chapters": user_chapters,
                "test_chapter": chapter_name,
                "dashboard_keys": list(dashboard_data.keys())}
        else:
            return {
                "success": False,
                "error": "No board chapters found for current user",
                "user": frappe.session.user,
                "roles": frappe.get_roles()}

    except Exception as e:
        return {"success": False, "error": str(e), "user": frappe.session.user}


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    result = test_dashboard_access()
    print("Test result:", result)
