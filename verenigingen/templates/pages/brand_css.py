import os

import frappe
from frappe.utils import now

from verenigingen.utils.brand_css_generator import get_brand_css_file_path
from verenigingen.utils.security.api_security_framework import public_api


def get_context(context):
    """Generate CSS content for brand colors"""
    context.no_cache = 1

    # Read from the static CSS file
    css_path = get_brand_css_file_path()
    if os.path.exists(css_path):
        with open(css_path, "r") as f:
            css = f.read()
    else:
        # Fallback if file doesn't exist
        from verenigingen.verenigingen.doctype.brand_settings.brand_settings import generate_brand_css

        css = generate_brand_css()

    # Add timestamp comment to help debug caching issues
    css_with_timestamp = f"/* Generated at {now()} */\n{css}"

    # Set response content and headers after generating CSS
    context.css_content = css_with_timestamp

    # Headers go in frappe.local.response_headers, the only dict app.py applies to the
    # HTTP response. frappe.response is the body dict and ignores content_type here (#2779).
    frappe.local.response_headers["Content-Type"] = "text/css; charset=utf-8"
    frappe.local.response_headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    frappe.local.response_headers["Pragma"] = "no-cache"
    frappe.local.response_headers["Expires"] = "0"

    return context


@frappe.whitelist(allow_guest=True)
@public_api
def serve_brand_css():
    """Serve brand CSS with proper MIME type"""
    try:
        # Read from the static CSS file
        css_path = get_brand_css_file_path()
        if os.path.exists(css_path):
            with open(css_path, "r") as f:
                css = f.read()
        else:
            # Fallback if file doesn't exist
            from verenigingen.verenigingen.doctype.brand_settings.brand_settings import generate_brand_css

            css = generate_brand_css()

        css_with_timestamp = f"/* Generated at {now()} */\n{css}"

        # This endpoint answers in the JSON envelope, so Content-Type stays JSON; only the
        # cache headers are meaningful. They must go in response_headers: keys set on
        # frappe.response land in the JSON body instead (#2779).
        frappe.local.response_headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        frappe.local.response_headers["Pragma"] = "no-cache"
        frappe.local.response_headers["Expires"] = "0"

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
