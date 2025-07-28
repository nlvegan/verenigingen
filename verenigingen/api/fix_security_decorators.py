#!/usr/bin/env python3
"""
Comprehensive Security Decorator Standardization Script

This script systematically fixes all import conflicts and standardizes
security decorator patterns across the API directory.
"""

import glob
import os
import re
from pathlib import Path

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, utility_api

# Operation type mapping based on function purpose
OPERATION_TYPE_MAPPING = {
    # Financial operations
    "payment": "OperationType.FINANCIAL",
    "invoice": "OperationType.FINANCIAL",
    "batch": "OperationType.FINANCIAL",
    "sepa": "OperationType.FINANCIAL",
    "mandate": "OperationType.FINANCIAL",
    "debit": "OperationType.FINANCIAL",
    "reconcil": "OperationType.FINANCIAL",
    # Member data operations
    "member": "OperationType.MEMBER_DATA",
    "application": "OperationType.MEMBER_DATA",
    "suspend": "OperationType.MEMBER_DATA",
    "terminate": "OperationType.MEMBER_DATA",
    "donor": "OperationType.MEMBER_DATA",
    "customer": "OperationType.MEMBER_DATA",
    # Administrative operations
    "toggle": "OperationType.ADMIN",
    "enable": "OperationType.ADMIN",
    "disable": "OperationType.ADMIN",
    "config": "OperationType.ADMIN",
    "setting": "OperationType.ADMIN",
    "admin": "OperationType.ADMIN",
    # Reporting operations
    "get_": "OperationType.REPORTING",
    "list_": "OperationType.REPORTING",
    "stat": "OperationType.REPORTING",
    "report": "OperationType.REPORTING",
    "dashboard": "OperationType.REPORTING",
    "analytics": "OperationType.REPORTING",
    # Utility operations
    "validate": "OperationType.UTILITY",
    "test": "OperationType.UTILITY",
    "check": "OperationType.UTILITY",
    "debug": "OperationType.UTILITY",
    "fix": "OperationType.UTILITY",
}


def determine_operation_type(function_name, function_content):
    """Determine the appropriate operation type based on function name and content"""

    function_name_lower = function_name.lower()
    content_lower = function_content.lower()

    # Check for direct matches in function name
    for keyword, op_type in OPERATION_TYPE_MAPPING.items():
        if keyword in function_name_lower:
            return op_type

    # Check content for clues
    if any(word in content_lower for word in ["payment", "invoice", "financial", "money", "batch"]):
        return "OperationType.FINANCIAL"
    elif any(word in content_lower for word in ["member", "application", "user"]):
        return "OperationType.MEMBER_DATA"
    elif any(word in content_lower for word in ["settings", "config", "admin"]):
        return "OperationType.ADMIN"
    elif any(word in content_lower for word in ["get", "list", "report", "dashboard"]):
        return "OperationType.REPORTING"
    else:
        return "OperationType.UTILITY"


def fix_single_file(file_path):
    """Fix imports and decorators in a single file"""

    with open(file_path, "r") as f:
        content = f.read()

    original_content = content

    # Step 1: Fix imports
    # Remove old import patterns
    old_patterns = [
        r"from verenigingen\.utils\.security\.authorization import.*",
        r"from verenigingen\.utils\.security\.rate_limiting import.*(?:critical_api|high_security_api|standard_api|utility_api|public_api).*",
    ]

    for pattern in old_patterns:
        content = re.sub(pattern, "", content)

    # Add correct import if decorators are used
    uses_decorators = any(
        decorator in content
        for decorator in [
            "@critical_api",
            "@high_security_api",
            "@standard_api",
            "@utility_api",
            "@public_api",
        ]
    )

    if uses_decorators:
        # Find where to insert import (after other imports)
        lines = content.split("\n")
        insert_index = 0

        for i, line in enumerate(lines):
            if line.strip().startswith("from") or line.strip().startswith("import"):
                insert_index = i + 1
            elif line.strip() and not line.strip().startswith("#") and not line.strip().startswith('"""'):
                break

        # Insert the correct import
        new_import = "from verenigingen.utils.security.api_security_framework import (\n    critical_api, high_security_api, standard_api, utility_api, public_api, OperationType\n)"

        lines.insert(insert_index, new_import)
        content = "\n".join(lines)

    # Step 2: Fix decorator patterns
    def fix_decorator(match):
        decorator_name = match.group(1)
        # old_params = match.group(2) if match.group(2) else ""  # Unused variable

        # Extract function name to determine operation type
        remaining_content = content[match.end() :]
        func_match = re.search(r"def\s+(\w+)\s*\(", remaining_content)

        if func_match:
            function_name = func_match.group(1)
            # Get some function content for analysis
            func_content = remaining_content[:500]  # First 500 chars
            op_type = determine_operation_type(function_name, func_content)

            return f"@{decorator_name}(operation_type={op_type})"
        else:
            return f"@{decorator_name}(operation_type=OperationType.UTILITY)"

    # Pattern to match decorators with old-style parameters
    decorator_pattern = r"@(critical_api|high_security_api|standard_api|utility_api|public_api)\s*\([^)]*\)"
    content = re.sub(decorator_pattern, fix_decorator, content)

    # Fix decorators without parameters
    decorator_pattern_simple = r"@(critical_api|high_security_api|standard_api|utility_api|public_api)(?!\()"

    def fix_simple_decorator(match):
        decorator_name = match.group(1)
        # Try to determine operation type from context
        return f"@{decorator_name}(operation_type=OperationType.UTILITY)"

    content = re.sub(decorator_pattern_simple, fix_simple_decorator, content)

    # Step 3: Clean up duplicate imports and empty lines
    lines = content.split("\n")
    cleaned_lines = []
    prev_line = ""

    for line in lines:
        # Skip duplicate empty lines
        if line.strip() == "" and prev_line.strip() == "":
            continue
        cleaned_lines.append(line)
        prev_line = line

    content = "\n".join(cleaned_lines)

    # Only write if content changed
    if content != original_content:
        with open(file_path, "w") as f:
            f.write(content)
        return True

    return False


@utility_api(operation_type=OperationType.UTILITY)
def main():
    """Fix all API files"""

    api_dir = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api"

    print("🔧 Starting comprehensive security decorator standardization...")

    files_fixed = 0
    files_processed = 0

    # Process all Python files in API directory
    for py_file in glob.glob(os.path.join(api_dir, "*.py")):
        if py_file.endswith("fix_security_decorators.py") or py_file.endswith("fix_security_imports.py"):
            continue

        files_processed += 1
        filename = os.path.basename(py_file)

        try:
            was_fixed = fix_single_file(py_file)
            if was_fixed:
                files_fixed += 1
                print(f"  ✅ Fixed {filename}")
            else:
                print(f"  ⏭️  {filename} (no changes needed)")
        except Exception as e:
            print(f"  ❌ Error fixing {filename}: {e}")

    print("\n📊 Summary:")
    print(f"  📁 Files processed: {files_processed}")
    print(f"  ✅ Files fixed: {files_fixed}")
    print("  🎉 Standardization complete!")

    return files_fixed


if __name__ == "__main__":
    main()
