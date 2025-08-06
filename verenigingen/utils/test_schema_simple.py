#!/usr/bin/env python3
"""
Simple schema validation utility for Chapter Board Member system
"""

import frappe


@frappe.whitelist()
def validate_chapter_board_schema():
    """Simple validation of Chapter Board Member schema fixes"""

    results = {"success": True, "tests_passed": 0, "tests_failed": 0, "details": []}

    # Test 1: Basic field reference validation
    try:
        result = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabChapter` c
            LEFT JOIN `tabChapter` cbm_parent ON cbm_parent.name = c.name
            LEFT JOIN `tabChapter Board Member` cbm ON cbm.parent = cbm_parent.name
            LEFT JOIN `tabVolunteer` v ON v.name = cbm.volunteer
            LEFT JOIN `tabMember` m ON m.name = v.member
            WHERE c.published = 1
        """,
            as_dict=True,
        )

        results["tests_passed"] += 1
        results["details"].append(f"✅ Basic schema structure: Found {result[0]['count']} records")

    except Exception as e:
        results["tests_failed"] += 1
        results["success"] = False
        results["details"].append(f"❌ Basic schema structure failed: {e}")

    # Test 2: Treasurer query validation
    try:
        treasurer_query = """
            SELECT DISTINCT
                c.name as chapter_name,
                cbm.volunteer,
                v.volunteer_name,
                m.first_name, m.last_name, m.email,
                cr.permissions_level
            FROM `tabChapter` c
            LEFT JOIN `tabChapter Board Member` cbm ON cbm.parent = c.name
            LEFT JOIN `tabVolunteer` v ON v.name = cbm.volunteer
            LEFT JOIN `tabMember` m ON m.name = v.member
            LEFT JOIN `tabChapter Role` cr ON cr.name = cbm.chapter_role
            WHERE cbm.is_active = 1
              AND cr.permissions_level = 'Financial'
            LIMIT 5
        """

        result = frappe.db.sql(treasurer_query, as_dict=True)
        results["tests_passed"] += 1
        results["details"].append(f"✅ Treasurer query validation: Found {len(result)} treasurer records")

    except Exception as e:
        results["tests_failed"] += 1
        results["success"] = False
        results["details"].append(f"❌ Treasurer query validation failed: {e}")

    # Test 3: Permission filter validation
    try:
        permission_query = """
            SELECT c.name
            FROM `tabChapter` c
            WHERE c.name IN (
                SELECT DISTINCT cbm_parent.name
                FROM `tabChapter` cbm_parent
                LEFT JOIN `tabChapter Board Member` cbm ON cbm.parent = cbm_parent.name
                LEFT JOIN `tabVolunteer` v ON v.name = cbm.volunteer
                LEFT JOIN `tabMember` m ON m.name = v.member
                WHERE cbm.is_active = 1
                  AND m.email = 'nonexistent@test.invalid'
            )
            LIMIT 5
        """

        result = frappe.db.sql(permission_query, as_dict=True)
        results["tests_passed"] += 1
        results["details"].append(f"✅ Permission filter validation: Returned {len(result)} records")

    except Exception as e:
        results["tests_failed"] += 1
        results["success"] = False
        results["details"].append(f"❌ Permission filter validation failed: {e}")

    return results
