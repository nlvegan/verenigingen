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

    # Set headers
    frappe.response.content_type = "text/css; charset=utf-8"
    frappe.response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    frappe.response.headers["Pragma"] = "no-cache"
    frappe.response.headers["Expires"] = "0"

    return context
