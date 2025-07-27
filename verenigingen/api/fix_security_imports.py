#!/usr/bin/env python3
"""
Security Import Standardization Script

This script fixes import conflicts by standardizing all security decorator
imports to use the new API Security Framework.
"""

import glob
import os
import re
from pathlib import Path

# Define the correct import patterns
CORRECT_IMPORTS = {
    "critical_api": "from verenigingen.utils.security.api_security_framework import critical_api, OperationType",
    "high_security_api": "from verenigingen.utils.security.api_security_framework import high_security_api, OperationType",
    "standard_api": "from verenigingen.utils.security.api_security_framework import standard_api, OperationType",
    "utility_api": "from verenigingen.utils.security.api_security_framework import utility_api, OperationType",
    "public_api": "from verenigingen.utils.security.api_security_framework import public_api, OperationType",
}

# Patterns to find and replace
OLD_IMPORT_PATTERNS = [
    r"from verenigingen\.utils\.security\.authorization import.*",
    r"from verenigingen\.utils\.security\.rate_limiting import.*",
]


def analyze_api_directory():
    """Analyze all API files for import conflicts"""
    api_dir = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api"

    conflicts = []

    for py_file in glob.glob(os.path.join(api_dir, "*.py")):
        if py_file.endswith("fix_security_imports.py"):
            continue

        with open(py_file, "r") as f:
            content = f.read()

        # Check for old import patterns
        for pattern in OLD_IMPORT_PATTERNS:
            if re.search(pattern, content):
                conflicts.append({"file": py_file, "pattern": pattern, "content": content})

    return conflicts


def fix_file_imports(file_path, content):
    """Fix imports in a single file"""
    lines = content.split("\n")
    new_lines = []
    imports_added = set()

    # Find what decorators are actually used in the file
    used_decorators = set()
    for line in content.split("\n"):
        if "@critical_api" in line:
            used_decorators.add("critical_api")
        if "@high_security_api" in line:
            used_decorators.add("high_security_api")
        if "@standard_api" in line:
            used_decorators.add("standard_api")
        if "@utility_api" in line:
            used_decorators.add("utility_api")
        if "@public_api" in line:
            used_decorators.add("public_api")

    skip_next = False
    # in_import_section = True  # Unused variable

    for i, line in enumerate(lines):
        if skip_next:
            skip_next = False
            continue

        # Skip old import lines
        is_old_import = False
        for pattern in OLD_IMPORT_PATTERNS:
            if re.match(pattern, line.strip()):
                is_old_import = True
                break

        if is_old_import:
            # Add correct imports if not already added
            if not imports_added and used_decorators:
                # Build the correct import statement
                needed_imports = []
                for decorator in used_decorators:
                    if decorator in CORRECT_IMPORTS:
                        needed_imports.append(decorator)

                if needed_imports:
                    import_items = list(needed_decorators) + ["OperationType"]
                    new_import = f"from verenigingen.utils.security.api_security_framework import {', '.join(import_items)}"
                    new_lines.append(new_import)
                    imports_added.update(needed_imports)
            continue

        # Track when we're past imports
        if (
            line.strip()
            and not line.startswith("import")
            and not line.startswith("from")
            and not line.startswith("#")
            and not line.startswith('"""')
        ):
            # in_import_section = False  # Unused variable
            pass

        new_lines.append(line)

    return "\n".join(new_lines)


def main():
    """Main function to fix all import conflicts"""
    print("🔍 Analyzing API directory for import conflicts...")

    conflicts = analyze_api_directory()

    print(f"📊 Found {len(conflicts)} files with import conflicts")

    for conflict in conflicts:
        file_path = conflict["file"]
        filename = os.path.basename(file_path)
        print(f"  ✏️  Fixing {filename}")

        try:
            fixed_content = fix_file_imports(file_path, conflict["content"])

            # Write back the fixed content
            with open(file_path, "w") as f:
                f.write(fixed_content)

            print(f"  ✅ Fixed {filename}")
        except Exception as e:
            print(f"  ❌ Error fixing {filename}: {e}")

    print(f"🎉 Completed import standardization for {len(conflicts)} files")


if __name__ == "__main__":
    main()
