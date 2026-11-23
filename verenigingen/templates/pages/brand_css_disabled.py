import frappe


def get_context(context):
    """Temporarily disable brand CSS to test if it's causing menu issues"""
    context.no_cache = 1

    # Return minimal CSS without overrides
    css_content = """
/* Brand CSS temporarily disabled for debugging */
/* Only essential brand variables */
:root {
    --brand-primary: #cf3131;
    --brand-secondary: #01796f;
    --brand-accent: #663399;
}
"""

    context.css_content = css_content

    # Headers go in frappe.local.response_headers, the only dict app.py applies to the
    # HTTP response. frappe.response is the body dict and ignores content_type here (#2779).
    frappe.local.response_headers["Content-Type"] = "text/css; charset=utf-8"
    frappe.local.response_headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    frappe.local.response_headers["Pragma"] = "no-cache"
    frappe.local.response_headers["Expires"] = "0"

    return context
