#!/usr/bin/env python3
"""
Schema Fixes Validation Utilities
=================================

Validates that the Chapter Board Member schema fixes are properly applied.
"""

import frappe


@frappe.whitelist()
def validate_chapter_board_schema_fixes():
    """Validate that schema fixes are working correctly"""

    result = {"success": True, "tests_passed": 0, "tests_failed": 0, "details": []}

    def add_test_result(name, passed, details=""):
        if passed:
            result["tests_passed"] += 1
            result["details"].append(f"✅ {name}: {details}")
        else:
            result["tests_failed"] += 1
            result["success"] = False
            result["details"].append(f"❌ {name}: {details}")

    # Test 1: Basic schema structure
    try:
        board_members = frappe.db.sql(
            """
            SELECT cbm.volunteer, cbm.chapter_role, cbm.is_active
            FROM `tabChapter Board Member` cbm
            WHERE cbm.is_active = 1
            LIMIT 3
        """,
            as_dict=True,
        )

        add_test_result("Basic schema structure", True, f"Found {len(board_members)} active board members")

    except Exception as e:
        add_test_result("Basic schema structure", False, str(e))

    # Test 2: Volunteer JOIN
    try:
        board_with_volunteer = frappe.db.sql(
            """
            SELECT cbm.volunteer, v.member
            FROM `tabChapter Board Member` cbm
            INNER JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            WHERE cbm.is_active = 1
            LIMIT 3
        """,
            as_dict=True,
        )

        add_test_result(
            "Board Member → Volunteer JOIN", True, f"Successfully joined {len(board_with_volunteer)} records"
        )

    except Exception as e:
        add_test_result("Board Member → Volunteer JOIN", False, str(e))

    # Test 3: Full JOIN chain
    try:
        full_chain = frappe.db.sql(
            """
            SELECT cbm.volunteer, v.member, m.first_name, m.last_name
            FROM `tabChapter Board Member` cbm
            INNER JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            INNER JOIN `tabMember` m ON v.member = m.name
            WHERE cbm.is_active = 1
            LIMIT 3
        """,
            as_dict=True,
        )

        add_test_result(
            "Full JOIN chain (Board → Volunteer → Member)",
            True,
            f"Successfully joined {len(full_chain)} complete records",
        )

    except Exception as e:
        add_test_result("Full JOIN chain (Board → Volunteer → Member)", False, str(e))

    # Test 4: Chapter filtering
    try:
        chapter_filtering = frappe.db.sql(
            """
            SELECT c.name as chapter_name, cbm.volunteer, v.member
            FROM `tabChapter` c
            INNER JOIN `tabChapter Board Member` cbm ON cbm.parent = c.name
            INNER JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            WHERE cbm.is_active = 1
            LIMIT 5
        """,
            as_dict=True,
        )

        add_test_result(
            "Chapter-level filtering",
            True,
            f"Chapter filtering query successful for {len(chapter_filtering)} records",
        )

    except Exception as e:
        add_test_result("Chapter-level filtering", False, str(e))

    # Test 5: Treasurer queries
    try:
        treasurer_query = frappe.db.sql(
            """
            SELECT cbm.volunteer, v.member, cr.permissions_level
            FROM `tabChapter Board Member` cbm
            INNER JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            INNER JOIN `tabChapter Role` cr ON cbm.chapter_role = cr.name
            WHERE cbm.is_active = 1 AND cr.permissions_level = 'Financial'
            LIMIT 3
        """,
            as_dict=True,
        )

        add_test_result(
            "Treasurer permission queries", True, f"Found {len(treasurer_query)} treasurer records"
        )

    except Exception as e:
        add_test_result("Treasurer permission queries", False, str(e))

    # Test 6: Performance test
    try:
        import time

        start_time = time.time()

        performance_query = frappe.db.sql(
            """
            SELECT COUNT(*) as total
            FROM `tabChapter Board Member` cbm
            INNER JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            WHERE cbm.is_active = 1
        """,
            as_dict=True,
        )

        query_time = time.time() - start_time
        total = performance_query[0].total if performance_query else 0

        performance_ok = query_time < 1.0
        add_test_result(
            "Query performance", performance_ok, f"Query completed in {query_time:.3f}s ({total} records)"
        )

    except Exception as e:
        add_test_result("Query performance", False, str(e))

    return result
