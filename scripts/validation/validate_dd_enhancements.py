#!/usr/bin/env python3
"""
DD Enhancement Validation Script
Validates syntax and structure of DD enhancement files without requiring Frappe
"""

import ast
import os
import sys


class DDEnhancementValidator:
    """Validates DD enhancement files for syntax and structure"""

    def __init__(self):
        self.results = {
            "files_checked": 0,
            "syntax_errors": 0,
            "structure_issues": 0,
            "passed": 0,
            "details": [],
        }

    def validate_python_syntax(self, file_path):
        """Validate Python file syntax"""
        try:
            with open(file_path, "r") as f:
                content = f.read()

            # Parse the Python code
            ast.parse(content, filename=file_path)
            return True, "Syntax OK"

        except SyntaxError as e:
            return False, f"Syntax Error: {e.msg} at line {e.lineno}"
        except Exception as e:
            return False, f"Parse Error: {str(e)}"

    def validate_test_file_structure(self, file_path):
        """Validate test file has proper structure"""
        try:
            with open(file_path, "r") as f:
                content = f.read()

            # Check for required imports
            required_imports = ["unittest", "frappe"]
            missing_imports = []
            for imp in required_imports:
                if f"import {imp}" not in content:
                    missing_imports.append(imp)

            # Check for test classes
            test_classes = []
            lines = content.split("\n")
            for line in lines:
                if line.strip().startswith("class Test") and "TestCase" in line:
                    class_name = line.split("class ")[1].split("(")[0]
                    test_classes.append(class_name)

            # Check for test methods
            test_methods = []
            for line in lines:
                if line.strip().startswith("def test_"):
                    method_name = line.split("def ")[1].split("(")[0]
                    test_methods.append(method_name)

            issues = []
            if missing_imports:
                issues.append(f"Missing imports: {', '.join(missing_imports)}")
            if not test_classes:
                issues.append("No test classes found")
            if not test_methods:
                issues.append("No test methods found")

            return (
                len(issues) == 0,
                issues,
                {
                    "test_classes": test_classes,
                    "test_methods": test_methods,
                    "method_count": len(test_methods),
                },
            )

        except Exception as e:
            return False, [f"Structure validation error: {str(e)}"], {}

    def validate_security_enhancements(self, file_path):
        """Validate security enhancement file structure"""
        try:
            with open(file_path, "r") as f:
                content = f.read()

            # Check for required classes
            required_classes = [
                "MemberIdentityValidator",
                "DDSecurityAuditLogger",
                "DDConflictResolutionManager",
            ]

            missing_classes = []
            found_classes = []

            for class_name in required_classes:
                if f"class {class_name}" in content:
                    found_classes.append(class_name)
                else:
                    missing_classes.append(class_name)

            # Check for API functions
            api_functions = []
            lines = content.split("\n")
            for line in lines:
                if "@frappe.whitelist()" in line:
                    # Next line should be function definition
                    next_line_idx = lines.index(line) + 1
                    if next_line_idx < len(lines):
                        next_line = lines[next_line_idx]
                        if next_line.strip().startswith("def "):
                            func_name = next_line.split("def ")[1].split("(")[0]
                            api_functions.append(func_name)

            issues = []
            if missing_classes:
                issues.append(f"Missing classes: {', '.join(missing_classes)}")

            return (
                len(issues) == 0,
                issues,
                {
                    "found_classes": found_classes,
                    "api_functions": api_functions,
                    "class_count": len(found_classes),
                    "api_count": len(api_functions),
                },
            )

        except Exception as e:
            return False, [f"Security validation error: {str(e)}"], {}

    def validate_javascript_syntax(self, file_path):
        """Basic JavaScript syntax validation"""
        try:
            with open(file_path, "r") as f:
                content = f.read()

            # Basic syntax checks
            issues = []

            # Check for balanced braces
            brace_count = content.count("{") - content.count("}")
            if brace_count != 0:
                issues.append(f"Unbalanced braces: {brace_count}")

            # Check for balanced parentheses
            paren_count = content.count("(") - content.count(")")
            if paren_count != 0:
                issues.append(f"Unbalanced parentheses: {paren_count}")

            # Check for required classes
            required_classes = ["DDBatchManagementDashboard", "BatchCreationWizard"]
            missing_classes = []
            found_classes = []

            for class_name in required_classes:
                if f"class {class_name}" in content:
                    found_classes.append(class_name)
                else:
                    missing_classes.append(class_name)

            if missing_classes:
                issues.append(f"Missing JS classes: {', '.join(missing_classes)}")

            return (
                len(issues) == 0,
                issues,
                {"found_classes": found_classes, "js_class_count": len(found_classes)},
            )

        except Exception as e:
            return False, [f"JavaScript validation error: {str(e)}"], {}

    def validate_file(self, file_path, file_type):
        """Validate a single file based on its type"""
        file_name = os.path.basename(file_path)
        self.results["files_checked"] += 1

        print(f"📁 Validating: {file_name}")

        if not os.path.exists(file_path):
            print(f"   ❌ File not found")
            self.results["syntax_errors"] += 1
            return False

        # Basic syntax validation
        if file_type == "python":
            syntax_ok, syntax_msg = self.validate_python_syntax(file_path)
            if not syntax_ok:
                print(f"   ❌ {syntax_msg}")
                self.results["syntax_errors"] += 1
                return False
            else:
                print(f"   ✅ Python syntax: OK")

        elif file_type == "javascript":
            syntax_ok, syntax_issues, details = self.validate_javascript_syntax(file_path)
            if not syntax_ok:
                print(f"   ❌ JavaScript issues: {', '.join(syntax_issues)}")
                self.results["syntax_errors"] += 1
                return False
            else:
                print(f"   ✅ JavaScript syntax: OK")
                print(f"      Classes found: {details.get('js_class_count', 0)}")

        # Specific structure validation
        if "test_dd_batch_edge_cases" in file_name:
            structure_ok, issues, details = self.validate_test_file_structure(file_path)
            if not structure_ok:
                print(f"   ⚠️  Structure issues: {', '.join(issues)}")
                self.results["structure_issues"] += 1
            else:
                print(f"   ✅ Test structure: OK")
                print(f"      Test classes: {details.get('method_count', 0)} methods")

        elif "dd_security_enhancements" in file_name:
            structure_ok, issues, details = self.validate_security_enhancements(file_path)
            if not structure_ok:
                print(f"   ⚠️  Structure issues: {', '.join(issues)}")
                self.results["structure_issues"] += 1
            else:
                print(f"   ✅ Security structure: OK")
                print(
                    f"      Classes: {details.get('class_count', 0)}, API functions: {details.get('api_count', 0)}"
                )

        print(f"   ✅ {file_name} validation completed")
        self.results["passed"] += 1
        return True

    def run_validation(self):
        """Run validation on all DD enhancement files"""
        print("🔍 DD Enhancement File Validation")
        print("=" * 50)

        # Files to validate
        files_to_check = [
            {"path": "verenigingen/utils/dd_security_enhancements.py", "type": "python", "required": True},
            {
                "path": "verenigingen/tests/test_dd_batch_edge_cases_comprehensive.py",
                "type": "python",
                "required": True,
            },
            {
                "path": "verenigingen/public/js/dd_batch_management_enhanced.js",
                "type": "javascript",
                "required": True,
            },
            {"path": "run_dd_batch_comprehensive_tests.py", "type": "python", "required": False},
        ]

        success_count = 0

        for file_info in files_to_check:
            success = self.validate_file(file_info["path"], file_info["type"])
            if success:
                success_count += 1
            elif file_info["required"]:
                print(f"   🚨 Required file failed validation")
            print()  # Add spacing

        # Summary
        print("📊 Validation Summary")
        print("-" * 30)
        print(f"Files checked: {self.results['files_checked']}")
        print(f"✅ Passed: {self.results['passed']}")
        print(f"❌ Syntax errors: {self.results['syntax_errors']}")
        print(f"⚠️  Structure issues: {self.results['structure_issues']}")

        overall_success = self.results["syntax_errors"] == 0 and success_count >= len(
            [f for f in files_to_check if f["required"]]
        )

        if overall_success:
            print("\n🎉 All validations passed! Files are ready for Frappe testing.")
        else:
            print("\n💥 Some validations failed. Please fix issues before running in Frappe.")

        return overall_success


def main():
    """Main validation entry point"""
    validator = DDEnhancementValidator()

    try:
        success = validator.run_validation()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⏹️  Validation interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Validation error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
