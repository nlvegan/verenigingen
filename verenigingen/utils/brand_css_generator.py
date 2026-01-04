"""
Brand CSS Generator - Creates static CSS file from Brand Settings
This avoids permission issues and improves performance
"""

import os

import frappe

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    development_only_api,
    standard_api,
)


def is_light_color(hex_color):
    """Calculate if a color is light (needs dark text) or dark (needs light text).

    Uses the standard luminance formula: (R*299 + G*587 + B*114) / 1000
    Colors with brightness > 128 are considered "light" and need dark text.

    Args:
        hex_color: CSS hex color string (e.g., "#F99F21" or "#fff")

    Returns:
        bool: True if the color is light (brightness > 128), False otherwise
    """
    if not hex_color or not hex_color.startswith("#"):
        return False
    hex_part = hex_color[1:]
    # Convert 3-digit hex to 6-digit
    if len(hex_part) == 3:
        hex_part = "".join([c * 2 for c in hex_part])
    try:
        r = int(hex_part[0:2], 16)
        g = int(hex_part[2:4], 16)
        b = int(hex_part[4:6], 16)
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        return brightness > 128
    except (ValueError, IndexError):
        return False


def get_contrasting_text_color(background_color):
    """Get white or black text color based on background brightness.

    Args:
        background_color: CSS hex color string

    Returns:
        str: "#000000" for light backgrounds, "#ffffff" for dark backgrounds
    """
    return "#000000" if is_light_color(background_color) else "#ffffff"


def generate_brand_css_file(doc=None, method=None):
    """Generate static brand CSS file when Brand Settings is saved"""
    try:
        # Get Brand Settings (now a Single doctype)
        if doc:
            # If called from hook, use the document passed
            brand_settings = doc
            frappe.logger().info(f"Using passed doc: {brand_settings.primary_color}")
        else:
            # Get Brand Settings as a Single doctype
            brand_settings = frappe.get_single("Brand Settings")
            frappe.logger().info(f"Loaded Brand Settings: {brand_settings.primary_color}")

        # Ensure we have the required field values
        if not brand_settings.primary_color:
            raise Exception("Brand Settings primary_color is empty")

        # Generate CSS content with full color scale
        css_content = f"""/* Brand CSS - Auto-generated from Brand Settings */
/* Generated at: {frappe.utils.now()} */

:root {{
    /* Brand Colors from Brand Settings */
    --brand-primary: {brand_settings.primary_color or '#cf3131'};
    --brand-secondary: {brand_settings.secondary_color or '#01796f'};
    --brand-accent: {brand_settings.accent_color or '#663399'};
    --brand-success: {brand_settings.success_color or '#28a745'};
    --brand-warning: {brand_settings.warning_color or '#ffc107'};
    --brand-error: {brand_settings.error_color or '#dc3545'};
    --brand-info: {brand_settings.info_color or '#17a2b8'};
    --brand-text: {brand_settings.text_primary_color or '#333333'};
    --brand-background: {brand_settings.background_primary_color or '#ffffff'};

    /* Computed variations for full Tailwind scale */
    /* Lighter shades (50-400) - mix with white */
    --brand-primary-50: color-mix(in srgb, var(--brand-primary) 10%, white);
    --brand-primary-100: color-mix(in srgb, var(--brand-primary) 20%, white);
    --brand-primary-200: color-mix(in srgb, var(--brand-primary) 35%, white);
    --brand-primary-300: color-mix(in srgb, var(--brand-primary) 50%, white);
    --brand-primary-400: color-mix(in srgb, var(--brand-primary) 70%, white);
    /* Base color (500) */
    --brand-primary-500: var(--brand-primary);
    /* Darker shades (600-900) - mix with black */
    --brand-primary-600: color-mix(in srgb, var(--brand-primary) 85%, black);
    --brand-primary-700: color-mix(in srgb, var(--brand-primary) 70%, black);
    --brand-primary-800: color-mix(in srgb, var(--brand-primary) 55%, black);
    --brand-primary-900: color-mix(in srgb, var(--brand-primary) 40%, black);

    --brand-secondary-50: color-mix(in srgb, var(--brand-secondary) 10%, white);
    --brand-secondary-100: color-mix(in srgb, var(--brand-secondary) 20%, white);
    --brand-secondary-200: color-mix(in srgb, var(--brand-secondary) 35%, white);
    --brand-secondary-300: color-mix(in srgb, var(--brand-secondary) 50%, white);
    --brand-secondary-400: color-mix(in srgb, var(--brand-secondary) 70%, white);
    --brand-secondary-500: var(--brand-secondary);
    --brand-secondary-600: color-mix(in srgb, var(--brand-secondary) 85%, black);
    --brand-secondary-700: color-mix(in srgb, var(--brand-secondary) 70%, black);
    --brand-secondary-800: color-mix(in srgb, var(--brand-secondary) 55%, black);
    --brand-secondary-900: color-mix(in srgb, var(--brand-secondary) 40%, black);

    --brand-accent-50: color-mix(in srgb, var(--brand-accent) 10%, white);
    --brand-accent-100: color-mix(in srgb, var(--brand-accent) 20%, white);
    --brand-accent-200: color-mix(in srgb, var(--brand-accent) 35%, white);
    --brand-accent-300: color-mix(in srgb, var(--brand-accent) 50%, white);
    --brand-accent-400: color-mix(in srgb, var(--brand-accent) 70%, white);
    --brand-accent-500: var(--brand-accent);
    --brand-accent-600: color-mix(in srgb, var(--brand-accent) 85%, black);
    --brand-accent-700: color-mix(in srgb, var(--brand-accent) 70%, black);
    --brand-accent-800: color-mix(in srgb, var(--brand-accent) 55%, black);
    --brand-accent-900: color-mix(in srgb, var(--brand-accent) 40%, black);

    /* Contrasting text colors for accessibility */
    --brand-primary-contrast: {'#000000' if is_light_color(brand_settings.primary_color) else '#ffffff'};
    --brand-secondary-contrast: {'#000000' if is_light_color(brand_settings.secondary_color) else '#ffffff'};
    --brand-accent-contrast: {'#000000' if is_light_color(brand_settings.accent_color) else '#ffffff'};
}}

/* Complete Tailwind utility class overrides for primary color */
.bg-primary-50 {{ background-color: var(--brand-primary-50) !important; }}
.bg-primary-100 {{ background-color: var(--brand-primary-100) !important; }}
.bg-primary-200 {{ background-color: var(--brand-primary-200) !important; }}
.bg-primary-300 {{ background-color: var(--brand-primary-300) !important; }}
.bg-primary-400 {{ background-color: var(--brand-primary-400) !important; }}
.bg-primary-500 {{ background-color: var(--brand-primary-500) !important; }}
.bg-primary-600 {{ background-color: var(--brand-primary-600) !important; }}
.bg-primary-700 {{ background-color: var(--brand-primary-700) !important; }}
.bg-primary-800 {{ background-color: var(--brand-primary-800) !important; }}
.bg-primary-900 {{ background-color: var(--brand-primary-900) !important; }}

.hover\\:bg-primary-600:hover {{ background-color: var(--brand-primary-600) !important; }}
.hover\\:bg-primary-700:hover {{ background-color: var(--brand-primary-700) !important; }}
.hover\\:bg-primary-800:hover {{ background-color: var(--brand-primary-800) !important; }}

.text-primary-50 {{ color: var(--brand-primary-50) !important; }}
.text-primary-100 {{ color: var(--brand-primary-100) !important; }}
.text-primary-200 {{ color: var(--brand-primary-200) !important; }}
.text-primary-300 {{ color: var(--brand-primary-300) !important; }}
.text-primary-400 {{ color: var(--brand-primary-400) !important; }}
.text-primary-500 {{ color: var(--brand-primary-500) !important; }}
.text-primary-600 {{ color: var(--brand-primary-600) !important; }}
.text-primary-700 {{ color: var(--brand-primary-700) !important; }}
.text-primary-800 {{ color: var(--brand-primary-800) !important; }}
.text-primary-900 {{ color: var(--brand-primary-900) !important; }}
.text-primary-contrast {{ color: var(--brand-primary-contrast) !important; }}

.border-primary-50 {{ border-color: var(--brand-primary-50) !important; }}
.border-primary-100 {{ border-color: var(--brand-primary-100) !important; }}
.border-primary-200 {{ border-color: var(--brand-primary-200) !important; }}
.border-primary-300 {{ border-color: var(--brand-primary-300) !important; }}
.border-primary-400 {{ border-color: var(--brand-primary-400) !important; }}
.border-primary-500 {{ border-color: var(--brand-primary-500) !important; }}
.border-primary-600 {{ border-color: var(--brand-primary-600) !important; }}
.border-primary-700 {{ border-color: var(--brand-primary-700) !important; }}
.border-primary-800 {{ border-color: var(--brand-primary-800) !important; }}
.border-primary-900 {{ border-color: var(--brand-primary-900) !important; }}

/* Complete Tailwind utility class overrides for secondary color */
.bg-secondary-50 {{ background-color: var(--brand-secondary-50) !important; }}
.bg-secondary-100 {{ background-color: var(--brand-secondary-100) !important; }}
.bg-secondary-200 {{ background-color: var(--brand-secondary-200) !important; }}
.bg-secondary-300 {{ background-color: var(--brand-secondary-300) !important; }}
.bg-secondary-400 {{ background-color: var(--brand-secondary-400) !important; }}
.bg-secondary-500 {{ background-color: var(--brand-secondary-500) !important; }}
.bg-secondary-600 {{ background-color: var(--brand-secondary-600) !important; }}
.bg-secondary-700 {{ background-color: var(--brand-secondary-700) !important; }}
.bg-secondary-800 {{ background-color: var(--brand-secondary-800) !important; }}
.bg-secondary-900 {{ background-color: var(--brand-secondary-900) !important; }}

.hover\\:bg-secondary-600:hover {{ background-color: var(--brand-secondary-600) !important; }}
.hover\\:bg-secondary-700:hover {{ background-color: var(--brand-secondary-700) !important; }}
.hover\\:bg-secondary-800:hover {{ background-color: var(--brand-secondary-800) !important; }}

.text-secondary-50 {{ color: var(--brand-secondary-50) !important; }}
.text-secondary-100 {{ color: var(--brand-secondary-100) !important; }}
.text-secondary-200 {{ color: var(--brand-secondary-200) !important; }}
.text-secondary-300 {{ color: var(--brand-secondary-300) !important; }}
.text-secondary-400 {{ color: var(--brand-secondary-400) !important; }}
.text-secondary-500 {{ color: var(--brand-secondary-500) !important; }}
.text-secondary-600 {{ color: var(--brand-secondary-600) !important; }}
.text-secondary-700 {{ color: var(--brand-secondary-700) !important; }}
.text-secondary-800 {{ color: var(--brand-secondary-800) !important; }}
.text-secondary-900 {{ color: var(--brand-secondary-900) !important; }}
.text-secondary-contrast {{ color: var(--brand-secondary-contrast) !important; }}

.border-secondary-50 {{ border-color: var(--brand-secondary-50) !important; }}
.border-secondary-100 {{ border-color: var(--brand-secondary-100) !important; }}
.border-secondary-200 {{ border-color: var(--brand-secondary-200) !important; }}
.border-secondary-300 {{ border-color: var(--brand-secondary-300) !important; }}
.border-secondary-400 {{ border-color: var(--brand-secondary-400) !important; }}
.border-secondary-500 {{ border-color: var(--brand-secondary-500) !important; }}
.border-secondary-600 {{ border-color: var(--brand-secondary-600) !important; }}
.border-secondary-700 {{ border-color: var(--brand-secondary-700) !important; }}
.border-secondary-800 {{ border-color: var(--brand-secondary-800) !important; }}
.border-secondary-900 {{ border-color: var(--brand-secondary-900) !important; }}

/* Complete Tailwind utility class overrides for accent color */
.bg-accent-50 {{ background-color: var(--brand-accent-50) !important; }}
.bg-accent-100 {{ background-color: var(--brand-accent-100) !important; }}
.bg-accent-200 {{ background-color: var(--brand-accent-200) !important; }}
.bg-accent-300 {{ background-color: var(--brand-accent-300) !important; }}
.bg-accent-400 {{ background-color: var(--brand-accent-400) !important; }}
.bg-accent-500 {{ background-color: var(--brand-accent-500) !important; }}
.bg-accent-600 {{ background-color: var(--brand-accent-600) !important; }}
.bg-accent-700 {{ background-color: var(--brand-accent-700) !important; }}
.bg-accent-800 {{ background-color: var(--brand-accent-800) !important; }}
.bg-accent-900 {{ background-color: var(--brand-accent-900) !important; }}

.hover\\:bg-accent-600:hover {{ background-color: var(--brand-accent-600) !important; }}
.hover\\:bg-accent-700:hover {{ background-color: var(--brand-accent-700) !important; }}
.hover\\:bg-accent-800:hover {{ background-color: var(--brand-accent-800) !important; }}

.text-accent-50 {{ color: var(--brand-accent-50) !important; }}
.text-accent-100 {{ color: var(--brand-accent-100) !important; }}
.text-accent-200 {{ color: var(--brand-accent-200) !important; }}
.text-accent-300 {{ color: var(--brand-accent-300) !important; }}
.text-accent-400 {{ color: var(--brand-accent-400) !important; }}
.text-accent-500 {{ color: var(--brand-accent-500) !important; }}
.text-accent-600 {{ color: var(--brand-accent-600) !important; }}
.text-accent-700 {{ color: var(--brand-accent-700) !important; }}
.text-accent-800 {{ color: var(--brand-accent-800) !important; }}
.text-accent-900 {{ color: var(--brand-accent-900) !important; }}
.text-accent-contrast {{ color: var(--brand-accent-contrast) !important; }}

.border-accent-50 {{ border-color: var(--brand-accent-50) !important; }}
.border-accent-100 {{ border-color: var(--brand-accent-100) !important; }}
.border-accent-200 {{ border-color: var(--brand-accent-200) !important; }}
.border-accent-300 {{ border-color: var(--brand-accent-300) !important; }}
.border-accent-400 {{ border-color: var(--brand-accent-400) !important; }}
.border-accent-500 {{ border-color: var(--brand-accent-500) !important; }}
.border-accent-600 {{ border-color: var(--brand-accent-600) !important; }}
.border-accent-700 {{ border-color: var(--brand-accent-700) !important; }}
.border-accent-800 {{ border-color: var(--brand-accent-800) !important; }}
.border-accent-900 {{ border-color: var(--brand-accent-900) !important; }}

/* Success utilities with proper scale */
.bg-success-100 {{ background-color: color-mix(in srgb, var(--brand-success) 10%, white) !important; }}
.bg-success-500 {{ background-color: var(--brand-success) !important; }}
.text-success-600 {{ color: color-mix(in srgb, var(--brand-success) 85%, black) !important; }}
.text-success-800 {{ color: color-mix(in srgb, var(--brand-success) 70%, black) !important; }}
.border-success-500 {{ border-color: var(--brand-success) !important; }}

/* Warning utilities with proper scale */
.bg-warning-100 {{ background-color: color-mix(in srgb, var(--brand-warning) 10%, white) !important; }}
.bg-warning-500 {{ background-color: var(--brand-warning) !important; }}
.text-warning-600 {{ color: color-mix(in srgb, var(--brand-warning) 85%, black) !important; }}
.text-warning-800 {{ color: color-mix(in srgb, var(--brand-warning) 70%, black) !important; }}
.border-warning-500 {{ border-color: var(--brand-warning) !important; }}

/* Danger/Error utilities with proper scale */
.bg-danger-100 {{ background-color: color-mix(in srgb, var(--brand-error) 10%, white) !important; }}
.bg-danger-500 {{ background-color: var(--brand-error) !important; }}
.text-danger-600 {{ color: color-mix(in srgb, var(--brand-error) 85%, black) !important; }}
.text-danger-800 {{ color: color-mix(in srgb, var(--brand-error) 70%, black) !important; }}
.border-danger-500 {{ border-color: var(--brand-error) !important; }}

/* Special overrides for common classes */
.bg-red-600 {{ background-color: var(--brand-primary) !important; }}

/* Form headers and gradients */
.form-header {{
    background: linear-gradient(to right, var(--brand-primary), var(--brand-primary-600)) !important;
}}

.gradient-primary-to-dark {{
    background: linear-gradient(to right, var(--brand-primary), var(--brand-primary-600)) !important;
}}

/* Button styling with proper text contrast */
.btn-primary {{
    background-color: var(--brand-primary) !important;
    border-color: var(--brand-primary) !important;
    color: var(--brand-primary-contrast) !important;
}}

.btn-primary:hover {{
    background-color: var(--brand-primary-600) !important;
    border-color: var(--brand-primary-600) !important;
}}

.btn-secondary {{
    background-color: var(--brand-secondary) !important;
    border-color: var(--brand-secondary) !important;
    color: var(--brand-secondary-contrast) !important;
}}

.btn-secondary:hover {{
    background-color: var(--brand-secondary-600) !important;
    border-color: var(--brand-secondary-600) !important;
}}

/* Additional brand utility classes for legacy code */
.bg-brand-primary {{
    background-color: var(--brand-primary) !important;
}}

.bg-brand-secondary {{
    background-color: var(--brand-secondary) !important;
}}

.bg-brand-accent {{
    background-color: var(--brand-accent) !important;
}}

.text-brand-primary {{
    color: var(--brand-primary) !important;
}}

.text-brand-secondary {{
    color: var(--brand-secondary) !important;
}}

.text-brand-accent {{
    color: var(--brand-accent) !important;
}}

.border-brand-primary {{
    border-color: var(--brand-primary) !important;
}}

.border-brand-secondary {{
    border-color: var(--brand-secondary) !important;
}}

.border-brand-accent {{
    border-color: var(--brand-accent) !important;
}}
"""

        # Write to assets directory
        css_path = get_brand_css_file_path()
        write_css_file(css_path, css_content)

        frappe.logger().info(f"Generated brand CSS file: {css_path}")

        # Also generate email CSS (with literal hex values for email clients)
        generate_email_css_file(doc=brand_settings, method=method)

        return css_path

    except Exception as e:
        import traceback

        error_msg = f"Error generating brand CSS file: {str(e)}\nTraceback: {traceback.format_exc()}"
        frappe.log_error(error_msg, "Brand CSS Generation Error")
        frappe.logger().error(error_msg)

        # Create fallback CSS file
        create_fallback_css()
        return None


def get_brand_css_file_path():
    """Get the path for the brand CSS file"""
    # Place in public CSS directory so it's web accessible
    site_path = frappe.get_site_path()
    css_dir = os.path.join(site_path, "public", "css")

    # Ensure directory exists
    if not os.path.exists(css_dir):
        os.makedirs(css_dir, exist_ok=True)

    return os.path.join(css_dir, "brand_colors.css")


def get_email_css_file_path():
    """Get the path for the email brand CSS file.

    Uses the app's public/css folder so premailer can find it via
    the /assets/verenigingen/css/ path. This is required because
    Frappe's email_css hook expects bundled assets, not site-specific files.
    """
    app_path = frappe.get_app_path("verenigingen")
    css_dir = os.path.join(app_path, "public", "css")

    if not os.path.exists(css_dir):
        os.makedirs(css_dir, exist_ok=True)

    return os.path.join(css_dir, "email_brand.css")


def generate_email_css_file(doc=None, method=None):
    """Generate email CSS with literal hex values.

    Email clients don't support CSS variables, so we bake in the actual
    color values. This file is loaded via Frappe's email_css hook and
    inlined by premailer at send time.
    """
    try:
        brand_settings = doc or frappe.get_single("Brand Settings")

        # Get contrasting text color for primary header
        primary_text = get_contrasting_text_color(brand_settings.primary_color)

        email_css = f"""/* Email Brand CSS - Auto-generated from Brand Settings */
/* Generated at: {frappe.utils.now()} */
/* NOTE: Literal hex values - email clients don't support CSS variables */

/* Email container and layout */
.email-container {{
    font-family: Arial, 'Helvetica Neue', Helvetica, sans-serif;
    max-width: 600px;
    margin: 0 auto;
    font-size: 14px;
    line-height: 1.5;
    color: {brand_settings.text_primary_color or '#333333'};
}}

/* Brand headers for different message types */
.email-header-primary {{
    background-color: {brand_settings.primary_color or '#007bff'};
    color: {primary_text};
    padding: 20px;
    border-radius: 8px 8px 0 0;
}}

.email-header-success {{
    background-color: {brand_settings.success_color or '#d4edda'};
    color: #155724;
    padding: 20px;
    border-radius: 8px 8px 0 0;
}}

.email-header-danger {{
    background-color: {brand_settings.error_color or '#f8d7da'};
    color: #721c24;
    padding: 20px;
    border-radius: 8px 8px 0 0;
}}

.email-header-warning {{
    background-color: {brand_settings.warning_color or '#fff3cd'};
    color: #856404;
    padding: 20px;
    border-radius: 8px 8px 0 0;
}}

.email-header-info {{
    background-color: {brand_settings.info_color or '#d1ecf1'};
    color: #0c5460;
    padding: 20px;
    border-radius: 8px 8px 0 0;
}}

/* Content sections */
.email-content {{
    background-color: {brand_settings.background_primary_color or '#ffffff'};
    padding: 20px;
    border: 1px solid #e9ecef;
    border-top: none;
}}

.email-content-box {{
    background-color: {brand_settings.background_secondary_color or '#f8f9fa'};
    padding: 15px;
    border-radius: 5px;
    margin: 15px 0;
}}

/* Buttons */
.email-btn-primary {{
    background-color: {brand_settings.primary_color or '#007bff'};
    color: {brand_settings.primary_button_text_color or '#ffffff'};
    padding: 15px 30px;
    text-decoration: none;
    border-radius: 5px;
    display: inline-block;
    font-weight: bold;
}}

.email-btn-secondary {{
    background-color: {brand_settings.secondary_color or '#6c757d'};
    color: {brand_settings.secondary_button_text_color or '#ffffff'};
    padding: 15px 30px;
    text-decoration: none;
    border-radius: 5px;
    display: inline-block;
    font-weight: bold;
}}

/* Alert/callout boxes */
.email-alert-warning {{
    background-color: {brand_settings.warning_color or '#fff3cd'};
    padding: 15px;
    border-radius: 5px;
    border-left: 4px solid #ffc107;
    margin: 15px 0;
}}

.email-alert-info {{
    background-color: {brand_settings.info_color or '#d1ecf1'};
    padding: 15px;
    border-radius: 5px;
    border-left: 4px solid #17a2b8;
    margin: 15px 0;
}}

/* Footer */
.email-footer {{
    font-size: 12px;
    color: {brand_settings.text_secondary_color or '#6c757d'};
    padding: 20px;
    text-align: center;
    border-top: 1px solid #e9ecef;
}}

/* Typography */
.email-title {{
    margin: 0;
    font-size: 24px;
}}

.email-subtitle {{
    margin: 5px 0 0 0;
    font-size: 14px;
    opacity: 0.9;
}}

/* Tables */
.email-data-table {{
    width: 100%;
    border-collapse: collapse;
}}

.email-data-table td {{
    padding: 8px 0;
    border-bottom: 1px solid #dee2e6;
}}

.email-data-table td:first-child {{
    font-weight: bold;
    width: 40%;
}}

/* Logo */
.email-logo {{
    max-height: 50px;
    max-width: 150px;
    margin-bottom: 10px;
}}
"""

        css_path = get_email_css_file_path()
        write_css_file(css_path, email_css)

        frappe.logger().info(f"Generated email brand CSS file: {css_path}")
        return css_path

    except Exception as e:
        frappe.log_error(f"Error generating email CSS: {str(e)}", "Email CSS Generation")
        return None


def write_css_file(file_path, content):
    """Write CSS content to file"""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        frappe.logger().info(f"Successfully wrote brand CSS to {file_path}")
    except Exception as e:
        frappe.log_error(f"Error writing CSS file {file_path}: {str(e)}", "CSS File Write Error")
        raise


def create_fallback_css():
    """Create fallback CSS file with default colors"""
    css_content = """/* Brand CSS - Fallback defaults */
:root {
    --brand-primary: #3b82f6;
    --brand-secondary: #10b981;
    --brand-accent: #8b5cf6;
    --brand-success: #10b981;
    --brand-warning: #f59e0b;
    --brand-error: #ef4444;
    --brand-info: #3b82f6;
    --brand-text: #1f2937;
    --brand-background: #ffffff;
}
/* Basic styling omitted for brevity - same as above */
"""

    css_path = get_brand_css_file_path()
    write_css_file(css_path, css_content)
    frappe.logger().info("Created fallback brand CSS file")


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def regenerate_brand_css():
    """API endpoint to manually regenerate brand CSS"""
    try:
        # Debug: Get Brand Settings first
        brand_settings = frappe.get_single("Brand Settings")
        debug_info = {
            "primary_color": brand_settings.primary_color,
            "has_data": bool(brand_settings.primary_color),
        }

        css_path = generate_brand_css_file()
        return {
            "success": True,
            "message": "Brand CSS regenerated successfully",
            "file_path": css_path,
            "debug": debug_info,
        }
    except Exception as e:
        import traceback

        return {
            "success": False,
            "message": f"Error regenerating brand CSS: {str(e)}",
            "traceback": traceback.format_exc(),
        }


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def check_brand_settings_and_generate():
    """Check Brand Settings and generate CSS file"""
    try:
        # Get Brand Settings (now a Single doctype)
        brand_settings = frappe.get_single("Brand Settings")
        message = f"Found Brand Settings - Primary: {brand_settings.primary_color}"

        # Generate CSS file
        css_path = generate_brand_css_file()

        return {
            "success": True,
            "message": f"{message}. CSS generated at: {css_path}",
            "brand_settings": {
                "primary_color": brand_settings.primary_color,
                "secondary_color": brand_settings.secondary_color,
                "accent_color": brand_settings.accent_color,
            },
            "css_path": css_path,
        }
    except Exception as e:
        import traceback

        return {"success": False, "message": f"Error: {str(e)}", "traceback": traceback.format_exc()}


def ensure_brand_css_exists():
    """Ensure brand CSS file exists on startup"""
    css_path = get_brand_css_file_path()

    if not os.path.exists(css_path):
        frappe.logger().info("Brand CSS file not found, generating...")
        try:
            generate_brand_css_file()
        except Exception:
            # If generation fails, create fallback
            create_fallback_css()
    else:
        frappe.logger().info(f"Brand CSS file exists: {css_path}")


# Call on module import to ensure CSS file exists
try:
    if frappe.db and frappe.db.db_name:  # Only if database is connected
        ensure_brand_css_exists()
except Exception:
    pass  # Ignore errors during import


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_member_user_link():
    """Debug Member-User link for troubleshooting"""
    member_name = "Assoc-Member-2025-07-0030"

    try:
        member = frappe.get_doc("Member", member_name)
        result = {
            "member_name": member.full_name,
            "member_email": member.email,
            "user_field_value": member.user,
            "user_field_type": str(type(member.user)),
            "user_field_empty": not member.user,
        }

        if member.user:
            # Check if the user record exists
            user_exists = frappe.db.exists("User", member.user)
            result["user_record_exists"] = user_exists

            if user_exists:
                user_doc = frappe.get_doc("User", member.user)
                result["user_email"] = user_doc.email
                result["user_enabled"] = user_doc.enabled
            else:
                result["error"] = "User record does not exist in database"
        else:
            result["message"] = "No user linked to this member"

            # Check if there's a user with the same email
            if member.email:
                users_with_email = frappe.get_all(
                    "User", filters={"email": member.email}, fields=["name", "email", "enabled"]
                )
                result["users_with_same_email"] = users_with_email

        return result

    except Exception as e:
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc()}
