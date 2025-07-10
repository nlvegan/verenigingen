#!/usr/bin/env python3
"""
Analyze LIKE usage in the eBoekhouden processing code
"""

import frappe


@frappe.whitelist()
def analyze_like_usage():
    """Analyze all LIKE patterns in the code for potential issues"""

    # Read the file and find all LIKE patterns
    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    try:
        with open(file_path, "r") as f:
            lines = f.readlines()
    except Exception as e:
        return {"error": f"Could not read file: {str(e)}"}

    like_patterns = []

    for i, line in enumerate(lines):
        if "LIKE" in line:
            like_patterns.append(
                {
                    "line_number": i + 1,
                    "line_content": line.strip(),
                    "context": {
                        "before": lines[max(0, i - 2) : i] if i > 1 else [],
                        "after": lines[i + 1 : min(len(lines), i + 3)] if i < len(lines) - 2 else [],
                    },
                }
            )

    # Analyze each pattern
    analysis = {
        "total_like_patterns": len(like_patterns),
        "patterns_by_category": {},
        "potentially_problematic": [],
        "acceptable_patterns": [],
    }

    for pattern in like_patterns:
        line = pattern["line_content"]
        line_num = pattern["line_number"]

        # Categorize the LIKE usage
        category = "unknown"
        is_problematic = False
        reason = ""

        if "account_name LIKE" in line:
            category = "account_name_search"
            # These are usually acceptable for searching account names
            if "kostprijs" in line.lower() or "omzet" in line.lower():
                is_problematic = False
                reason = "Acceptable - searching for account names by partial match"
            elif "sociale lasten" in line.lower():
                is_problematic = False
                reason = "Acceptable - excluding accounts with specific text"

        elif "erpnext_account LIKE" in line:
            category = "erpnext_account_search"
            # These could be problematic if they should be exact matches
            is_problematic = True
            reason = "POTENTIALLY PROBLEMATIC - should this be exact match instead?"

        elif "ledger_id LIKE" in line:
            category = "ledger_id_search"
            # These are definitely problematic - ledger IDs should be exact
            is_problematic = True
            reason = "PROBLEMATIC - ledger IDs should use exact matching"

        elif "name LIKE 'EB-" in line:
            category = "item_name_search"
            is_problematic = False
            reason = "Acceptable - searching for eBoekhouden items by prefix"

        elif "expense_account LIKE" in line or "income_account LIKE" in line:
            category = "account_field_search"
            is_problematic = False
            reason = "Acceptable - searching accounts by partial name match"

        elif "user_remark LIKE" in line or "remarks LIKE" in line:
            category = "remarks_search"
            is_problematic = False
            reason = "Acceptable - searching remarks/comments by partial match"

        elif "title LIKE" in line:
            category = "title_search"
            is_problematic = False
            reason = "Acceptable - searching titles by partial match"

        pattern_info = {
            "line_number": line_num,
            "line_content": line,
            "category": category,
            "is_problematic": is_problematic,
            "reason": reason,
        }

        if is_problematic:
            analysis["potentially_problematic"].append(pattern_info)
        else:
            analysis["acceptable_patterns"].append(pattern_info)

        # Group by category
        if category not in analysis["patterns_by_category"]:
            analysis["patterns_by_category"][category] = []
        analysis["patterns_by_category"][category].append(pattern_info)

    # Summary
    analysis["summary"] = {
        "total_patterns": len(like_patterns),
        "problematic_count": len(analysis["potentially_problematic"]),
        "acceptable_count": len(analysis["acceptable_patterns"]),
        "categories_found": list(analysis["patterns_by_category"].keys()),
    }

    return analysis


@frappe.whitelist()
def check_for_ledger_like_patterns():
    """Specifically check for ledger-related LIKE patterns that should be exact matches"""

    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    try:
        with open(file_path, "r") as f:
            content = f.read()
    except Exception as e:
        return {"error": f"Could not read file: {str(e)}"}

    # Look for specific patterns that are definitely wrong
    problematic_patterns = []

    # Pattern 1: ledger_id with LIKE
    if "ledger_id" in content and "LIKE" in content:
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "ledger_id" in line and "LIKE" in line:
                problematic_patterns.append(
                    {
                        "line_number": i + 1,
                        "line": line.strip(),
                        "issue": "ledger_id should use exact matching (=) not LIKE",
                        "severity": "HIGH",
                    }
                )

    # Pattern 2: Check for WHERE clauses that might use LIKE incorrectly
    import re

    # Find WHERE clauses with LIKE that might need exact matching
    where_like_patterns = re.findall(
        r'WHERE\s+(\w+)\s+LIKE\s+[\'"]?([^\'"\s]+)[\'"]?', content, re.IGNORECASE
    )

    for field, pattern in where_like_patterns:
        if field in ["ledger_id", "mutation_id", "id"]:
            problematic_patterns.append(
                {
                    "field": field,
                    "pattern": pattern,
                    "issue": "{field} should use exact matching, not LIKE with pattern {pattern}",
                    "severity": "HIGH",
                }
            )

    return {
        "problematic_patterns_found": len(problematic_patterns),
        "patterns": problematic_patterns,
        "recommendation": "Replace LIKE with = for exact field matching"
        if problematic_patterns
        else "No problematic LIKE patterns found",
    }
