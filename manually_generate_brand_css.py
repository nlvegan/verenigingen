#!/usr/bin/env python3
"""
Manually generate brand CSS to test the system
"""

import os
import sys

import frappe

sys.path.insert(0, "/home/frappe/frappe-bench")
sys.path.insert(0, "/home/frappe/frappe-bench/apps/frappe")
sys.path.insert(0, "/home/frappe/frappe-bench/sites")


def manually_generate_css():
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    print("Manually generating brand CSS...")

    # Get site path and create directory
    site_path = frappe.get_site_path()
    css_dir = os.path.join(site_path, "public", "css")
    css_file = os.path.join(css_dir, "brand_colors.css")

    print(f"Site path: {site_path}")
    print(f"CSS directory: {css_dir}")
    print(f"CSS file: {css_file}")

    # Create directory
    if not os.path.exists(css_dir):
        print("Creating CSS directory...")
        os.makedirs(css_dir, exist_ok=True)
        print("✓ CSS directory created")

    # Check Brand Settings
    if frappe.db.exists("Brand Settings", "Brand Settings"):
        settings = frappe.get_doc("Brand Settings", "Brand Settings")
        print(f"✓ Brand Settings found - Primary: {settings.primary_color}")
        primary_color = settings.primary_color or "#3b82f6"
        secondary_color = settings.secondary_color or "#10b981"
        accent_color = settings.accent_color or "#8b5cf6"
    else:
        print("Brand Settings not found, using defaults")
        primary_color = "#3b82f6"
        secondary_color = "#10b981"
        accent_color = "#8b5cf6"

    # Generate CSS content
    css_content = f"""/* Brand CSS - Generated manually */
/* Generated at: {frappe.utils.now()} */

:root {{
    --brand-primary: {primary_color};
    --brand-secondary: {secondary_color};
    --brand-accent: {accent_color};
    --brand-success: #10b981;
    --brand-warning: #f59e0b;
    --brand-error: #ef4444;
    --brand-info: #3b82f6;
    --brand-text: #1f2937;
    --brand-background: #ffffff;

    --brand-primary-hover: color-mix(in srgb, var(--brand-primary) 85%, black);
    --brand-secondary-hover: color-mix(in srgb, var(--brand-secondary) 85%, black);
    --brand-accent-hover: color-mix(in srgb, var(--brand-accent) 85%, black);
}}

/* Tailwind overrides */
.bg-primary-500 {{ background-color: var(--brand-primary) !important; }}
.bg-primary-600 {{ background-color: var(--brand-primary-hover) !important; }}
.text-primary-500 {{ color: var(--brand-primary) !important; }}
.text-primary-600 {{ color: var(--brand-primary-hover) !important; }}

.bg-secondary-500 {{ background-color: var(--brand-secondary) !important; }}
.bg-secondary-600 {{ background-color: var(--brand-secondary-hover) !important; }}
.text-secondary-500 {{ color: var(--brand-secondary) !important; }}
.text-secondary-600 {{ color: var(--brand-secondary-hover) !important; }}

.bg-accent-500 {{ background-color: var(--brand-accent) !important; }}
.bg-accent-600 {{ background-color: var(--brand-accent-hover) !important; }}
.text-accent-500 {{ color: var(--brand-accent) !important; }}
.text-accent-600 {{ color: var(--brand-accent-hover) !important; }}

.bg-red-600 {{ background-color: var(--brand-primary) !important; }}

.form-header {{
    background: linear-gradient(to right, var(--brand-primary), var(--brand-primary-hover)) !important;
}}

.btn-primary {{
    background-color: var(--brand-primary) !important;
    border-color: var(--brand-primary) !important;
}}

.btn-primary:hover {{
    background-color: var(--brand-primary-hover) !important;
    border-color: var(--brand-primary-hover) !important;
}}
"""

    # Write CSS file
    try:
        with open(css_file, "w", encoding="utf-8") as f:
            f.write(css_content)
        print(f"✓ CSS file written: {css_file}")
        print(f"✓ File size: {len(css_content)} characters")

        # Verify file exists and is readable
        if os.path.exists(css_file):
            print("✓ File exists and is accessible")
            with open(css_file, "r") as f:
                read_content = f.read()
            print(f"✓ File readable, {len(read_content)} characters")
        else:
            print("✗ File was not created successfully")

    except Exception as e:
        print(f"✗ Error writing CSS file: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    manually_generate_css()
