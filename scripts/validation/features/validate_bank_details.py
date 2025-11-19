#!/usr/bin/env python3
"""
Validation script for bank details functionality
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


def main():
    """Main validation function"""
    print("🔍 Validating Bank Details Implementation...")
    print("=" * 50)

    files_to_validate = [
        ("verenigingen/templates/pages/bank_details.py", "python"),
        ("verenigingen/templates/pages/bank_details.html", "html"),
        ("verenigingen/templates/pages/bank_details_confirm.py", "python"),
        ("verenigingen/templates/pages/bank_details_confirm.html", "html"),
        ("verenigingen/templates/pages/bank_details_success.py", "python"),
        ("verenigingen/templates/pages/bank_details_success.html", "html"),
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

    print("=" * 50)

    # Check for required functions in Python files
    python_files_functions = {
        "verenigingen/templates/pages/bank_details.py": [
            "get_context",
            "update_bank_details",
            "has_website_permission",
        ],
        "verenigingen/templates/pages/bank_details_confirm.py": [
            "get_context",
            "process_bank_details_update",
            "has_website_permission",
        ],
        "verenigingen/templates/pages/bank_details_success.py": ["get_context", "has_website_permission"],
    }

    for file_path, required_functions in python_files_functions.items():
        try:
            with open(file_path, "r") as f:
                content = f.read()

            missing_functions = []
            for func in required_functions:
                if f"def {func}" not in content:
                    missing_functions.append(func)

            if missing_functions:
                print(f"⚠️  {file_path} - Missing functions: {missing_functions}")
                all_valid = False
            else:
                print(f"✅ {file_path} - All required functions present")

        except Exception as e:
            print(f"❌ {file_path} - Error checking functions: {e}")
            all_valid = False

    print("=" * 50)

    if all_valid:
        print("🎉 All bank details files are valid!")
        print("\n📋 Implementation Summary:")
        print("   • Bank details form with IBAN validation")
        print("   • Confirmation page with SEPA mandate handling")
        print("   • Success page with next steps")
        print("   • Integration with existing SEPA mandate system")
        print("   • Permission-based access control")
        print("\n🔗 Pages created:")
        print("   • /bank_details - Main form")
        print("   • /bank_details_confirm - Confirmation")
        print("   • /bank_details_success - Success page")
        print("\n💡 Next steps:")
        print("   • Test the flow in the Frappe environment")
        print("   • Verify SEPA mandate integration")
        print("   • Check member dashboard link")

        return 0
    else:
        print("❌ Some validation errors found. Please review the files.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
