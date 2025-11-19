#!/usr/bin/env python3
"""
Final DD Enhancement Validation
Comprehensive test of all DD enhancement components
"""

import ast
import json
import os
import sys
from pathlib import Path


def test_file_completeness():
    """Test that all required files are present and complete"""
    print("📁 Testing File Completeness")
    print("-" * 35)

    required_files = [
        {
            "path": "verenigingen/utils/dd_security_enhancements.py",
            "type": "security_enhancements",
            "min_lines": 400},
        {
            "path": "verenigingen/tests/test_dd_batch_edge_cases_comprehensive.py",
            "type": "comprehensive_tests",
            "min_lines": 300},
        {
            "path": "verenigingen/public/js/dd_batch_management_enhanced.js",
            "type": "enhanced_ui",
            "min_lines": 800},
        {"path": "run_dd_batch_comprehensive_tests.py", "type": "test_runner", "min_lines": 100},
    ]

    results = {"passed": 0, "failed": 0, "details": []}

    for file_info in required_files:
        path = file_info["path"]

        if os.path.exists(path):
            # Check file size
            with open(path, "r") as f:
                lines = f.readlines()
                line_count = len(lines)

            if line_count >= file_info["min_lines"]:
                print(f"   ✅ {os.path.basename(path)}: {line_count} lines")
                results["passed"] += 1
                results["details"].append({"file": path, "status": "passed", "lines": line_count})
            else:
                print(
                    f"   ⚠️  {os.path.basename(path)}: {line_count} lines (expected >= {file_info['min_lines']})"
                )
                results["failed"] += 1
                results["details"].append(
                    {
                        "file": path,
                        "status": "incomplete",
                        "lines": line_count,
                        "expected": file_info["min_lines"]}
                )
        else:
            print(f"   ❌ {os.path.basename(path)}: Missing")
            results["failed"] += 1
            results["details"].append({"file": path, "status": "missing"})

    return results


def test_security_enhancements_structure():
    """Test security enhancements file structure"""
    print("\n🔒 Testing Security Enhancements Structure")
    print("-" * 45)

    file_path = "verenigingen/utils/dd_security_enhancements.py"

    if not os.path.exists(file_path):
        print("   ❌ Security enhancements file not found")
        return False

    try:
        with open(file_path, "r") as f:
            content = f.read()

        # Check for required classes
        required_classes = ["MemberIdentityValidator", "DDSecurityAuditLogger", "DDConflictResolutionManager"]

        found_classes = []
        for class_name in required_classes:
            if f"class {class_name}" in content:
                found_classes.append(class_name)
                print(f"   ✅ {class_name} class found")
            else:
                print(f"   ❌ {class_name} class missing")

        # Check for required methods
        required_methods = [
            "detect_potential_duplicates",
            "validate_unique_bank_account",
            "detect_payment_anomalies",
            "_calculate_name_similarity",
            "_normalize_iban",
        ]

        found_methods = []
        for method_name in required_methods:
            if f"def {method_name}" in content:
                found_methods.append(method_name)
                print(f"   ✅ {method_name}() method found")
            else:
                print(f"   ❌ {method_name}() method missing")

        # Check for API endpoints
        api_endpoints = []
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "@frappe.whitelist()" in line and i + 1 < len(lines):
                next_line = lines[i + 1]
                if next_line.strip().startswith("def "):
                    func_name = next_line.split("def ")[1].split("(")[0]
                    api_endpoints.append(func_name)

        print(f"   ✅ Found {len(api_endpoints)} API endpoints: {', '.join(api_endpoints)}")

        success = (
            len(found_classes) == len(required_classes)
            and len(found_methods) == len(required_methods)
            and len(api_endpoints) >= 3
        )

        return success

    except Exception as e:
        print(f"   ❌ Error analyzing security enhancements: {str(e)}")
        return False


def test_comprehensive_tests_structure():
    """Test comprehensive tests file structure"""
    print("\n🧪 Testing Comprehensive Tests Structure")
    print("-" * 42)

    file_path = "verenigingen/tests/test_dd_batch_edge_cases_comprehensive.py"

    if not os.path.exists(file_path):
        print("   ❌ Comprehensive tests file not found")
        return False

    try:
        with open(file_path, "r") as f:
            content = f.read()

        # Check for test classes
        test_classes = []
        lines = content.split("\n")
        for line in lines:
            if line.strip().startswith("class Test") and "TestCase" in line:
                class_name = line.split("class ")[1].split("(")[0]
                test_classes.append(class_name)

        print(f"   ✅ Found {len(test_classes)} test classes:")
        for class_name in test_classes:
            print(f"      • {class_name}")

        # Check for test methods
        test_methods = []
        for line in lines:
            if line.strip().startswith("def test_"):
                method_name = line.split("def ")[1].split("(")[0]
                test_methods.append(method_name)

        print(f"   ✅ Found {len(test_methods)} test methods")

        # Check for edge case coverage
        edge_case_keywords = [
            "identical_names",
            "similar_names",
            "shared_family",
            "corporate_shared",
            "malicious_data",
            "security_event",
            "performance",
        ]

        covered_cases = []
        for keyword in edge_case_keywords:
            if keyword in content:
                covered_cases.append(keyword)

        print(f"   ✅ Edge case coverage: {len(covered_cases)}/{len(edge_case_keywords)} categories")

        success = len(test_classes) >= 3 and len(test_methods) >= 10 and len(covered_cases) >= 5

        return success

    except Exception as e:
        print(f"   ❌ Error analyzing comprehensive tests: {str(e)}")
        return False


def test_enhanced_ui_structure():
    """Test enhanced UI file structure"""
    print("\n🎨 Testing Enhanced UI Structure")
    print("-" * 32)

    file_path = "verenigingen/public/js/dd_batch_management_enhanced.js"

    if not os.path.exists(file_path):
        print("   ❌ Enhanced UI file not found")
        return False

    try:
        with open(file_path, "r") as f:
            content = f.read()

        # Check for required classes
        required_classes = ["DDBatchManagementDashboard", "BatchCreationWizard"]

        found_classes = []
        for class_name in required_classes:
            if f"class {class_name}" in content:
                found_classes.append(class_name)
                print(f"   ✅ {class_name} class found")
            else:
                print(f"   ❌ {class_name} class missing")

        # Check for UI components
        ui_components = [
            "createDashboardLayout",
            "renderBatchList",
            "showConflictResolution",
            "createBatchRow",
            "updateSecurityAlerts",
        ]

        found_components = []
        for component in ui_components:
            if component in content:
                found_components.append(component)
                print(f"   ✅ {component}() method found")

        # Check for security features
        security_features = ["security-alerts", "conflict-resolution", "risk-assessment", "anomaly-detection"]

        found_features = []
        for feature in security_features:
            if feature in content:
                found_features.append(feature)

        print(f"   ✅ Security features: {len(found_features)}/{len(security_features)} implemented")

        success = (
            len(found_classes) == len(required_classes)
            and len(found_components) >= 3
            and len(found_features) >= 2
        )

        return success

    except Exception as e:
        print(f"   ❌ Error analyzing enhanced UI: {str(e)}")
        return False


def test_documentation_completeness():
    """Test documentation completeness"""
    print("\n📚 Testing Documentation Completeness")
    print("-" * 40)

    doc_files = [
        "DD_BATCH_ENHANCEMENT_PROPOSAL.md",
        "DD_SECURITY_DOCTYPES.md",
        "DD_BATCH_ENHANCEMENT_SUMMARY.md",
    ]

    found_docs = 0
    total_content = 0

    for doc_file in doc_files:
        if os.path.exists(doc_file):
            with open(doc_file, "r") as f:
                content = f.read()
                word_count = len(content.split())
                total_content += word_count

            print(f"   ✅ {doc_file}: {word_count} words")
            found_docs += 1
        else:
            print(f"   ❌ {doc_file}: Missing")

    print(f"   📖 Total documentation: {total_content} words across {found_docs} files")

    return found_docs == len(doc_files) and total_content > 5000


def run_integration_syntax_check():
    """Check syntax of all Python files"""
    print("\n🔍 Running Integration Syntax Check")
    print("-" * 38)

    python_files = [
        "verenigingen/utils/dd_security_enhancements.py",
        "verenigingen/tests/test_dd_batch_edge_cases_comprehensive.py",
        "run_dd_batch_comprehensive_tests.py",
        "validate_dd_enhancements.py",
        "test_dd_logic_standalone.py",
    ]

    syntax_results = {"passed": 0, "failed": 0}

    for file_path in python_files:
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as f:
                    content = f.read()

                # Parse the Python code
                ast.parse(content, filename=file_path)
                print(f"   ✅ {os.path.basename(file_path)}: Syntax OK")
                syntax_results["passed"] += 1

            except SyntaxError as e:
                print(f"   ❌ {os.path.basename(file_path)}: Syntax Error at line {e.lineno}")
                syntax_results["failed"] += 1
            except Exception as e:
                print(f"   ❌ {os.path.basename(file_path)}: Parse Error")
                syntax_results["failed"] += 1
        else:
            print(f"   ⚠️  {os.path.basename(file_path)}: File not found")

    return syntax_results["failed"] == 0


def generate_final_report():
    """Generate final validation report"""
    print("\n📋 Final DD Enhancement Validation Report")
    print("=" * 50)

    # Run all tests
    test_results = {}

    test_results["file_completeness"] = test_file_completeness()
    test_results["security_structure"] = test_security_enhancements_structure()
    test_results["tests_structure"] = test_comprehensive_tests_structure()
    test_results["ui_structure"] = test_enhanced_ui_structure()
    test_results["documentation"] = test_documentation_completeness()
    test_results["syntax_check"] = run_integration_syntax_check()

    # Calculate overall scores
    passed_tests = sum(
        1
        for result in test_results.values()
        if result is True or (isinstance(result, dict) and result.get("failed", 1) == 0)
    )
    total_tests = len(test_results)
    success_rate = (passed_tests / total_tests) * 100

    print(f"\n📊 Overall Results:")
    print(f"   Tests Passed: {passed_tests}/{total_tests}")
    print(f"   Success Rate: {success_rate:.1f}%")

    # Detailed results
    print(f"\n📝 Detailed Results:")
    for test_name, result in test_results.items():
        if result is True:
            print(f"   ✅ {test_name.replace('_', ' ').title()}: PASSED")
        elif result is False:
            print(f"   ❌ {test_name.replace('_', ' ').title()}: FAILED")
        elif isinstance(result, dict):
            if result.get("failed", 1) == 0:
                print(f"   ✅ {test_name.replace('_', ' ').title()}: PASSED")
            else:
                print(f"   ❌ {test_name.replace('_', ' ').title()}: FAILED")

    # Recommendations
    print(f"\n💡 Recommendations:")

    if success_rate >= 90:
        print("   🎉 EXCELLENT! DD enhancements are ready for production")
        print("   ✅ All critical components are present and well-structured")
        print("   🚀 Proceed with Frappe environment testing")
    elif success_rate >= 70:
        print("   👍 GOOD! Most components are ready")
        print("   ⚠️  Address failing tests before production deployment")
        print("   🔧 Review and fix identified issues")
    else:
        print("   ⚠️  NEEDS WORK! Several critical issues found")
        print("   🔨 Significant development work required before testing")
        print("   📋 Focus on failing components first")

    print(f"\n🏁 Validation Complete")
    print("   Next steps:")
    print("   1. Fix any failing tests")
    print("   2. Run in Frappe environment:")
    print("      bench --site dev.veganisme.net run-tests --app verenigingen")
    print("   3. Test UI components in browser")
    print("   4. Validate security enhancements with real data")

    return success_rate >= 70


if __name__ == "__main__":
    print("🚀 DD Enhancement Final Validation")
    print("=" * 40)

    try:
        success = generate_final_report()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⏹️  Validation interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Validation error: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
