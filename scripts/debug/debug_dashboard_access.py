#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def debug_dashboard_access():
    """Debug dashboard access issues"""

    try:
        # Import the dashboard module
        from verenigingen.templates.pages.chapter_dashboard import get_context, get_user_board_chapters

        results = {
            "status": "success",
            "user": frappe.session.user,
            "roles": frappe.get_roles(),
            "is_guest": frappe.session.user == "Guest",
        }

        if frappe.session.user == "Guest":
            results["message"] = "User is guest - needs to login"
            return results

        # Try to get user chapters
        try:
            user_chapters = get_user_board_chapters()
            results["user_chapters"] = user_chapters
            results["has_board_access"] = len(user_chapters) > 0 if user_chapters else False
        except Exception as e:
            results["chapter_error"] = str(e)

        # Try to simulate getting context
        try:
            context = {}
            get_context(context)
            results["context_keys"] = list(context.keys())
            results["has_context_error"] = bool(context.get("error_message"))
        except Exception as e:
            results["context_error"] = str(e)

        return results

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "user": frappe.session.user if hasattr(frappe, "session") else "unknown",
        }


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    result = debug_dashboard_access()
    print("Debug result:", result)
