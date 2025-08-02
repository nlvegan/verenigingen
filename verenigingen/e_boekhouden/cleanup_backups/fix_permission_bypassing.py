#!/usr/bin/env python3
"""
Script to fix all ignore_permissions=True occurrences in E-Boekhouden module.

This script systematically replaces permission bypassing with proper
security helper calls throughout the codebase.
"""

import os
import re
from pathlib import Path

# Mapping of patterns to replacements
REPLACEMENTS = {
    # Basic insert patterns
    r"(\w+)\.insert\s*\(\s*ignore_permissions\s*=\s*True\s*\)": r"validate_and_insert(\1)",
    r"(\w+)\.save\s*\(\s*ignore_permissions\s*=\s*True\s*\)": r"validate_and_save(\1)",
    # Insert with additional parameters
    r"(\w+)\.insert\s*\(\s*ignore_permissions\s*=\s*True\s*,\s*([^)]+)\)": r"\1.update({\2})\nvalidate_and_insert(\1)",
    r"(\w+)\.save\s*\(\s*ignore_permissions\s*=\s*True\s*,\s*([^)]+)\)": r"\1.update({\2})\nvalidate_and_save(\1)",
    # Direct frappe.get_doc().insert patterns
    r"frappe\.get_doc\s*\(([^)]+)\)\.insert\s*\(\s*ignore_permissions\s*=\s*True\s*\)": r"doc = frappe.get_doc(\1)\nvalidate_and_insert(doc)",
}

# Files that need security helper import
NEEDS_IMPORT = set()

# Special cases that need manual review
MANUAL_REVIEW = []


def add_security_import(file_path: str, content: str) -> str:
    """Add security helper import to file if needed."""
    # Check if already imported
    if "from verenigingen.e_boekhouden.utils.security_helper import" in content:
        return content

    # Find the right place to add import
    lines = content.split("\n")
    import_added = False

    for i, line in enumerate(lines):
        # Add after other frappe imports
        if line.startswith("import frappe") or line.startswith("from frappe"):
            # Find the last frappe import
            j = i
            while j < len(lines) - 1 and (
                lines[j + 1].startswith("import") or lines[j + 1].startswith("from")
            ):
                j += 1

            # Insert after last import
            lines.insert(
                j + 1,
                "\nfrom verenigingen.e_boekhouden.utils.security_helper import validate_and_insert, validate_and_save",
            )
            import_added = True
            break

    if not import_added:
        # Add at the beginning after module docstring
        for i, line in enumerate(lines):
            if i > 0 and not line.strip().startswith('"""') and not line.strip().startswith("#"):
                lines.insert(
                    i,
                    "from verenigingen.e_boekhouden.utils.security_helper import validate_and_insert, validate_and_save\n",
                )
                break

    return "\n".join(lines)


def fix_permission_bypassing(file_path: str) -> tuple[bool, list]:
    """
    Fix permission bypassing in a single file.

    Returns:
        (modified, issues): Whether file was modified and list of issues found
    """
    with open(file_path, "r") as f:
        content = f.read()

    original_content = content
    issues = []

    # Check for ignore_permissions
    if "ignore_permissions=True" not in content:
        return False, []

    # Apply replacements
    for pattern, replacement in REPLACEMENTS.items():
        matches = re.findall(pattern, content)
        if matches:
            content = re.sub(pattern, replacement, content)
            issues.append(f"Replaced {len(matches)} occurrences of pattern: {pattern}")

    # Check for remaining ignore_permissions
    remaining = re.findall(r"ignore_permissions\s*=\s*True", content)
    if remaining:
        issues.append(f"WARNING: {len(remaining)} ignore_permissions=True still remain - needs manual review")
        MANUAL_REVIEW.append((file_path, remaining))

    # Add import if needed
    if content != original_content:
        content = add_security_import(file_path, content)
        NEEDS_IMPORT.add(file_path)

    # Write back if modified
    if content != original_content:
        with open(file_path, "w") as f:
            f.write(content)
        return True, issues

    return False, issues


def process_directory(directory: str):
    """Process all Python files in directory."""
    path = Path(directory)
    modified_files = []
    all_issues = []

    for py_file in path.rglob("*.py"):
        # Skip test files and backups for now
        if "test_" in py_file.name or "_backup" in py_file.name:
            continue

        modified, issues = fix_permission_bypassing(str(py_file))
        if modified:
            modified_files.append(str(py_file))
            all_issues.extend([(str(py_file), issue) for issue in issues])

    return modified_files, all_issues


def generate_report(modified_files: list, all_issues: list):
    """Generate report of changes."""
    print("=" * 80)
    print("PERMISSION BYPASSING FIX REPORT")
    print("=" * 80)

    print(f"\nTotal files modified: {len(modified_files)}")
    print(f"Files needing manual review: {len(MANUAL_REVIEW)}")

    print("\n\nMODIFIED FILES:")
    print("-" * 40)
    for f in sorted(modified_files):
        print(f"  - {f}")

    if MANUAL_REVIEW:
        print("\n\nFILES NEEDING MANUAL REVIEW:")
        print("-" * 40)
        for f, remaining in MANUAL_REVIEW:
            print(f"  - {f}: {len(remaining)} occurrences")

    print("\n\nDETAILED CHANGES:")
    print("-" * 40)
    for f, issue in all_issues:
        print(f"{f}:")
        print(f"  {issue}")

    print("\n\nNEXT STEPS:")
    print("-" * 40)
    print("1. Review the changes made to ensure they're correct")
    print("2. Manually fix files that couldn't be automatically updated")
    print("3. Test the migration functionality to ensure it still works")
    print("4. Ensure the Administrator user has all required roles")


if __name__ == "__main__":
    # Process the E-Boekhouden directory
    e_boekhouden_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/e_boekhouden"

    print("Starting permission bypassing fix...")
    modified_files, all_issues = process_directory(e_boekhouden_path)

    generate_report(modified_files, all_issues)

    print("\n\nTo apply these changes to the codebase, review the modifications and test thoroughly.")
    print("Consider creating a backup before applying changes in production.")
