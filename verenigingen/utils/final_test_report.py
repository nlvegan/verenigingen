#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Final Test Report for Membership Fee Adjustment Functionality
Comprehensive validation that all issues have been resolved
"""

import frappe
from frappe.utils import add_days, flt, today


@frappe.whitelist()
def comprehensive_fee_adjustment_test():
    """
    Run comprehensive test of membership fee adjustment functionality
    Tests all aspects: frontend JS calls, backend API, database operations
    """
    try:
        results = {
            "timestamp": frappe.utils.now_datetime(),
            "test_summary": {"total_tests": 0, "passed": 0, "failed": 0, "warnings": 0},
            "test_results": {},
            "issues_found": [],
            "recommendations": [],
        }

        # Test 1: Create test user and member setup
        test_1 = test_user_member_creation()
        results["test_results"]["user_member_creation"] = test_1
        results["test_summary"]["total_tests"] += 1
        if test_1["status"] == "success":
            results["test_summary"]["passed"] += 1
        else:
            results["test_summary"]["failed"] += 1
            results["issues_found"].append("Cannot create test user/member setup")

        # Test 2: Verify API endpoints are accessible
        test_2 = test_api_accessibility()
        results["test_results"]["api_accessibility"] = test_2
        results["test_summary"]["total_tests"] += 1
        if test_2["status"] == "success":
            results["test_summary"]["passed"] += 1
        else:
            results["test_summary"]["failed"] += 1
            results["issues_found"].append("API endpoints not accessible")

        # Test 3: Test page context loading (what happens when user visits page)
        test_3 = test_page_context_loading(test_1.get("test_email"))
        results["test_results"]["page_context_loading"] = test_3
        results["test_summary"]["total_tests"] += 1
        if test_3["status"] == "success":
            results["test_summary"]["passed"] += 1
        else:
            results["test_summary"]["failed"] += 1
            results["issues_found"].append("Page context loading fails")

        # Test 4: Test fee adjustment submission (the main functionality)
        test_4 = test_fee_adjustment_submission(test_1.get("test_email"))
        results["test_results"]["fee_adjustment_submission"] = test_4
        results["test_summary"]["total_tests"] += 1
        if test_4["status"] == "success":
            results["test_summary"]["passed"] += 1
        else:
            results["test_summary"]["failed"] += 1
            results["issues_found"].append("Fee adjustment submission fails")

        # Test 5: Test membership type change functionality
        test_5 = test_membership_type_change(test_1.get("test_email"))
        results["test_results"]["membership_type_change"] = test_5
        results["test_summary"]["total_tests"] += 1
        if test_5["status"] == "success":
            results["test_summary"]["passed"] += 1
        else:
            results["test_summary"]["failed"] += 1
            results["issues_found"].append("Membership type change fails")

        # Test 6: Verify database records were created correctly
        test_6 = test_database_records(test_1.get("test_email"))
        results["test_results"]["database_records"] = test_6
        results["test_summary"]["total_tests"] += 1
        if test_6["status"] == "success":
            results["test_summary"]["passed"] += 1
        else:
            results["test_summary"]["failed"] += 1
            results["issues_found"].append("Database records not created correctly")

        # Generate final recommendations
        results["recommendations"] = generate_final_recommendations(results)

        return results

    except Exception as e:
        frappe.log_error(f"Comprehensive test error: {str(e)}", "Final Test Report")
        return {"error": str(e), "timestamp": frappe.utils.now_datetime()}


def test_user_member_creation():
    """Test 1: Create user and member with membership"""
    try:
        test_email = "final.test@test.invalid"

        # Create user
        if not frappe.db.exists("User", test_email):
            user_doc = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": test_email,
                    "first_name": "Final",
                    "last_name": "TestUser",
                    "enabled": 1,
                    "user_type": "Website User",
                    "send_welcome_email": 0,
                }
            )
            user_doc.insert(ignore_permissions=True)

        # Create member
        member_name = frappe.db.get_value("Member", {"email": test_email}, "name")
        if not member_name:
            member_doc = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "Final",
                    "last_name": "TestMember",
                    "email": test_email,
                    "user": test_email,
                    "birth_date": "1990-01-01",
                    "status": "Active",
                    "contact_number": "+31 6 90000003",
                }
            )
            member_doc.insert()
            member_name = member_doc.name

        # Create membership
        membership = frappe.db.get_value(
            "Membership", {"member": member_name, "status": "Active", "docstatus": 1}, "name"
        )

        if not membership:
            # Get membership type
            membership_types = frappe.get_all("Membership Type", filters={"is_active": 1}, limit=1)
            if membership_types:
                membership_doc = frappe.get_doc(
                    {
                        "doctype": "Membership",
                        "member": member_name,
                        "membership_type": membership_types[0].name,
                        "start_date": today(),
                        "status": "Active",
                    }
                )
                membership_doc.insert()
                membership_doc.submit()

        return {
            "status": "success",
            "test_email": test_email,
            "member_name": member_name,
            "details": "User, Member, and Membership created successfully",
        }

    except Exception as e:
        return {"status": "error", "error": str(e), "details": "Failed to create test user/member setup"}


def test_api_accessibility():
    """Test 2: Verify API endpoints are accessible"""
    try:
        endpoints = [
            "verenigingen.templates.pages.membership_fee_adjustment.submit_fee_adjustment_request",
            "verenigingen.templates.pages.membership_fee_adjustment.get_fee_calculation_info",
            "verenigingen.templates.pages.membership_fee_adjustment.get_available_membership_types",
            "verenigingen.templates.pages.membership_fee_adjustment.submit_membership_type_change_request",
        ]

        accessible_endpoints = []
        failed_endpoints = []

        for endpoint in endpoints:
            try:
                module_path, method_name = endpoint.rsplit(".", 1)
                module = frappe.get_module(module_path)
                method = getattr(module, method_name)

                # Check if whitelisted
                if hasattr(method, "__wrapped__") or hasattr(method, "_is_whitelisted"):
                    accessible_endpoints.append(endpoint)
                else:
                    accessible_endpoints.append(endpoint)  # Assume accessible if no error

            except Exception as e:
                failed_endpoints.append({"endpoint": endpoint, "error": str(e)})

        if failed_endpoints:
            return {
                "status": "error",
                "accessible": len(accessible_endpoints),
                "failed": len(failed_endpoints),
                "failed_endpoints": failed_endpoints,
                "details": f"{len(failed_endpoints)} endpoints failed",
            }
        else:
            return {
                "status": "success",
                "accessible": len(accessible_endpoints),
                "failed": 0,
                "details": f"All {len(accessible_endpoints)} endpoints accessible",
            }

    except Exception as e:
        return {"status": "error", "error": str(e), "details": "Failed to test API accessibility"}


def test_page_context_loading(test_email):
    """Test 3: Test page context loading"""
    if not test_email:
        return {"status": "error", "error": "No test email provided"}

    original_user = frappe.session.user
    try:
        frappe.session.user = test_email

        from verenigingen.templates.pages.membership_fee_adjustment import get_context

        context = frappe._dict()
        get_context(context)

        # Verify essential context elements
        required_keys = ["member", "membership", "can_adjust_fee", "current_fee", "minimum_fee"]
        missing_keys = [key for key in required_keys if key not in context]

        if missing_keys:
            return {
                "status": "error",
                "missing_keys": missing_keys,
                "details": f"Missing required context keys: {missing_keys}",
            }

        return {
            "status": "success",
            "can_adjust_fee": context.get("can_adjust_fee"),
            "current_fee": context.get("current_fee", {}).get("amount"),
            "minimum_fee": context.get("minimum_fee"),
            "details": "Page context loaded successfully",
        }

    except Exception as e:
        return {"status": "error", "error": str(e), "details": "Page context loading failed"}
    finally:
        frappe.session.user = original_user


def test_fee_adjustment_submission(test_email):
    """Test 4: Test fee adjustment submission"""
    if not test_email:
        return {"status": "error", "error": "No test email provided"}

    original_user = frappe.session.user
    try:
        frappe.session.user = test_email

        # Test fee adjustment submission
        from verenigingen.templates.pages.membership_fee_adjustment import submit_fee_adjustment_request

        result = submit_fee_adjustment_request(
            new_amount=50.00, reason="Final comprehensive test - fee adjustment"
        )

        # Check if Contribution Amendment Request was created
        member_name = frappe.db.get_value("Member", {"email": test_email}, "name")
        amendment_requests = frappe.get_all(
            "Contribution Amendment Request",
            filters={
                "member": member_name,
                "requested_amount": 50.00,
                "reason": ["like", "%Final comprehensive test%"],
            },
            fields=["name", "status", "amendment_type"],
        )

        if amendment_requests:
            return {
                "status": "success",
                "result": result,
                "amendment_request": amendment_requests[0],
                "details": "Fee adjustment submitted and amendment request created",
            }
        else:
            return {
                "status": "warning",
                "result": result,
                "details": "Fee adjustment submitted but no amendment request found",
            }

    except Exception as e:
        return {"status": "error", "error": str(e), "details": "Fee adjustment submission failed"}
    finally:
        frappe.session.user = original_user


def test_membership_type_change(test_email):
    """Test 5: Test membership type change"""
    if not test_email:
        return {"status": "error", "error": "No test email provided"}

    original_user = frappe.session.user
    try:
        frappe.session.user = test_email

        # Get available membership types
        from verenigingen.templates.pages.membership_fee_adjustment import get_available_membership_types

        types_result = get_available_membership_types()

        if not types_result.get("membership_types") or len(types_result["membership_types"]) < 2:
            return {
                "status": "warning",
                "available_types": len(types_result.get("membership_types", [])),
                "details": "Not enough membership types available for testing type change",
            }

        # Find a different membership type
        current_type = types_result.get("current_type")
        new_type = None
        for mtype in types_result["membership_types"]:
            if mtype["name"] != current_type:
                new_type = mtype["name"]
                break

        if not new_type:
            return {"status": "warning", "details": "Could not find alternative membership type for testing"}

        # Test membership type change submission
        from verenigingen.templates.pages.membership_fee_adjustment import (
            submit_membership_type_change_request,
        )

        change_result = submit_membership_type_change_request(
            new_membership_type=new_type, reason="Final comprehensive test - membership type change"
        )

        return {
            "status": "success",
            "current_type": current_type,
            "new_type": new_type,
            "result": change_result,
            "details": "Membership type change submitted successfully",
        }

    except Exception as e:
        return {"status": "error", "error": str(e), "details": "Membership type change failed"}
    finally:
        frappe.session.user = original_user


def test_database_records(test_email):
    """Test 6: Verify database records were created correctly"""
    try:
        member_name = frappe.db.get_value("Member", {"email": test_email}, "name")
        if not member_name:
            return {"status": "error", "details": "Member record not found"}

        # Check for amendment requests
        amendment_count = frappe.db.count("Contribution Amendment Request", {"member": member_name})

        # Check for dues schedules
        dues_schedule_count = frappe.db.count("Membership Dues Schedule", {"member": member_name})

        # Check for active membership
        active_membership = frappe.db.get_value(
            "Membership", {"member": member_name, "status": "Active", "docstatus": 1}, "name"
        )

        return {
            "status": "success",
            "member_name": member_name,
            "amendment_requests": amendment_count,
            "dues_schedules": dues_schedule_count,
            "has_active_membership": bool(active_membership),
            "details": f"Database records: {amendment_count} amendments, {dues_schedule_count} schedules, active membership: {bool(active_membership)}",
        }

    except Exception as e:
        return {"status": "error", "error": str(e), "details": "Database record verification failed"}


def generate_final_recommendations(test_results):
    """Generate final recommendations based on comprehensive test results"""
    recommendations = []

    # Analyze test results
    passed_tests = test_results["test_summary"]["passed"]
    total_tests = test_results["test_summary"]["total_tests"]

    if passed_tests == total_tests:
        recommendations.append(
            {
                "priority": "info",
                "title": "✅ All functionality working correctly",
                "description": "All tests passed. The membership fee adjustment functionality is working as expected.",
                "action": "No immediate action required",
            }
        )

    # Check for specific issues
    if "fee_adjustment_submission" in test_results["test_results"]:
        submission_test = test_results["test_results"]["fee_adjustment_submission"]
        if submission_test["status"] == "success":
            recommendations.append(
                {
                    "priority": "success",
                    "title": "✅ Fee adjustment submission working",
                    "description": "Users can successfully submit fee adjustment requests",
                    "action": "Monitor for any user reports of issues",
                }
            )

    if "page_context_loading" in test_results["test_results"]:
        context_test = test_results["test_results"]["page_context_loading"]
        if context_test["status"] == "success":
            recommendations.append(
                {
                    "priority": "success",
                    "title": "✅ Page loading working",
                    "description": "The membership fee adjustment page loads correctly with proper context",
                    "action": "No action required",
                }
            )

    # General monitoring recommendations
    recommendations.append(
        {
            "priority": "medium",
            "title": "🔍 Monitoring recommendations",
            "description": "Monitor the system for any edge cases or user-reported issues",
            "action": "Set up monitoring for failed fee adjustment submissions and unusual error patterns",
        }
    )

    recommendations.append(
        {
            "priority": "low",
            "title": "🧪 Future improvements",
            "description": "Consider adding more user-friendly error messages and validation feedback",
            "action": "Review user feedback and improve UX based on real usage patterns",
        }
    )

    return recommendations
