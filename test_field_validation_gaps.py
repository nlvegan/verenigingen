#!/usr/bin/env python3
"""
Test script to identify what field validation patterns are being missed
"""

import ast
import re
from pathlib import Path


def find_next_billing_date_patterns():
    """Find all the patterns that our validator should have caught"""

    patterns_found = []
    app_path = Path("/home/frappe/frappe-bench/apps/verenigingen")

    # Search in Python files
    for py_file in app_path.rglob("*.py"):
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                content = f.read()
                lines = content.split("\n")

                # Pattern 1: getattr access
                getattr_pattern = r'getattr\([^,]+,\s*["\']next_billing_date["\']'
                if re.search(getattr_pattern, content):
                    for i, line in enumerate(lines):
                        if re.search(getattr_pattern, line):
                            patterns_found.append(
                                {
                                    "file": str(py_file.relative_to(app_path)),
                                    "line": i + 1,
                                    "pattern": "getattr() access",
                                    "code": line.strip(),
                                    "type": "attribute_access",
                                }
                            )

                # Pattern 2: Direct attribute access
                attr_pattern = r"\w+\.next_billing_date"
                if re.search(attr_pattern, content):
                    for i, line in enumerate(lines):
                        if re.search(attr_pattern, line):
                            patterns_found.append(
                                {
                                    "file": str(py_file.relative_to(app_path)),
                                    "line": i + 1,
                                    "pattern": "direct attribute access",
                                    "code": line.strip(),
                                    "type": "attribute_access",
                                }
                            )

                # Pattern 3: In field lists (frappe.get_all)
                field_list_pattern = r'["\']next_billing_date["\']'
                if re.search(field_list_pattern, content):
                    for i, line in enumerate(lines):
                        if re.search(field_list_pattern, line):
                            patterns_found.append(
                                {
                                    "file": str(py_file.relative_to(app_path)),
                                    "line": i + 1,
                                    "pattern": "field list",
                                    "code": line.strip(),
                                    "type": "field_query",
                                }
                            )

                # Pattern 4: SQL queries
                sql_pattern = r"(SELECT|FROM|WHERE|ORDER BY|GROUP BY).*next_billing_date"
                if re.search(sql_pattern, content, re.IGNORECASE):
                    for i, line in enumerate(lines):
                        if re.search(sql_pattern, line, re.IGNORECASE):
                            patterns_found.append(
                                {
                                    "file": str(py_file.relative_to(app_path)),
                                    "line": i + 1,
                                    "pattern": "SQL query",
                                    "code": line.strip(),
                                    "type": "sql_query",
                                }
                            )

                # Pattern 5: db_set operations
                db_set_pattern = r'\.db_set\(["\']next_billing_date["\']'
                if re.search(db_set_pattern, content):
                    for i, line in enumerate(lines):
                        if re.search(db_set_pattern, line):
                            patterns_found.append(
                                {
                                    "file": str(py_file.relative_to(app_path)),
                                    "line": i + 1,
                                    "pattern": "db_set operation",
                                    "code": line.strip(),
                                    "type": "database_operation",
                                }
                            )

        except Exception as e:
            print(f"Error reading {py_file}: {e}")

    # Search in HTML template files
    for html_file in app_path.rglob("*.html"):
        try:
            with open(html_file, "r", encoding="utf-8") as f:
                content = f.read()
                lines = content.split("\n")

                # Pattern: Template variables
                template_pattern = r"\{\{.*next_billing_date.*\}\}"
                if re.search(template_pattern, content):
                    for i, line in enumerate(lines):
                        if re.search(template_pattern, line):
                            patterns_found.append(
                                {
                                    "file": str(html_file.relative_to(app_path)),
                                    "line": i + 1,
                                    "pattern": "template variable",
                                    "code": line.strip(),
                                    "type": "template",
                                }
                            )

        except Exception as e:
            print(f"Error reading {html_file}: {e}")

    return patterns_found


def categorize_gaps(patterns):
    """Categorize the validation gaps by type"""
    gaps = {
        "attribute_access": [],
        "field_query": [],
        "sql_query": [],
        "database_operation": [],
        "template": [],
    }

    for pattern in patterns:
        gaps[pattern["type"]].append(pattern)

    return gaps


if __name__ == "__main__":
    print("🔍 Analyzing field validation gaps for next_billing_date...")

    patterns = find_next_billing_date_patterns()
    gaps = categorize_gaps(patterns)

    print(f"\n📊 Found {len(patterns)} total patterns that should have been caught:")

    for gap_type, items in gaps.items():
        if items:
            print(f"\n🔴 {gap_type.upper()} ({len(items)} instances):")
            for item in items:
                print(f"   {item['file']}:{item['line']} - {item['pattern']}")
                print(f"      Code: {item['code']}")

    print(f"\n💡 Validation Gap Analysis:")
    print(f"   - Attribute access patterns: {len(gaps['attribute_access'])}")
    print(f"   - Field query patterns: {len(gaps['field_query'])}")
    print(f"   - SQL query patterns: {len(gaps['sql_query'])}")
    print(f"   - Database operation patterns: {len(gaps['database_operation'])}")
    print(f"   - Template patterns: {len(gaps['template'])}")

    if patterns:
        print(f"\n🚨 Our current validator missed {len(patterns)} field references!")
        print("   This indicates significant gaps in validation coverage.")
    else:
        print(f"\n✅ No patterns found (they may have been already fixed)")
