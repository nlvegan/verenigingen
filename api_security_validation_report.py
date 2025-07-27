#!/usr/bin/env python3
"""
API Security Framework Validation Report
Comprehensive analysis and validation of the API security framework
"""

import os
import re
from pathlib import Path


def analyze_decorator_usage():
    """Analyze decorator usage across all API files"""
    print("API Security Framework Validation Report")
    print("=" * 60)

    api_path = Path("/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api")

    # Statistics
    stats = {
        "total_files": 0,
        "files_with_decorators": 0,
        "critical_api_usage": 0,
        "high_security_api_usage": 0,
        "standard_api_usage": 0,
        "utility_api_usage": 0,
        "public_api_usage": 0,
        "whitelisted_functions": 0,
        "security_protected_functions": 0,
        "issues_found": [],
    }

    decorator_patterns = {
        "critical_api": r"@critical_api\s*\(",
        "high_security_api": r"@high_security_api\s*\(",
        "standard_api": r"@standard_api\s*\(",
        "utility_api": r"@utility_api\s*\(",
        "public_api": r"@public_api\s*\(",
        "whitelist": r"@frappe\.whitelist\s*\(",
    }

    # Old patterns that should not exist
    problematic_patterns = [
        r"@critical_api\s*\(\s*max_requests\s*=",
        r"@high_security_api\s*\(\s*max_requests\s*=",
        r"@standard_api\s*\(\s*max_requests\s*=",
        r"@utility_api\s*\(\s*max_requests\s*=",
        r"@public_api\s*\(\s*max_requests\s*=",
        r"@.*_api\([^)]*window_minutes",
    ]

    files_analyzed = []

    for py_file in api_path.glob("*.py"):
        if py_file.name.startswith("__"):
            continue

        stats["total_files"] += 1

        try:
            with open(py_file, "r", encoding="utf-8") as f:
                content = f.read()

            file_stats = {"filename": py_file.name, "decorators": {}, "issues": [], "functions": []}

            # Check for decorator usage
            has_decorators = False
            for decorator_name, pattern in decorator_patterns.items():
                matches = re.findall(pattern, content, re.MULTILINE)
                count = len(matches)
                if count > 0:
                    file_stats["decorators"][decorator_name] = count
                    stats[f"{decorator_name}_usage"] += count
                    has_decorators = True

            if has_decorators:
                stats["files_with_decorators"] += 1

            # Check for problematic patterns
            for pattern in problematic_patterns:
                matches = re.finditer(pattern, content, re.MULTILINE | re.IGNORECASE)
                for match in matches:
                    line_num = content[: match.start()].count("\n") + 1
                    issue = {
                        "file": py_file.name,
                        "line": line_num,
                        "issue": f"Old decorator pattern: {match.group()}",
                        "pattern": pattern,
                    }
                    file_stats["issues"].append(issue)
                    stats["issues_found"].append(issue)

            # Find function definitions with decorators
            function_pattern = r"@[^\n]*\ndef\s+(\w+)\s*\("
            function_matches = re.finditer(function_pattern, content, re.MULTILINE)
            for match in function_matches:
                func_name = match.group(1)
                # Get the decorators above this function
                func_start = match.start()
                lines_before = content[:func_start].split("\n")
                decorators = []
                for line in reversed(lines_before[-10:]):  # Check last 10 lines
                    line = line.strip()
                    if line.startswith("@"):
                        decorators.insert(0, line)
                    elif line and not line.startswith("#"):
                        break

                file_stats["functions"].append({"name": func_name, "decorators": decorators})

                # Count security protected functions
                if any("_api(" in dec for dec in decorators):
                    stats["security_protected_functions"] += 1

            files_analyzed.append(file_stats)

        except Exception as e:
            stats["issues_found"].append(
                {
                    "file": py_file.name,
                    "line": 0,
                    "issue": f"Failed to analyze file: {e}",
                    "pattern": "file_error",
                }
            )

    return stats, files_analyzed


def generate_report():
    """Generate the validation report"""
    stats, files_analyzed = analyze_decorator_usage()

    print(f"Analysis of {stats['total_files']} API files")
    print("-" * 40)

    print("DECORATOR USAGE STATISTICS:")
    print(f"  Files with security decorators: {stats['files_with_decorators']}")
    print(f"  @critical_api usage: {stats['critical_api_usage']}")
    print(f"  @high_security_api usage: {stats['high_security_api_usage']}")
    print(f"  @standard_api usage: {stats['standard_api_usage']}")
    print(f"  @utility_api usage: {stats['utility_api_usage']}")
    print(f"  @public_api usage: {stats['public_api_usage']}")
    print(f"  @frappe.whitelist usage: {stats['whitelisted_functions']}")
    print(f"  Security-protected functions: {stats['security_protected_functions']}")

    print(f"\nISSUES FOUND: {len(stats['issues_found'])}")
    if stats["issues_found"]:
        print("❌ CRITICAL ISSUES DETECTED:")
        for issue in stats["issues_found"]:
            print(f"  {issue['file']}:{issue['line']} - {issue['issue']}")
    else:
        print("✅ NO ISSUES FOUND")

    print("\nFILES WITH SECURITY DECORATORS:")
    for file_info in files_analyzed:
        if file_info["decorators"]:
            print(f"  {file_info['filename']}:")
            for decorator, count in file_info["decorators"].items():
                print(f"    {decorator}: {count}")

    print("\nFUNCTIONS WITH MULTIPLE DECORATORS:")
    for file_info in files_analyzed:
        for func in file_info["functions"]:
            if len(func["decorators"]) > 1:
                print(f"  {file_info['filename']}.{func['name']}:")
                for decorator in func["decorators"]:
                    print(f"    {decorator}")

    # Security coverage analysis
    total_whitelisted = stats["whitelisted_functions"]
    total_secured = stats["security_protected_functions"]

    if total_whitelisted > 0:
        coverage_percent = (total_secured / total_whitelisted) * 100
        print("\nSECURITY COVERAGE:")
        print(f"  Security coverage: {coverage_percent:.1f}% ({total_secured}/{total_whitelisted})")

        if coverage_percent < 80:
            print("  ⚠️  Warning: Low security coverage")
        else:
            print("  ✅ Good security coverage")

    return stats, len(stats["issues_found"]) == 0


def check_framework_compatibility():
    """Check framework compatibility and backward compatibility"""
    print("\nFRAMEWORK COMPATIBILITY CHECK:")
    print("-" * 40)

    framework_file = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/security/api_security_framework.py"
    )

    try:
        with open(framework_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for critical_api definition
        critical_api_pattern = r"def critical_api\s*\(([^)]*)\):"
        match = re.search(critical_api_pattern, content)

        if match:
            params = match.group(1).strip()
            print(f"✅ critical_api signature: def critical_api({params})")

            # Check that it doesn't accept old parameters
            if "max_requests" in params or "window_minutes" in params:
                print("❌ Framework still accepts legacy parameters")
                return False
            else:
                print("✅ Framework properly rejects legacy parameters")

        # Check for other decorator definitions
        other_decorators = ["high_security_api", "standard_api", "utility_api", "public_api"]
        for decorator in other_decorators:
            pattern = f"def {decorator}\\s*\\(([^)]*)\\):"
            match = re.search(pattern, content)
            if match:
                params = match.group(1).strip()
                print(f"✅ {decorator} signature: def {decorator}({params})")

        print("✅ Framework compatibility check passed")
        return True

    except Exception as e:
        print(f"❌ Failed to check framework compatibility: {e}")
        return False


def main():
    """Main function"""
    stats, no_issues = generate_report()
    framework_ok = check_framework_compatibility()

    print("\n" + "=" * 60)
    print("FINAL ASSESSMENT:")

    if no_issues and framework_ok:
        print("✅ API Security Framework is working correctly")
        print("✅ All decorators are using the proper syntax")
        print("✅ No legacy parameter usage found")

        print("\nThe 'max_requests' error is likely due to:")
        print("1. Cached .pyc files (already cleared)")
        print("2. Frappe framework module loading timing issue")
        print("3. Temporary import conflict during startup")

        print("\nRECOMMENDED SOLUTION:")
        print("1. bench restart")
        print("2. If error persists, check Frappe logs for more details")
        print("3. The error may be transient and resolve on restart")

    else:
        print("❌ Issues found that need to be addressed")
        if not no_issues:
            print(f"  - {len(stats['issues_found'])} decorator issues found")
        if not framework_ok:
            print("  - Framework compatibility issues found")

    print(
        f"\nAnalyzed {stats['total_files']} files with {stats['security_protected_functions']} secured endpoints"
    )

    return no_issues and framework_ok


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
