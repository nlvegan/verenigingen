#!/usr/bin/env python3
"""
Automated Batch API Security Implementation
Secures all remaining unprotected @frappe.whitelist functions with appropriate decorators
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


def load_unprotected_files() -> List[str]:
    """Load list of unprotected files from the comprehensive report"""
    with open("comprehensive_api_security_report.json", "r") as f:
        report = json.load(f)

    unprotected_files = []
    for risk_level in ["MEDIUM", "LOW"]:  # Skip CRITICAL and HIGH as they're done
        for file_info in report["unprotected_files_detail"][risk_level]:
            unprotected_files.append(file_info["file"])

    return unprotected_files


def classify_function_type(function_name: str, file_path: str) -> Tuple[str, str]:
    """Classify function to determine appropriate security decorator"""

    # Financial/Payment functions
    if any(
        keyword in function_name.lower()
        for keyword in ["payment", "sepa", "financial", "invoice", "billing", "mandate"]
    ):
        return "critical_api", "OperationType.FINANCIAL"

    # Admin functions
    if any(
        keyword in function_name.lower() for keyword in ["admin", "config", "system", "workspace", "security"]
    ):
        return "critical_api", "OperationType.ADMIN"

    # Member data functions
    if any(keyword in function_name.lower() for keyword in ["member", "customer", "user", "profile"]):
        return "high_security_api", "OperationType.MEMBER_DATA"

    # Debug/Test functions (low security)
    if any(
        keyword in function_name.lower() for keyword in ["debug", "test_", "validate_", "check_", "monitor"]
    ):
        return "standard_api", "OperationType.UTILITY"

    # Performance/Management functions
    if any(
        keyword in function_name.lower()
        for keyword in ["performance", "job_", "status", "coverage", "measurement"]
    ):
        return "standard_api", "OperationType.UTILITY"

    # Reporting functions
    if any(keyword in function_name.lower() for keyword in ["report", "analytics", "dashboard"]):
        return "standard_api", "OperationType.REPORTING"

    # Default to standard security for other functions
    return "standard_api", "OperationType.UTILITY"


def extract_function_names(file_path: str) -> List[str]:
    """Extract @frappe.whitelist function names from file"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find function names that follow @frappe.whitelist
        function_matches = re.findall(r"@frappe\.whitelist\(\)\s*\ndef\s+(\w+)", content, re.MULTILINE)

        return function_matches
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return []


def add_security_framework_to_file(file_path: str) -> bool:
    """Add security framework import to file if not present"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check if security framework is already imported
        if "from verenigingen.utils.security.api_security_framework import" in content:
            return True  # Already has security framework

        # Find the import section
        import_match = re.search(r"(import frappe[^\n]*\n)", content)
        if not import_match:
            return False  # Can't find import section

        # Add security framework import after frappe import
        import_line = import_match.group(1)
        security_import = "from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api, standard_api\n"

        new_content = content.replace(
            import_line, import_line + security_import, 1  # Replace only first occurrence
        )

        # Write back to file
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return True

    except Exception as e:
        print(f"Error adding security framework to {file_path}: {e}")
        return False


def add_security_decorators_to_file(file_path: str) -> Dict[str, Any]:
    """Add security decorators to all @frappe.whitelist functions in file"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find all @frappe.whitelist functions
        pattern = r"(@frappe\.whitelist\(\)\s*\n)(def\s+(\w+).*?:)"
        matches = list(re.finditer(pattern, content, re.MULTILINE))

        if not matches:
            return {"success": False, "message": "No @frappe.whitelist functions found"}

        # Process matches in reverse order to avoid position shifts
        functions_processed = []
        new_content = content

        for match in reversed(matches):
            whitelist_decorator = match.group(1)
            function_def = match.group(2)
            function_name = match.group(3)

            # Determine appropriate security decorator
            decorator_type, operation_type = classify_function_type(function_name, file_path)

            # Create new decorator combination
            security_decorator = f"@{decorator_type}(operation_type={operation_type})"
            new_decorators = f"{whitelist_decorator}{security_decorator}\n{function_def}"

            # Replace in content
            old_decorators = whitelist_decorator + function_def
            new_content = new_content.replace(old_decorators, new_decorators, 1)

            functions_processed.append(
                {"function": function_name, "decorator": decorator_type, "operation_type": operation_type}
            )

        # Write back to file
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return {
            "success": True,
            "functions_processed": len(functions_processed),
            "details": functions_processed,
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


def secure_file(file_path: str) -> Dict[str, Any]:
    """Secure a single API file with security framework"""
    result = {"file": file_path, "success": False, "functions_secured": 0, "details": [], "errors": []}

    try:
        # Step 1: Add security framework import
        if not add_security_framework_to_file(file_path):
            result["errors"].append("Failed to add security framework import")
            return result

        # Step 2: Add security decorators to functions
        decorator_result = add_security_decorators_to_file(file_path)

        if decorator_result["success"]:
            result["success"] = True
            result["functions_secured"] = decorator_result["functions_processed"]
            result["details"] = decorator_result["details"]
        else:
            result["errors"].append(decorator_result["message"])

        return result

    except Exception as e:
        result["errors"].append(str(e))
        return result


def main():
    print("🚀 Automated Batch API Security Implementation")
    print("=" * 55)

    # Load unprotected files
    print("📊 Loading unprotected files list...")
    try:
        unprotected_files = load_unprotected_files()
        print(f"Found {len(unprotected_files)} files to secure")
    except Exception as e:
        print(f"❌ Error loading unprotected files: {e}")
        return

    # Process each file
    results = {"secured": [], "failed": [], "total_functions": 0}

    for i, file_path in enumerate(unprotected_files, 1):
        print(f"\n[{i}/{len(unprotected_files)}] Securing: {os.path.basename(file_path)}")

        result = secure_file(file_path)

        if result["success"]:
            print(f"  ✅ Secured {result['functions_secured']} functions")
            results["secured"].append(result)
            results["total_functions"] += result["functions_secured"]
        else:
            print(f"  ❌ Failed: {'; '.join(result['errors'])}")
            results["failed"].append(result)

    # Generate summary
    print("\n📊 BATCH SECURITY IMPLEMENTATION SUMMARY")
    print("=" * 45)
    print(f"Files Processed: {len(unprotected_files)}")
    print(f"Files Secured: {len(results['secured'])} ✅")
    print(f"Files Failed: {len(results['failed'])} ❌")
    print(f"Total Functions Secured: {results['total_functions']}")
    print(f"Success Rate: {(len(results['secured']) / len(unprotected_files) * 100):.1f}%")

    # Save detailed results
    with open("batch_security_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\n📝 Detailed results saved to: batch_security_results.json")

    if results["failed"]:
        print(f"\n⚠️  {len(results['failed'])} files failed - check batch_security_results.json for details")
    else:
        print("\n🎉 All files secured successfully!")


if __name__ == "__main__":
    main()
