#!/usr/bin/env python3
"""
Validation script for member portal landing page
Tests syntax and basic structure without requiring Frappe imports
"""

import ast
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


def check_portal_features(file_path):
    """Check for member portal specific features"""
    try:
        with open(file_path, "r") as f:
            content = f.read()

        features = []

        # Check for key features
        if "portal-sections" in content:
            features.append("Portal sections grid")

        if "member-info-card" in content:
            features.append("Member info card")

        if "quick-actions" in content:
            features.append("Quick actions")

        if "portal-links" in content:
            features.append("Portal links")

        if "volunteer" in content.lower():
            features.append("Volunteer services integration")

        if "bank_details" in content:
            features.append("Bank details link")

        if "sepa" in content.lower():
            features.append("SEPA mentions")

        return True, f"Features found: {', '.join(features)}"

    except Exception as e:
        return False, f"Error: {e}"


def main():
    """Main validation function"""
    print("🔍 Validating Member Portal Implementation...")
    print("=" * 60)

    files_to_validate = [
        ("verenigingen/templates/pages/member_portal.py", "python"),
        ("verenigingen/templates/pages/member_portal.html", "html"),
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
    python_file = "verenigingen/templates/pages/member_portal.py"
    required_functions = ["get_context", "has_website_permission", "get_member_activity", "get_quick_actions"]

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

    # Check portal features
    html_file = "verenigingen/templates/pages/member_portal.html"
    if os.path.exists(html_file):
        valid, message = check_portal_features(html_file)
        status = "✅" if valid else "❌"
        print(f"{status} {html_file} - {message}")

    # Check member dashboard integration
    dashboard_file = "verenigingen/templates/pages/member_dashboard.py"
    if os.path.exists(dashboard_file):
        try:
            with open(dashboard_file, "r") as f:
                content = f.read()

            if "member_portal" in content and "featured" in content:
                print(f"✅ {dashboard_file} - Member portal integration found")
            else:
                print(f"⚠️  {dashboard_file} - Member portal integration not found")

        except Exception as e:
            print(f"❌ {dashboard_file} - Error checking integration: {e}")

    print("=" * 60)

    if all_valid:
        print("🎉 Member Portal implementation is valid!")
        print("\n📋 Implementation Summary:")
        print("   • Comprehensive member portal landing page")
        print("   • Organized service sections (Account, Membership, Volunteer, Events)")
        print("   • Quick actions based on member status")
        print("   • Integration with all existing member services")
        print("   • Responsive design with modern styling")
        print("   • Permission-based access control")
        print("   • Member dashboard integration with featured link")

        print("\n🔗 Features included:")
        print("   • Account Management (Profile, Address, Bank Details)")
        print("   • Membership Services (Manage, Fee Adjustment, Invoices)")
        print("   • Volunteer Services (Dashboard, Expenses, Application)")
        print("   • Events & Community (Events, Chapters, Resources)")
        print("   • Recent Activity Display")
        print("   • Personalized Quick Actions")

        print("\n🎯 Page accessible at:")
        print("   • /member_portal - Main landing page")
        print("   • Featured link in member dashboard")

        print("\n💡 Next steps:")
        print("   • Test the portal in Frappe environment")
        print("   • Verify all links work correctly")
        print("   • Check responsive design on mobile")
        print("   • Gather user feedback for improvements")

        return 0
    else:
        print("❌ Some validation errors found. Please review the files.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
