#!/usr/bin/env python3
"""
Fix for critical_api decorator error
This script will identify and fix any remaining issues with the critical_api decorator usage
"""

import os
import re
import shutil
from datetime import datetime


def backup_file(filepath):
    """Create a backup of a file before modifying it"""
    backup_path = f"{filepath}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(filepath, backup_path)
    return backup_path


def fix_dd_batch_scheduler():
    """Fix any potential issues in dd_batch_scheduler.py"""
    filepath = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api/dd_batch_scheduler.py"

    print(f"Checking {filepath}...")

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Check for any problematic patterns
    problematic_patterns = [
        r"@critical_api\s*\(\s*max_requests\s*=",
        r"@critical_api\s*\(\s*window_minutes\s*=",
        r"@.*_api\([^)]*max_requests",
        r"@.*_api\([^)]*window_minutes",
    ]

    issues_found = []
    for pattern in problematic_patterns:
        matches = re.finditer(pattern, content, re.MULTILINE | re.IGNORECASE)
        for match in matches:
            line_num = content[: match.start()].count("\n") + 1
            issues_found.append((line_num, match.group(), pattern))

    if issues_found:
        print(f"❌ Found {len(issues_found)} issues in {filepath}:")
        backup_path = backup_file(filepath)
        print(f"Created backup at: {backup_path}")

        # Fix the issues
        fixed_content = content
        for line_num, match_text, pattern in issues_found:
            print(f"  Line {line_num}: {match_text}")

            # Fix critical_api calls with old parameters
            if "critical_api" in match_text:
                # Replace with proper critical_api call
                if "operation_type=" not in match_text:
                    fixed_content = re.sub(
                        r"@critical_api\s*\([^)]*\)",
                        "@critical_api(operation_type=OperationType.FINANCIAL)",
                        fixed_content,
                    )
                else:
                    # Remove old parameters but keep operation_type
                    fixed_content = re.sub(
                        r"@critical_api\s*\(\s*([^,\)]*operation_type[^,\)]*)[^)]*\)",
                        r"@critical_api(\1)",
                        fixed_content,
                    )

        # Write the fixed content
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(fixed_content)

        print(f"✅ Fixed {len(issues_found)} issues in {filepath}")
        return True
    else:
        print("✅ No issues found")
        return False


def fix_import_statements():
    """Ensure import statements are correct"""
    filepath = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api/dd_batch_scheduler.py"

    print("Checking import statements...")

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Find the api_security_framework import line
    import_line_index = None
    for i, line in enumerate(lines):
        if "api_security_framework" in line and "import" in line:
            import_line_index = i
            break

    if import_line_index is not None:
        current_import = lines[import_line_index].strip()
        expected_import = "from verenigingen.utils.security.api_security_framework import critical_api, high_security_api, standard_api, OperationType"

        if current_import == expected_import:
            print("✅ Import statement is correct")
            return False
        else:
            print("❌ Import statement needs fixing:")
            print(f"  Current: {current_import}")
            print(f"  Expected: {expected_import}")

            # Fix the import
            backup_path = backup_file(filepath)
            print(f"Created backup at: {backup_path}")

            lines[import_line_index] = expected_import + "\n"

            with open(filepath, "w", encoding="utf-8") as f:
                f.writelines(lines)

            print("✅ Fixed import statement")
            return True
    else:
        print("❌ Could not find api_security_framework import")
        return False


def check_security_framework_definition():
    """Check that the security framework definition is correct"""
    framework_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/security/api_security_framework.py"
    )

    print(f"Checking {framework_path}...")

    with open(framework_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check that critical_api only accepts operation_type parameter
    critical_api_pattern = r"def critical_api\s*\(([^)]*)\):"
    match = re.search(critical_api_pattern, content)

    if match:
        params = match.group(1).strip()
        print(f"critical_api parameters: {params}")

        if "max_requests" in params or "window_minutes" in params:
            print("❌ critical_api definition contains old parameters")
            return False
        else:
            print("✅ critical_api definition is correct")
            return True
    else:
        print("❌ Could not find critical_api definition")
        return False


def clear_module_cache():
    """Clear any potential module cache issues"""
    print("Clearing module cache...")

    # Remove .pyc files
    os.system("find /home/frappe/frappe-bench/apps/verenigingen -name '*.pyc' -delete 2>/dev/null || true")

    # Remove __pycache__ directories
    os.system(
        "find /home/frappe/frappe-bench/apps/verenigingen -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true"
    )

    print("✅ Cleared module cache")


def main():
    """Main function to fix the critical_api decorator error"""
    print("API Security Framework Decorator Fix")
    print("=" * 50)

    fixes_applied = []

    # 1. Check and fix dd_batch_scheduler.py
    if fix_dd_batch_scheduler():
        fixes_applied.append("Fixed dd_batch_scheduler.py decorators")

    # 2. Check and fix import statements
    if fix_import_statements():
        fixes_applied.append("Fixed import statements")

    # 3. Check security framework definition
    if not check_security_framework_definition():
        fixes_applied.append("Security framework definition needs attention")

    # 4. Clear module cache
    clear_module_cache()
    fixes_applied.append("Cleared module cache")

    print("\n" + "=" * 50)
    print("SUMMARY:")

    if len(fixes_applied) > 1:  # More than just cache clearing
        print(f"Applied {len(fixes_applied)} fixes:")
        for fix in fixes_applied:
            print(f"  ✅ {fix}")
    else:
        print("✅ No code fixes needed - only cleared cache")

    print("\nNEXT STEPS:")
    print("1. Restart the Frappe application: bench restart")
    print("2. Check the error logs: bench --site [site-name] logs")
    print("3. Test the affected function:")
    print("   bench --site [site-name] console")
    print("   >>> from verenigingen.api.dd_batch_scheduler import daily_batch_optimization")
    print("   >>> daily_batch_optimization()")

    return len(fixes_applied) > 1


if __name__ == "__main__":
    main()
