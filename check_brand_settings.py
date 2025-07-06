#!/usr/bin/env python3
"""
Check current brand settings and colors
"""

import sys

import frappe

sys.path.insert(0, "/home/frappe/frappe-bench")
sys.path.insert(0, "/home/frappe/frappe-bench/apps/frappe")
sys.path.insert(0, "/home/frappe/frappe-bench/sites")


def check_brand_settings():
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    print("Current Brand Settings:")
    print("=" * 40)

    try:
        if frappe.db.exists("Brand Settings", "Brand Settings"):
            settings = frappe.get_doc("Brand Settings", "Brand Settings")
            print(f"Primary Color: {settings.primary_color}")
            print(f"Secondary Color: {settings.secondary_color}")
            print(f"Accent Color: {settings.accent_color}")
            print(f"Success Color: {settings.success_color}")
            print(f"Warning Color: {settings.warning_color}")
            print(f"Error Color: {settings.error_color}")
            print(f"Info Color: {settings.info_color}")
            print(f"Text Color: {settings.text_color}")
            print(f"Background Color: {settings.background_color}")
        else:
            print("❌ Brand Settings record does not exist!")
            print("Creating default Brand Settings...")

            # Create default brand settings
            brand_settings = frappe.get_doc(
                {
                    "doctype": "Brand Settings",
                    "name": "Brand Settings",
                    "primary_color": "#cf3131",
                    "secondary_color": "#01796f",
                    "accent_color": "#663399",
                    "success_color": "#10b981",
                    "warning_color": "#f59e0b",
                    "error_color": "#ef4444",
                    "info_color": "#3b82f6",
                    "text_color": "#1f2937",
                    "background_color": "#ffffff",
                }
            )
            brand_settings.insert(ignore_permissions=True)
            frappe.db.commit()
            print("✅ Default Brand Settings created!")

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    check_brand_settings()
