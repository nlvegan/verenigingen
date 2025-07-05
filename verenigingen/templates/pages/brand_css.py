import frappe
from frappe.utils import now

from verenigingen.verenigingen.doctype.brand_settings.brand_settings import generate_brand_css


def get_context(context):
    """Generate CSS content for brand colors"""
    context.no_cache = 1

    # Add timestamp comment to help debug caching issues
    css = generate_brand_css()
    css_with_timestamp = f"/* Generated at {now()} */\n{css}"

    # Set response content and headers after generating CSS
    context.css_content = css_with_timestamp

    # Set headers
    frappe.response.content_type = "text/css; charset=utf-8"
    frappe.response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    frappe.response.headers["Pragma"] = "no-cache"
    frappe.response.headers["Expires"] = "0"

    return context


@frappe.whitelist(allow_guest=True)
def serve_brand_css():
    """Serve brand CSS with proper MIME type"""
    try:
        css = generate_brand_css()
        css_with_timestamp = f"/* Generated at {now()} */\n{css}"

        # Set response content type
        if hasattr(frappe, "response"):
            frappe.response.content_type = "text/css; charset=utf-8"

            # Initialize headers if they don't exist
            if not hasattr(frappe.response, "headers") or frappe.response.headers is None:
                frappe.response.headers = {}

            frappe.response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            frappe.response.headers["Pragma"] = "no-cache"
            frappe.response.headers["Expires"] = "0"

        return css_with_timestamp

    except Exception as e:
        frappe.log_error(f"Error serving brand CSS: {str(e)}", "Brand CSS Error")
        # Return fallback CSS
        return """
/* Fallback brand CSS */
:root {
    --brand-primary: #cf3131;
    --brand-secondary: #01796f;
    --brand-primary-dark: #a52828;
}
.gradient-primary-to-dark {
    background: linear-gradient(to right, var(--brand-primary), var(--brand-primary-dark)) !important;
}
"""
