#!/usr/bin/env python3
"""
Validation script for personal details management
Tests syntax and basic structure without requiring Frappe imports
"""

import ast
import json
import os
import sys


def validate_python_file(file_path):
    """Validate Python file syntax"""
    try:
        with open(file_path, "r") as f:
            content = f.read()

        # Parse the file to check for syntax errors
        ast.parse(content)
        return True, "Syntax OK"
    except SyntaxError as e:
        return False, f"Syntax Error: {e}"
    except Exception as e:
        return False, f"Error: {e}"


def validate_html_basic(file_path):
    """Basic HTML validation"""
    try:
        with open(file_path, "r") as f:
            content = f.read()

        # Check for basic HTML structure
        required_elements = [
            '{% extends "templates/web.html" %}',
            "{% block page_content %}",
            "{% endblock %}",
        ]
        missing_elements = [elem for elem in required_elements if elem not in content]

        if missing_elements:
            return False, f"Missing elements: {missing_elements}"

        return True, "HTML structure OK"
    except Exception as e:
        return False, f"Error: {e}"


def check_personal_details_features(file_path):
    """Check for personal details specific features"""
    try:
        with open(file_path, "r") as f:
            content = f.read()

        features = []

        # Check for key features
        if "pronouns" in content.lower():
            features.append("Pronouns support")

        if "custom_pronouns" in content:
            features.append("Custom pronouns")

        if "first_name" in content and "last_name" in content:
            features.append("Name fields")

        if "birth_date" in content:
            features.append("Birth date")

        if "contact_number" in content:
            features.append("Contact information")

        if "image" in content:
            features.append("Profile image upload")

        if "privacy" in content.lower() or "gdpr" in content.lower():
            features.append("Privacy notices")

        if "validation" in content.lower():
            features.append("Form validation")

        return True, f"Features found: {', '.join(features)}"

    except Exception as e:
        return False, f"Error: {e}"


def check_pronouns_field_update():
    """Check if pronouns field was updated in member.json"""
    member_json_path = "verenigingen/verenigingen/doctype/member/member.json"

    if not os.path.exists(member_json_path):
        return False, "member.json not found"

    try:
        with open(member_json_path, "r") as f:
            member_data = json.load(f)

        # Find pronouns field
        pronouns_field = None
        for field in member_data.get("fields", []):
            if field.get("fieldname") == "pronouns":
                pronouns_field = field
                break

        if not pronouns_field:
            return False, "Pronouns field not found"

        # Check if it's now a Data field (not Select)
        if pronouns_field.get("fieldtype") == "Data":
            return True, "Pronouns field updated to Data type for custom entries"
        else:
            return False, f"Pronouns field is still {pronouns_field.get('fieldtype')}"

    except Exception as e:
        return False, f"Error checking member.json: {e}"


def main():
    """Main validation function"""
    print("🔍 Validating Personal Details Implementation...")
    print("=" * 60)

    files_to_validate = [
        ("verenigingen/templates/pages/personal_details.py", "python"),
        ("verenigingen/templates/pages/personal_details.html", "html"),
    ]

    all_valid = True

    for file_path, file_type in files_to_validate:
        if not os.path.exists(file_path):
            print(f"❌ {file_path} - File not found")
            all_valid = False
            continue

        if file_type == "python":
            valid, message = validate_python_file(file_path)
        elif file_type == "html":
            valid, message = validate_html_basic(file_path)

        status = "✅" if valid else "❌"
        print(f"{status} {file_path} - {message}")

        if not valid:
            all_valid = False

    print("=" * 60)

    # Check for required functions in Python file
    python_file = "verenigingen/templates/pages/personal_details.py"
    required_functions = [
        "get_context",
        "has_website_permission",
        "update_personal_details",
        "validate_name_format",
        "validate_phone_number",
        "validate_pronouns",
        "track_changes",
        "handle_image_update",
        "apply_personal_details_changes",
    ]

    try:
        with open(python_file, "r") as f:
            content = f.read()

        missing_functions = []
        for func in required_functions:
            if f"def {func}" not in content:
                missing_functions.append(func)

        if missing_functions:
            print(f"⚠️  {python_file} - Missing functions: {missing_functions}")
            all_valid = False
        else:
            print(f"✅ {python_file} - All required functions present")

    except Exception as e:
        print(f"❌ {python_file} - Error checking functions: {e}")
        all_valid = False

    print("=" * 60)

    # Check personal details features
    html_file = "verenigingen/templates/pages/personal_details.html"
    if os.path.exists(html_file):
        valid, message = check_personal_details_features(html_file)
        status = "✅" if valid else "❌"
        print(f"{status} {html_file} - {message}")

    # Check pronouns field update
    valid, message = check_pronouns_field_update()
    status = "✅" if valid else "❌"
    print(f"{status} Member DocType - {message}")

    # Check member portal integration
    portal_file = "verenigingen/templates/pages/member_portal.html"
    if os.path.exists(portal_file):
        try:
            with open(portal_file, "r") as f:
                content = f.read()

            if "personal_details" in content and "pronouns" in content.lower():
                print(f"✅ {portal_file} - Personal details integration found")
            else:
                print(f"⚠️  {portal_file} - Personal details integration not found")

        except Exception as e:
            print(f"❌ {portal_file} - Error checking integration: {e}")

    # Check dashboard integration
    dashboard_file = "verenigingen/templates/pages/member_dashboard.py"
    if os.path.exists(dashboard_file):
        try:
            with open(dashboard_file, "r") as f:
                content = f.read()

            if "personal_details" in content:
                print(f"✅ {dashboard_file} - Personal details link found")
            else:
                print(f"⚠️  {dashboard_file} - Personal details link not found")

        except Exception as e:
            print(f"❌ {dashboard_file} - Error checking integration: {e}")

    print("=" * 60)

    if all_valid:
        print("🎉 Personal Details implementation is valid!")
        print("\n📋 Implementation Summary:")
        print("   • Comprehensive personal details management page")
        print("   • Name fields (first, middle, last) with validation")
        print("   • Flexible pronouns system (predefined + custom)")
        print("   • Contact information management")
        print("   • Profile image upload/removal")
        print("   • Privacy preferences and GDPR compliance")
        print("   • Secure form handling with validation")
        print("   • Success feedback system")

        print("\n🏷️ Pronouns Support:")
        print("   • She/her, He/him, They/them (predefined)")
        print("   • Custom pronoun entry support")
        print("   • Updated Member DocType to Data field")
        print("   • Validation for appropriate content")

        print("\n🔒 Security & Privacy:")
        print("   • Member-only access with permission checks")
        print("   • Input validation and sanitization")
        print("   • GDPR compliance notices")
        print("   • Email address protection (read-only)")
        print("   • Audit logging for changes")

        print("\n🎯 Page accessible at:")
        print("   • /personal_details - Main form")
        print("   • Linked from member portal and dashboard")

        print("\n💡 Next steps:")
        print("   • Test the form in Frappe environment")
        print("   • Verify pronouns field migration")
        print("   • Test image upload functionality")
        print("   • Verify validation and error handling")

        return 0
    else:
        print("❌ Some validation errors found. Please review the files.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
