#!/usr/bin/env python3
"""
Script to fix literal string formatting issues throughout the codebase.
Converts literal strings with {braces} to proper f-strings.

This addresses a systematic issue where strings like:
    "Hello {name}"
Should be:
    f"Hello {name}"
"""

import glob
import re


def fix_literal_string_patterns(content):
    """Fix common literal string patterns that should be f-strings"""
    fixes_applied = []

    # Pattern 1: return "text {variable} text"
    pattern1 = r'return\s+"([^"]*\{[^}]+\}[^"]*)"'

    def replace1(match):
        string_content = match.group(1)
        fixes_applied.append(f"return statement: {string_content[:50]}...")
        return f'return f"{string_content}"'

    content = re.sub(pattern1, replace1, content)

    # Pattern 2: variable = "text {variable} text"
    pattern2 = r'(\w+)\s*=\s*"([^"]*\{[^}]+\}[^"]*)"'

    def replace2(match):
        var_name = match.group(1)
        string_content = match.group(2)
        fixes_applied.append(f"assignment to {var_name}: {string_content[:50]}...")
        return f'{var_name} = f"{string_content}"'

    content = re.sub(pattern2, replace2, content)

    # Pattern 3: Multi-line string assignments
    pattern3 = r'(\w+)\s*=\s*"([^"]*\{[^}]+\}[^"]*)"'
    content = re.sub(pattern3, replace2, content)

    return content, fixes_applied


def should_fix_file(filepath):
    """Determine if a file should be processed for fixes"""
    # Skip certain files that might have legitimate brace usage
    skip_patterns = [
        "test_",
        "__pycache__",
        ".pyc",
        "migrations/",
        "fixtures/",
        "locale/",
    ]

    for pattern in skip_patterns:
        if pattern in filepath:
            return False

    return filepath.endswith(".py")


def fix_file(filepath):
    """Fix a single file and return results"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            original_content = f.read()

        fixed_content, fixes_applied = fix_literal_string_patterns(original_content)

        if fixes_applied:
            # Create backup
            backup_path = filepath + ".backup"
            with open(backup_path, "w", encoding="utf-8") as f:
                f.write(original_content)

            # Write fixed content
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(fixed_content)

            return {
                "file": filepath,
                "fixes": len(fixes_applied),
                "details": fixes_applied[:5],  # Show first 5 fixes
                "backup": backup_path,
            }

    except Exception as e:
        return {"file": filepath, "error": str(e)}

    return None


def main():
    """Main execution"""
    print("🔍 Scanning for literal string formatting issues...")

    # Find Python files in utils directory
    utils_files = glob.glob("verenigingen/utils/*.py")

    results = {"fixed": [], "errors": [], "total_fixes": 0}

    for filepath in utils_files:
        if should_fix_file(filepath):
            result = fix_file(filepath)
            if result:
                if "error" in result:
                    results["errors"].append(result)
                else:
                    results["fixed"].append(result)
                    results["total_fixes"] += result["fixes"]

    # Print summary
    print("\n📊 Summary:")
    print(f"✅ Files fixed: {len(results['fixed'])}")
    print(f"🔧 Total fixes applied: {results['total_fixes']}")
    print(f"❌ Errors: {len(results['errors'])}")

    if results["fixed"]:
        print("\n📄 Fixed files:")
        for result in results["fixed"]:
            print(f"  • {result['file']}: {result['fixes']} fixes")
            for detail in result["details"]:
                print(f"    - {detail}")

    if results["errors"]:
        print("\n❌ Errors:")
        for error in results["errors"]:
            print(f"  • {error['file']}: {error['error']}")

    print("\n💾 Backups created with .backup extension")
    print("🔄 Run 'git diff' to see changes")


if __name__ == "__main__":
    main()
