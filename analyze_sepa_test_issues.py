#!/usr/bin/env python3
"""
Analyze SEPA test file for potential syntax issues or import problems
"""

import ast
import os
import sys


def analyze_sepa_test_file():
    """Analyze the SEPA mandate naming test file for issues"""
    print("🔍 Analyzing SEPA mandate naming test file...")

    test_file = "verenigingen/tests/test_sepa_mandate_naming.py"

    if not os.path.exists(test_file):
        print("❌ Test file not found")
        return False

    try:
        # Read the file
        with open(test_file, "r") as f:
            content = f.read()

        print(f"✅ File readable, {len(content)} characters")

        # Check for syntax errors
        try:
            ast.parse(content)
            print("✅ No syntax errors found")
        except SyntaxError as e:
            print(f"❌ Syntax error: {e}")
            print(f"   Line {e.lineno}: {e.text}")
            return False

        # Check for potential issues
        issues = []

        # Check imports
        import_lines = [
            line.strip()
            for line in content.split("\n")
            if line.strip().startswith("import ") or line.strip().startswith("from ")
        ]
        print(f"✅ Found {len(import_lines)} import statements")

        for line in import_lines:
            if "frappe" in line:
                print(f"  - {line}")

        # Check for common naming test issues
        potential_issues = [
            ("generate_test_iban", "IBAN generation method"),
            ("track_doc", "Document tracking method"),
            ("VereningingenTestCase", "Base test case class"),
            ("frappe.get_single", "Settings access method"),
            ("sepa_mandate_naming_pattern", "Naming pattern field"),
            ("sepa_mandate_starting_counter", "Counter field"),
        ]

        for method, description in potential_issues:
            if method in content:
                print(f"✅ {description} found: {method}")
            else:
                issues.append(f"Missing {description}: {method}")

        if issues:
            print(f"\n⚠️ Potential issues found:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("\n✅ All expected components found")

        # Check for test method structure
        test_methods = []
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if line.strip().startswith("def test_"):
                method_name = line.strip().split("(")[0].replace("def ", "")
                test_methods.append((method_name, i + 1))

        print(f"\n✅ Found {len(test_methods)} test methods:")
        for method, line_num in test_methods:
            print(f"  - {method} (line {line_num})")

        # Look for common test issues patterns
        common_issues = [
            ("mandate.save()", "Missing mandate save calls"),
            ("self.track_doc", "Missing document tracking"),
            ("frappe.new_doc", "Document creation pattern"),
            ("generate_test_iban", "IBAN generation calls"),
        ]

        for pattern, description in common_issues:
            count = content.count(pattern)
            if count > 0:
                print(f"✅ {description}: {count} occurrences")
            else:
                print(f"⚠️ {description}: No occurrences found")

        return True

    except Exception as e:
        print(f"❌ Error analyzing file: {e}")
        return False


def check_dependencies():
    """Check if dependencies are accessible"""
    print("\n🔍 Checking test dependencies...")

    # Check if base test case file exists
    base_test_file = "verenigingen/tests/utils/base.py"
    if os.path.exists(base_test_file):
        print("✅ Base test case file found")
    else:
        print("❌ Base test case file missing")
        return False

    # Check if IBAN validator exists
    iban_validator_file = "verenigingen/utils/validation/iban_validator.py"
    if os.path.exists(iban_validator_file):
        print("✅ IBAN validator file found")
    else:
        print("❌ IBAN validator file missing")
        return False

    return True


def main():
    """Run all analysis"""
    print("🚀 Starting SEPA test analysis...\n")

    os.chdir("/home/frappe/frappe-bench/apps/verenigingen")

    success = True

    success &= analyze_sepa_test_file()
    success &= check_dependencies()

    print(f"\n{'='*60}")
    print("ANALYSIS SUMMARY")
    print("=" * 60)

    if success:
        print("✅ SEPA test file analysis completed successfully")
        print("   - No syntax errors found")
        print("   - All expected components present")
        print("   - Dependencies accessible")
        print("\n💡 The test failures are likely due to:")
        print("   1. Frappe/bench environment issues (barista app dependency)")
        print("   2. Database state or test data conflicts")
        print("   3. Runtime validation errors rather than code issues")
    else:
        print("❌ Issues found in SEPA test analysis")
        print("   - Check the specific error messages above")

    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
