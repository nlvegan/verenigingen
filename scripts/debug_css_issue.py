#!/usr/bin/env python
"""
Debug CSS loading issues affecting the desk menu
"""
import frappe


def check_css_loading():
    """Check what CSS files are being loaded"""
    print("Checking CSS loading configuration...")

    # Check hooks.py for CSS includes
    from verenigingen import hooks

    print("\n1. app_include_css from hooks.py:")
    for css in hooks.app_include_css:
        print(f"   - {css}")

    # Check if brand settings CSS is being generated
    print("\n2. Brand Settings CSS status:")
    try:
        from verenigingen.verenigingen.doctype.brand_settings.brand_settings import generate_brand_css

        css_content = generate_brand_css()
        print(f"   - CSS generated successfully, length: {len(css_content)} characters")

        # Check for problematic CSS rules
        problematic_rules = ["!important", ".bg-red-600", ".bg-green-600", "color-primary-500"]

        print("\n3. Checking for problematic CSS rules:")
        for rule in problematic_rules:
            count = css_content.count(rule)
            if count > 0:
                print(f"   - Found '{rule}': {count} times")

    except Exception as e:
        print(f"   - Error generating CSS: {str(e)}")

    # Check active brand settings
    print("\n4. Active Brand Settings:")
    try:
        active_settings = frappe.get_all(
            "Brand Settings", filters={"is_active": 1}, fields=["name", "settings_name"], limit=1
        )

        if active_settings:
            print(f"   - Active: {active_settings[0]['settings_name']} ({active_settings[0]['name']})")
        else:
            print("   - No active brand settings found")
    except Exception as e:
        print(f"   - Error checking brand settings: {str(e)}")

    # Check cache status
    print("\n5. Cache status:")
    try:
        cached_css = frappe.cache().get_value("brand_settings_css")
        if cached_css:
            print(f"   - Cached CSS found, length: {len(cached_css)} characters")
        else:
            print("   - No cached CSS found")

        cached_settings = frappe.cache().get_value("active_brand_settings")
        if cached_settings:
            print("   - Cached settings found")
        else:
            print("   - No cached settings found")
    except Exception as e:
        print(f"   - Error checking cache: {str(e)}")

    # Check for CSS conflicts with other apps
    print("\n6. Checking other apps for CSS conflicts:")
    try:
        all_hooks = frappe.get_hooks()
        if "app_include_css" in all_hooks:
            for app, css_files in all_hooks["app_include_css"].items():
                if isinstance(css_files, list) and css_files:
                    print(f"   - {app}: {len(css_files)} CSS files")
                    for css in css_files[:3]:  # Show first 3
                        print(f"     • {css}")
    except Exception as e:
        print(f"   - Error checking other apps: {str(e)}")


if __name__ == "__main__":
    frappe.connect()
    check_css_loading()
    frappe.destroy()
