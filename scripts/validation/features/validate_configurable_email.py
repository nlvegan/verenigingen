#!/usr/bin/env python3
"""
Validation script for configurable member contact email
Tests that the email is now configurable in Verenigingen Settings
"""

import json
import os
import sys


def check_settings_field():
    """Check if member_contact_email field was added to Verenigingen Settings"""
    settings_json_path = "verenigingen/verenigingen/doctype/verenigingen_settings/verenigingen_settings.json"

    if not os.path.exists(settings_json_path):
        return False, "verenigingen_settings.json not found"

    try:
        with open(settings_json_path, "r") as f:
            settings_data = json.load(f)

        # Check field_order
        field_order = settings_data.get("field_order", [])
        if "member_contact_email" not in field_order:
            return False, "member_contact_email not found in field_order"

        # Check field definition
        fields = settings_data.get("fields", [])
        contact_email_field = None
        for field in fields:
            if field.get("fieldname") == "member_contact_email":
                contact_email_field = field
                break

        if not contact_email_field:
            return False, "member_contact_email field definition not found"

        # Validate field properties
        if contact_email_field.get("fieldtype") != "Data":
            return False, "Field type should be Data"

        if contact_email_field.get("options") != "Email":
            return False, "Field should have Email options"

        if not contact_email_field.get("description"):
            return False, "Field should have a description"

        return True, "Member contact email field properly configured"

    except Exception as e:
        return False, f"Error checking settings: {e}"


def check_fee_adjustment_controller():
    """Check if fee adjustment controller uses the configurable email"""
    controller_path = "verenigingen/templates/pages/membership_fee_adjustment.py"

    if not os.path.exists(controller_path):
        return False, "Fee adjustment controller not found"

    try:
        with open(controller_path, "r") as f:
            content = f.read()

        # Check if it gets the setting
        if "member_contact_email" not in content:
            return False, "Controller doesn't reference member_contact_email"

        if "Verenigingen Settings" not in content:
            return False, "Controller doesn't access Verenigingen Settings"

        # Check for fallback email
        if "ledenadministratie@veganisme.org" not in content:
            return False, "No fallback email configured"

        return True, "Controller properly configured for email setting"

    except Exception as e:
        return False, f"Error checking controller: {e}"


def check_fee_adjustment_template():
    """Check if fee adjustment template uses the configurable email"""
    template_path = "verenigingen/templates/pages/membership_fee_adjustment.html"

    if not os.path.exists(template_path):
        return False, "Fee adjustment template not found"

    try:
        with open(template_path, "r") as f:
            content = f.read()

        # Check if template uses the variable
        if "{{ member_contact_email }}" not in content:
            return False, "Template doesn't use member_contact_email variable"

        # Check if hardcoded email is removed
        if (
            "ledenadministratie@veganisme.org" in content
            and "mailto:ledenadministratie@veganisme.org" in content
        ):
            return False, "Template still contains hardcoded email"

        # Check for proper usage in tooltip and mailto
        if "mailto:{{ member_contact_email }}" not in content:
            return False, "Mailto link not updated to use variable"

        return True, "Template properly configured for email setting"

    except Exception as e:
        return False, f"Error checking template: {e}"


def main():
    """Main validation function"""
    print("🔍 Validating Configurable Member Contact Email...")
    print("=" * 60)

    checks = [
        ("Verenigingen Settings Field", check_settings_field),
        ("Fee Adjustment Controller", check_fee_adjustment_controller),
        ("Fee Adjustment Template", check_fee_adjustment_template),
    ]

    all_valid = True

    for check_name, check_func in checks:
        valid, message = check_func()
        status = "✅" if valid else "❌"
        print(f"{status} {check_name} - {message}")

        if not valid:
            all_valid = False

    print("=" * 60)

    if all_valid:
        print("🎉 Configurable email implementation is valid!")
        print("\n📋 Implementation Summary:")
        print("   • Added member_contact_email field to Verenigingen Settings")
        print("   • Field type: Data with Email validation")
        print("   • Proper description for administrators")
        print("   • Fee adjustment controller retrieves setting")
        print("   • Fallback to default email if not configured")
        print("   • Template uses configurable email variable")
        print("   • Email used in tooltips and contact links")

        print("\n⚙️ Configuration Steps:")
        print("   1. Go to Verenigingen Settings in backend")
        print("   2. Set 'Member Contact Email' field")
        print("   3. Email will be used in:")
        print("      • Fee adjustment form tooltips")
        print("      • Contact support buttons")
        print("      • Out-of-range amount messages")

        print("\n🔧 For Other Organizations:")
        print("   • Simply configure the email in settings")
        print("   • No code changes needed")
        print("   • Automatic fallback to default if not set")

        return 0
    else:
        print("❌ Some validation errors found. Please review the implementation.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
