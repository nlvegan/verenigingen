#!/usr/bin/env python3

import frappe
import requests


def test_dashboard_route():
    """Test if chapter dashboard route is accessible"""

    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        # Test 1: Check if template files exist
        import os

        template_py = (
            "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/templates/pages/chapter_dashboard.py"
        )
        template_html = (
            "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/templates/pages/chapter_dashboard.html"
        )

        print(f"Template .py exists: {os.path.exists(template_py)}")
        print(f"Template .html exists: {os.path.exists(template_html)}")

        # Test 2: Try to import the module
        try:
            from verenigingen.templates.pages.chapter_dashboard import get_context

            print("✓ Module import successful")
        except ImportError as e:
            print(f"✗ Module import failed: {e}")
            return

        # Test 3: Try to get dashboard data directly
        try:
            from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

            user_chapters = get_user_board_chapters()
            print(f"Board chapters found: {len(user_chapters) if user_chapters else 0}")
        except Exception as e:
            print(f"Error getting board chapters: {e}")

        # Test 4: Check if we can access the route via HTTP request
        try:
            # Note: This would need authentication in real scenario
            print("HTTP route test: Would need authentication to test properly")
            print("Dashboard should be accessible at: https://dev.veganisme.net/chapter-dashboard")
        except Exception as e:
            print(f"HTTP test error: {e}")

        print("\nTesting complete. If module import works, the issue may be:")
        print("1. User permission/authentication issues")
        print("2. Missing board member role for the user")
        print("3. Web server routing configuration")

    except Exception as e:
        print(f"Test error: {e}")
    finally:
        frappe.destroy()


if __name__ == "__main__":
    test_dashboard_route()
