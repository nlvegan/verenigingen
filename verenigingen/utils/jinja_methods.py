"""
Jinja template methods for Verenigingen app
"""

import frappe


def get_brand_css_variables():
    """Get brand color CSS variables for templates"""
    try:
        # Try to get brand settings
        if frappe.db.exists("Brand Settings", "Brand Settings"):
            frappe.get_doc("Brand Settings", "Brand Settings")

            # Generate CSS variables
            css_vars = """
/* Brand colors from Brand Settings */
:root {{
    --brand-primary: {brand_settings.primary_color or '#cf3131'};
    --brand-secondary: {brand_settings.secondary_color or '#01796f'};
    --brand-accent: {brand_settings.accent_color or '#663399'};
    --brand-success: {brand_settings.success_color or '#10b981'};
    --brand-warning: {brand_settings.warning_color or '#f59e0b'};
    --brand-error: {brand_settings.error_color or '#ef4444'};
    --brand-info: {brand_settings.info_color or '#3b82f6'};
    --brand-text: {brand_settings.text_color or '#1f2937'};
    --brand-background: {brand_settings.background_color or '#ffffff'};
}}
"""
            return css_vars
        else:
            # Return default colors if no brand settings
            return """
/* Default brand colors */
:root {
    --brand-primary: #cf3131;
    --brand-secondary: #01796f;
    --brand-accent: #663399;
    --brand-success: #10b981;
    --brand-warning: #f59e0b;
    --brand-error: #ef4444;
    --brand-info: #3b82f6;
    --brand-text: #1f2937;
    --brand-background: #ffffff;
}
"""
    except Exception as e:
        frappe.log_error(f"Error loading brand CSS variables: {str(e)}", "Brand CSS Variables Error")
        # Return safe defaults
        return """
/* Fallback brand colors */
:root {
    --brand-primary: #cf3131;
    --brand-secondary: #01796f;
    --brand-accent: #663399;
}
"""
