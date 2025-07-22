import os
import re

import frappe


@frappe.whitelist()
def identify_fuzzy_logic_patterns():
    """Identify cases of fuzzy logic similar to the template lookup issue"""

    fuzzy_patterns = {
        "implicit_lookups": [],
        "name_based_matching": [],
        "fallback_logic": [],
        "auto_creation": [],
        "loose_validation": [],
    }

    # Common fuzzy logic patterns to search for
    search_patterns = [
        {
            "category": "implicit_lookups",
            "patterns": [
                r"frappe\.db\.get_value.*filters.*=.*\{.*\"name\":",  # Name-based lookups
                r"frappe\.get_all.*filters.*=.*\{.*\"name\":",
                r"frappe\.db\.sql.*WHERE.*name\s*LIKE",  # SQL name matching
                r"get_value.*\{.*\".*_type\":",  # Type field matching
            ],
        },
        {
            "category": "name_based_matching",
            "patterns": [
                r"Template-.*\+",  # Template name concatenation
                r"\"Template.*\".*\+",
                r"f\"Template-\{.*\}\"",  # Template name formatting
                r"\.startswith\(\"Template",
                r"\.endswith\(\"Template",
            ],
        },
        {
            "category": "fallback_logic",
            "patterns": [
                r"if\s+not.*:\s*#.*fallback",  # Fallback comments
                r"except.*:\s*#.*fallback",
                r"or\s+frappe\.get_doc\(",  # Fallback document gets
                r"if.*not.*found.*create",  # Auto-creation patterns
            ],
        },
        {
            "category": "auto_creation",
            "patterns": [
                r"create_default_template",
                r"auto.*create",
                r"create.*automatically",
                r"if.*not.*exist.*create",
            ],
        },
        {
            "category": "loose_validation",
            "patterns": [
                r"ignore_permissions=True",
                r"ignore_validate=True",
                r"try:.*except:.*pass",  # Silent failures
                r"except.*Exception.*:",  # Broad exception catching
            ],
        },
    ]

    # Files to search through
    base_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen"

    for root, dirs, files in os.walk(base_path):
        for file in files:
            if file.endswith(".py") and not file.startswith("test_"):
                file_path = os.path.join(root, file)
                relative_path = file_path.replace(base_path + "/", "")

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    for pattern_group in search_patterns:
                        category = pattern_group["category"]

                        for pattern in pattern_group["patterns"]:
                            matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)

                            for match in matches:
                                line_num = content[: match.start()].count("\n") + 1
                                line_content = content.split("\n")[line_num - 1].strip()

                                fuzzy_patterns[category].append(
                                    {
                                        "file": relative_path,
                                        "line": line_num,
                                        "pattern": pattern,
                                        "content": line_content,
                                        "match": match.group(),
                                    }
                                )

                except Exception as e:
                    continue

    # Remove duplicates and limit results
    for category in fuzzy_patterns:
        # Remove duplicates by file+line combination
        seen = set()
        unique_patterns = []

        for item in fuzzy_patterns[category]:
            key = f"{item['file']}:{item['line']}"
            if key not in seen:
                seen.add(key)
                unique_patterns.append(item)

        fuzzy_patterns[category] = unique_patterns[:20]  # Limit to 20 per category

    return {
        "total_patterns_found": sum(len(fuzzy_patterns[cat]) for cat in fuzzy_patterns),
        "patterns": fuzzy_patterns,
        "analysis": {
            "high_risk": len(fuzzy_patterns["implicit_lookups"]) + len(fuzzy_patterns["name_based_matching"]),
            "medium_risk": len(fuzzy_patterns["fallback_logic"]) + len(fuzzy_patterns["auto_creation"]),
            "low_risk": len(fuzzy_patterns["loose_validation"]),
        },
    }


@frappe.whitelist()
def identify_specific_fuzzy_cases():
    """Identify specific fuzzy logic cases that might cause issues like the template problem"""

    issues = []

    # Check for other implicit lookup patterns in key files
    key_files = [
        "verenigingen/doctype/membership/membership.py",
        "verenigingen/doctype/member/member.py",
        "verenigingen/doctype/volunteer/volunteer.py",
        "verenigingen/doctype/chapter/chapter.py",
        "api/*.py",
        "utils/*.py",
    ]

    # Look for specific problematic patterns
    problematic_patterns = [
        {
            "name": "Member lookup by name/email instead of explicit assignment",
            "pattern": r"frappe\.db\.get_value\(\"Member\".*email.*=",
            "risk": "HIGH",
            "description": "Implicit member lookup by email could match wrong member",
        },
        {
            "name": "Chapter assignment by postal code/location",
            "pattern": r"postal.*code.*chapter|chapter.*postal",
            "risk": "MEDIUM",
            "description": "Fuzzy chapter assignment logic could be unpredictable",
        },
        {
            "name": "Membership type detection by amount/period",
            "pattern": r"amount.*membership_type|membership_type.*amount",
            "risk": "HIGH",
            "description": "Inferring membership type from amount could be wrong",
        },
        {
            "name": "Auto-creation without explicit configuration",
            "pattern": r"create.*if.*not.*exist",
            "risk": "MEDIUM",
            "description": "Auto-creation logic might create unexpected records",
        },
        {
            "name": "Default value fallbacks in business logic",
            "pattern": r"or\s+\".*\"|\|\|\s+\".*\"",
            "risk": "MEDIUM",
            "description": "Hardcoded fallback values in business logic",
        },
    ]

    base_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen"

    for root, dirs, files in os.walk(base_path):
        for file in files:
            if file.endswith(".py") and not file.startswith("test_"):
                file_path = os.path.join(root, file)
                relative_path = file_path.replace(base_path + "/", "")

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    for pattern_info in problematic_patterns:
                        matches = re.finditer(pattern_info["pattern"], content, re.IGNORECASE | re.MULTILINE)

                        for match in matches:
                            line_num = content[: match.start()].count("\n") + 1
                            line_content = content.split("\n")[line_num - 1].strip()

                            issues.append(
                                {
                                    "type": pattern_info["name"],
                                    "file": relative_path,
                                    "line": line_num,
                                    "content": line_content,
                                    "risk": pattern_info["risk"],
                                    "description": pattern_info["description"],
                                    "recommendation": "Review and make explicit",
                                }
                            )

                except Exception as e:
                    continue

    # Sort by risk level
    risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    issues.sort(key=lambda x: risk_order.get(x["risk"], 3))

    return {
        "total_issues": len(issues),
        "high_risk_count": len([i for i in issues if i["risk"] == "HIGH"]),
        "medium_risk_count": len([i for i in issues if i["risk"] == "MEDIUM"]),
        "low_risk_count": len([i for i in issues if i["risk"] == "LOW"]),
        "issues": issues[:30],  # Limit to 30 most important
        "summary": "Found potential fuzzy logic patterns that could cause similar issues to the template lookup problem",
    }
