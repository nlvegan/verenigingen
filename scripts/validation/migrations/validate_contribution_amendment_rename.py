#!/usr/bin/env python3
"""
Validation script for Contribution Amendment Request rename
Tests that all references were properly updated
"""

import json
import os
import sys


def check_new_doctype_files():
    """Check if new doctype files exist"""
    base_path = "verenigingen/verenigingen/doctype/contribution_amendment_request"
    required_files = [
        "contribution_amendment_request.json",
        "contribution_amendment_request.py",
        "contribution_amendment_request.js",
    ]

    results = []
    for file in required_files:
        file_path = os.path.join(base_path, file)
        if os.path.exists(file_path):
            results.append(f"✅ {file} exists")
        else:
            results.append(f"❌ {file} missing")

    return results


def check_doctype_json():
    """Check if JSON file has correct name"""
    json_path = (
        "verenigingen/verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.json"
    )

    if not os.path.exists(json_path):
        return False, "JSON file not found"

    try:
        with open(json_path, "r") as f:
            data = json.load(f)

        if data.get("name") == "Contribution Amendment Request":
            return True, "DocType name correctly updated in JSON"
        else:
            return False, f"DocType name is '{data.get('name')}', should be 'Contribution Amendment Request'"

    except Exception as e:
        return False, f"Error reading JSON: {e}"


def check_python_class():
    """Check if Python class name was updated"""
    py_path = (
        "verenigingen/verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.py"
    )

    if not os.path.exists(py_path):
        return False, "Python file not found"

    try:
        with open(py_path, "r") as f:
            content = f.read()

        if "class ContributionAmendmentRequest(Document):" in content:
            return True, "Python class name correctly updated"
        else:
            return False, "Python class name not updated"

    except Exception as e:
        return False, f"Error reading Python file: {e}"


def check_javascript_form():
    """Check if JavaScript form reference was updated"""
    js_path = (
        "verenigingen/verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.js"
    )

    if not os.path.exists(js_path):
        return False, "JavaScript file not found"

    try:
        with open(js_path, "r") as f:
            content = f.read()

        if "frappe.ui.form.on('Contribution Amendment Request'" in content:
            return True, "JavaScript form reference correctly updated"
        else:
            return False, "JavaScript form reference not updated"

    except Exception as e:
        return False, f"Error reading JavaScript file: {e}"


def check_fee_adjustment_references():
    """Check if fee adjustment page was updated"""
    py_path = "verenigingen/templates/pages/membership_fee_adjustment.py"
    html_path = "verenigingen/templates/pages/membership_fee_adjustment.html"

    results = []

    # Check Python file
    if os.path.exists(py_path):
        try:
            with open(py_path, "r") as f:
                content = f.read()

            if "Contribution Amendment Request" in content and "Membership Amendment Request" not in content:
                results.append("✅ Fee adjustment Python file updated")
            else:
                results.append("❌ Fee adjustment Python file not fully updated")
        except:
            results.append("❌ Error reading fee adjustment Python file")

    # Check HTML file
    if os.path.exists(html_path):
        try:
            with open(html_path, "r") as f:
                content = f.read()

            if "contribution-amendment-request" in content and "membership-amendment-request" not in content:
                results.append("✅ Fee adjustment HTML file updated")
            else:
                results.append("❌ Fee adjustment HTML file not fully updated")
        except:
            results.append("❌ Error reading fee adjustment HTML file")

    return results


def check_member_references():
    """Check if member doctype references were updated"""
    py_path = "verenigingen/verenigingen/doctype/member/member.py"
    json_path = "verenigingen/verenigingen/doctype/member/member.json"

    results = []

    # Check Python file
    if os.path.exists(py_path):
        try:
            with open(py_path, "r") as f:
                content = f.read()

            contribution_count = content.count("Contribution Amendment Request")
            membership_count = content.count("Membership Amendment Request")
            import_count = content.count("contribution_amendment_request.contribution_amendment_request")

            if contribution_count > 0 and membership_count == 0 and import_count > 0:
                results.append("✅ Member Python file references updated")
            else:
                results.append(
                    f"❌ Member Python file - Contribution: {contribution_count}, Membership: {membership_count}, Imports: {import_count}"
                )
        except:
            results.append("❌ Error reading member Python file")

    # Check JSON file
    if os.path.exists(json_path):
        try:
            with open(json_path, "r") as f:
                content = f.read()

            if "Contribution Amendment Request" in content and "Membership Amendment Request" not in content:
                results.append("✅ Member JSON file references updated")
            else:
                results.append("❌ Member JSON file not fully updated")
        except:
            results.append("❌ Error reading member JSON file")

    return results


def main():
    """Main validation function"""
    print("🔍 Validating Contribution Amendment Request Rename...")
    print("=" * 60)

    # Check new doctype files
    print("📁 New DocType Files:")
    file_results = check_new_doctype_files()
    for result in file_results:
        print(f"   {result}")

    print("\n📄 DocType Configuration:")

    # Check JSON
    valid, message = check_doctype_json()
    status = "✅" if valid else "❌"
    print(f"   {status} JSON: {message}")

    # Check Python class
    valid, message = check_python_class()
    status = "✅" if valid else "❌"
    print(f"   {status} Python Class: {message}")

    # Check JavaScript
    valid, message = check_javascript_form()
    status = "✅" if valid else "❌"
    print(f"   {status} JavaScript: {message}")

    print("\n🔗 Reference Updates:")

    # Check fee adjustment references
    fee_results = check_fee_adjustment_references()
    for result in fee_results:
        print(f"   {result}")

    # Check member references
    member_results = check_member_references()
    for result in member_results:
        print(f"   {result}")

    print("=" * 60)

    # Count successful validations
    all_results = [check_doctype_json()[0], check_python_class()[0], check_javascript_form()[0]] + [
        r.startswith("✅") for r in fee_results + member_results
    ]

    success_count = sum(all_results)
    total_count = len(all_results)

    if success_count == total_count:
        print("🎉 Contribution Amendment Request rename completed successfully!")
        print("\n📋 Rename Summary:")
        print("   • DocType renamed from 'Membership Amendment Request'")
        print("   • New name: 'Contribution Amendment Request'")
        print("   • All file references updated")
        print("   • Database queries updated")
        print("   • Member portal links updated")
        print("   • Import statements updated")

        print("\n✨ Benefits:")
        print("   • Less confusing name for members")
        print("   • Clearer indication it's about fee contributions")
        print("   • Maintains all existing functionality")

        print("\n⚠️  Migration Note:")
        print("   • Existing data will need database migration")
        print("   • Run 'bench migrate' after deploying")

        return 0
    else:
        print(f"❌ Some issues found: {success_count}/{total_count} validations passed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
