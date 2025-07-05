#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def test_url_access():
    """Test URL routing for pages"""

    # Check template pages directory contents
    import os

    template_dir = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/templates/pages"
    files = os.listdir(template_dir)

    # Filter for .py files (actual page handlers)
    py_files = [f[:-3] for f in files if f.endswith(".py") and not f.startswith("_")]

    results = {
        "template_pages": py_files,
        "chapter_dashboard_exists": "chapter_dashboard" in py_files,
        "member_dashboard_exists": "member_dashboard" in py_files,
        "site_url": frappe.utils.get_url(),
        "user": frappe.session.user,
    }

    # Test if we can access page context directly
    try:
        from verenigingen.templates.pages.chapter_dashboard import get_context

        test_context = frappe._dict()
        get_context(test_context)
        results["chapter_dashboard_context_ok"] = True
        results["context_data"] = {
            "title": test_context.get("title"),
            "has_data": test_context.get("has_data"),
            "selected_chapter": test_context.get("selected_chapter"),
        }
    except Exception as e:
        results["chapter_dashboard_context_ok"] = False
        results["context_error"] = str(e)

    return results


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    result = test_url_access()
    print(result)
