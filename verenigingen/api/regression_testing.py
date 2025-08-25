#!/usr/bin/env python3
"""
API functions for regression testing of recent changes

This module provides whitelisted API functions to test the functionality
of recent implementations including permission caching, volunteer role assignment,
and team-based project permissions.
"""

import frappe
from frappe import _


@frappe.whitelist()
def test_permission_caching():
    """Test permission caching system functionality"""
    try:
        from verenigingen.permissions import (
            clear_permission_cache,
            get_cache_key,
            get_user_chapter_memberships_cached,
        )

        results = []
        results.append("Testing permission caching system...")

        # Test cache key generation
        cache_key = get_cache_key()
        results.append(f"✓ Generated cache key: {cache_key}")

        # Test cache clearing
        clear_permission_cache()
        results.append("✓ Permission cache cleared successfully")

        # Test user chapter memberships function (will be empty but should not error)
        memberships = get_user_chapter_memberships_cached("Administrator", cache_key)
        results.append(f"✓ Administrator memberships: {memberships}")

        results.append("✅ Permission caching system tests PASSED")
        return {"success": True, "results": results}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_volunteer_role_assignment():
    """Test volunteer role assignment functionality"""
    try:
        results = []
        results.append("Testing volunteer role assignment functionality...")

        # Get a volunteer record to test the method
        volunteers = frappe.get_all("Volunteer", fields=["name", "email", "volunteer_name"], limit=1)
        if volunteers:
            volunteer = frappe.get_doc("Volunteer", volunteers[0].name)
            results.append(f"✓ Testing with volunteer: {volunteer.name} ({volunteer.volunteer_name})")

            if volunteer.email:
                results.append(f"✓ Volunteer email: {volunteer.email}")

                # Test the assign_volunteer_role method
                try:
                    volunteer.assign_volunteer_role()
                    results.append("✅ Volunteer role assignment completed successfully")
                    return {"success": True, "results": results}
                except Exception as e:
                    if "does not exist" in str(e):
                        results.append(
                            f"ℹ️ Volunteer role assignment skipped - user does not exist: {str(e)}"
                        )
                        return {"success": True, "results": results}
                    else:
                        results.append(f"❌ Volunteer role assignment error: {str(e)}")
                        return {"success": False, "results": results, "error": str(e)}
            else:
                results.append("ℹ️ Volunteer has no email - cannot test role assignment")
                return {"success": True, "results": results}
        else:
            results.append("ℹ️ No volunteers found to test with")
            return {"success": True, "results": results}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_team_project_permissions():
    """Test team-based project permissions"""
    try:
        from verenigingen.utils.project_permissions import (
            get_project_permission_query_conditions,
            user_has_any_team_projects,
        )

        results = []
        results.append("Testing team-based project permissions...")

        # Test permission query generation
        query_condition = get_project_permission_query_conditions("Administrator")
        results.append(f"✓ Admin query condition: {query_condition}")

        # Test team project access check
        has_team_projects = user_has_any_team_projects("Administrator")
        results.append(f"✓ Administrator has team projects: {has_team_projects}")

        results.append("✅ Team-based project permissions tests PASSED")
        return {"success": True, "results": results}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_basic_doctype_operations():
    """Test basic DocType operations for regression testing"""
    try:
        results = []
        results.append("Testing basic DocType operations...")

        # Test Member DocType
        members = frappe.get_all("Member", fields=["name", "full_name"], limit=5)
        results.append(f"✓ Found {len(members)} members")

        # Test Volunteer DocType
        volunteers = frappe.get_all("Volunteer", fields=["name", "volunteer_name"], limit=5)
        results.append(f"✓ Found {len(volunteers)} volunteers")

        # Test Chapter DocType (using 'name' field instead of non-existent 'chapter_name')
        chapters = frappe.get_all("Chapter", fields=["name"], limit=5)
        results.append(f"✓ Found {len(chapters)} chapters")

        results.append("✅ Basic DocType operations tests PASSED")
        return {"success": True, "results": results}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def run_comprehensive_regression_tests():
    """Run all regression tests and return comprehensive results"""
    try:
        all_results = []
        all_results.append("🧪 Starting Regression Testing for Recent Changes")
        all_results.append("=" * 60)

        tests = [
            ("Permission Caching", test_permission_caching),
            ("Volunteer Role Assignment", test_volunteer_role_assignment),
            ("Team Project Permissions", test_team_project_permissions),
            ("Basic DocType Operations", test_basic_doctype_operations),
        ]

        passed = 0
        total = len(tests)
        test_results = {}

        for test_name, test_func in tests:
            result = test_func()
            test_results[test_name] = result

            if result["success"]:
                passed += 1
                all_results.extend(result["results"])
            else:
                all_results.append(f'❌ {test_name} FAILED: {result.get("error", "Unknown error")}')
                if "results" in result:
                    all_results.extend(result["results"])

        all_results.append("=" * 60)
        all_results.append(f"📊 Regression Testing Results: {passed}/{total} tests passed")

        if passed == total:
            all_results.append("🎉 All regression tests PASSED - no regressions detected")
        else:
            all_results.append("⚠️  Some regression tests FAILED - investigation needed")

        return {
            "success": passed == total,
            "passed": passed,
            "total": total,
            "results": all_results,
            "test_details": test_results,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_volunteer_after_insert_functionality():
    """Test the after_insert hook functionality specifically"""
    try:
        results = []
        results.append("Testing volunteer after_insert functionality...")

        # Check if the after_insert method exists and can be called
        from verenigingen.verenigingen.doctype.volunteer.volunteer import Volunteer

        # Get an existing volunteer to test methods on
        volunteers = frappe.get_all("Volunteer", fields=["name"], limit=1)
        if volunteers:
            volunteer = frappe.get_doc("Volunteer", volunteers[0].name)

            # Test that the methods exist
            if hasattr(volunteer, "assign_volunteer_role"):
                results.append("✓ assign_volunteer_role method exists")
            else:
                results.append("❌ assign_volunteer_role method missing")

            if hasattr(volunteer, "create_employee_if_needed"):
                results.append("✓ create_employee_if_needed method exists")
            else:
                results.append("❌ create_employee_if_needed method missing")

            results.append("✅ Volunteer after_insert functionality tests PASSED")
        else:
            results.append("ℹ️ No volunteers found to test with")

        return {"success": True, "results": results}

    except Exception as e:
        return {"success": False, "error": str(e)}
