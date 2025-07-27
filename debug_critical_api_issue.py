#!/usr/bin/env python3
"""
Debug script for critical_api decorator issue
"""

import os
import re
import sys


def check_for_old_decorator_patterns():
    """Check for old decorator patterns that might cause issues"""
    print("Checking for old decorator patterns...")

    api_dir = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api"

    old_patterns = [
        r"@critical_api\s*\(\s*max_requests\s*=",
        r"@high_security_api\s*\(\s*max_requests\s*=",
        r"@standard_api\s*\(\s*max_requests\s*=",
        r"@utility_api\s*\(\s*max_requests\s*=",
        r"@public_api\s*\(\s*max_requests\s*=",
        r"@.*_api\([^)]*max_requests",
        r"@.*_api\([^)]*window_minutes",
    ]

    found_issues = []

    for filename in os.listdir(api_dir):
        if filename.endswith(".py"):
            filepath = os.path.join(api_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()

                for pattern in old_patterns:
                    matches = re.finditer(pattern, content, re.MULTILINE)
                    for match in matches:
                        line_num = content[: match.start()].count("\n") + 1
                        found_issues.append(
                            {"file": filename, "line": line_num, "pattern": pattern, "match": match.group()}
                        )

            except Exception as e:
                print(f"Error reading {filename}: {e}")

    if found_issues:
        print(f"❌ Found {len(found_issues)} issues:")
        for issue in found_issues:
            print(f"  File: {issue['file']}, Line: {issue['line']}")
            print(f"    Pattern: {issue['pattern']}")
            print(f"    Match: {issue['match']}")
            print()
    else:
        print("✅ No old decorator patterns found")

    return found_issues


def check_dd_batch_scheduler_specifically():
    """Check dd_batch_scheduler.py specifically"""
    print("\nChecking dd_batch_scheduler.py specifically...")

    filepath = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api/dd_batch_scheduler.py"

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Look for all decorator lines
        decorator_lines = []
        for i, line in enumerate(lines, 1):
            if line.strip().startswith("@"):
                decorator_lines.append((i, line.strip()))

        print(f"Found {len(decorator_lines)} decorator lines:")
        for line_num, line in decorator_lines:
            print(f"  Line {line_num}: {line}")

        # Check for critical_api specifically
        critical_api_lines = [(num, line) for num, line in decorator_lines if "critical_api" in line]

        print(f"\nFound {len(critical_api_lines)} critical_api lines:")
        for line_num, line in critical_api_lines:
            print(f"  Line {line_num}: {line}")

            # Check for problematic parameters
            if "max_requests" in line or "window_minutes" in line:
                print(f"    ❌ PROBLEM: Old-style parameters found!")
                return False
            else:
                print(f"    ✅ OK: No old-style parameters")

        return True

    except Exception as e:
        print(f"❌ Error reading dd_batch_scheduler.py: {e}")
        return False


def check_import_statements():
    """Check import statements in dd_batch_scheduler.py"""
    print("\nChecking import statements...")

    filepath = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api/dd_batch_scheduler.py"

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        import_lines = []
        for i, line in enumerate(lines, 1):
            if "import" in line and ("critical_api" in line or "api_security_framework" in line):
                import_lines.append((i, line.strip()))

        print(f"Found {len(import_lines)} relevant import lines:")
        for line_num, line in import_lines:
            print(f"  Line {line_num}: {line}")

        return True

    except Exception as e:
        print(f"❌ Error reading import statements: {e}")
        return False


if __name__ == "__main__":
    print("Debugging critical_api decorator issue")
    print("=" * 60)

    # Check for old patterns
    issues = check_for_old_decorator_patterns()

    # Check dd_batch_scheduler specifically
    dd_ok = check_dd_batch_scheduler_specifically()

    # Check imports
    import_ok = check_import_statements()

    print("\n" + "=" * 60)
    print("SUMMARY:")
    print(f"Old patterns found: {len(issues)}")
    print(f"dd_batch_scheduler.py OK: {dd_ok}")
    print(f"Import statements OK: {import_ok}")

    if len(issues) == 0 and dd_ok and import_ok:
        print("✅ No obvious issues found with decorators")
        print("The error might be coming from:")
        print("  1. Cached .pyc files")
        print("  2. Frappe module loading issue")
        print("  3. Import ordering problem")
        print("  4. Namespace conflict")
    else:
        print("❌ Issues found that need to be fixed")
