#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Debugging Script for Membership Fee Adjustment Functionality

This script tests the API endpoints directly, checks permissions, validates data,
and creates a whitelisted debug function that can be called from bench console or browser.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today


@frappe.whitelist()
def debug_membership_fee_adjustment():
    """
    Whitelisted function to debug membership fee adjustment functionality
    Can be called from:
    - bench --site dev.veganisme.net execute verenigingen.utils.debug_membership_fee_adjustment.debug_membership_fee_adjustment
    - Browser console: frappe.call({method: 'verenigingen.utils.debug_membership_fee_adjustment.debug_membership_fee_adjustment'})
    """
    try:
        results = {"timestamp": frappe.utils.now_datetime(), "user": frappe.session.user, "tests": {}}

        # Test 1: Check DocType exists and permissions
        results["tests"]["doctype_check"] = test_doctype_existence()

        # Test 2: Check API endpoint accessibility
        results["tests"]["api_endpoints"] = test_api_endpoints()

        # Test 3: Check for test members
        results["tests"]["test_members"] = find_or_create_test_member()

        # Test 4: Test the submit_fee_adjustment_request function directly
        results["tests"]["fee_adjustment_test"] = test_fee_adjustment_function()

        # Test 5: Check permissions and settings
        results["tests"]["permissions_settings"] = test_permissions_and_settings()

        # Test 6: Test membership type change functionality
        results["tests"]["membership_type_change"] = test_membership_type_change()

        # Generate recommendations
        results["recommendations"] = generate_recommendations(results["tests"])

        return results

    except Exception as e:
        frappe.log_error(f"Debug script error: {str(e)}", "Membership Fee Adjustment Debug")
        return {"error": str(e), "timestamp": frappe.utils.now_datetime(), "user": frappe.session.user}


def test_doctype_existence():
    """Test if required DocTypes exist and have proper structure"""
    test_results = {"status": "success", "message": "All required DocTypes exist", "details": {}}

    required_doctypes = [
        "Member",
        "Membership",
        "Membership Type",
        "Contribution Amendment Request",
        "Membership Dues Schedule",
        "Verenigingen Settings",
    ]

    for doctype in required_doctypes:
        try:
            meta = frappe.get_meta(doctype)
            test_results["details"][doctype] = {
                "exists": True,
                "field_count": len(meta.fields),
                "permissions": len(meta.permissions) if meta.permissions else 0,
            }
        except frappe.DoesNotExistError:
            test_results["status"] = "error"
            test_results["message"] = f"Missing DocType: {doctype}"
            test_results["details"][doctype] = {"exists": False}
        except Exception as e:
            test_results["status"] = "error"
            test_results["message"] = f"Error checking {doctype}: {str(e)}"
            test_results["details"][doctype] = {"error": str(e)}

    return test_results


def test_api_endpoints():
    """Test if API endpoints are properly whitelisted and accessible"""
    test_results = {"status": "success", "message": "API endpoints accessible", "endpoints": {}}

    endpoints = [
        "verenigingen.templates.pages.membership_fee_adjustment.submit_fee_adjustment_request",
        "verenigingen.templates.pages.membership_fee_adjustment.get_fee_calculation_info",
        "verenigingen.templates.pages.membership_fee_adjustment.get_available_membership_types",
        "verenigingen.templates.pages.membership_fee_adjustment.submit_membership_type_change_request",
    ]

    for endpoint in endpoints:
        try:
            # Check if method is whitelisted
            method_parts = endpoint.split(".")
            module_path = ".".join(method_parts[:-1])
            method_name = method_parts[-1]

            # Try to import the module
            module = frappe.get_module(module_path)
            if hasattr(module, method_name):
                method = getattr(module, method_name)
                is_whitelisted = hasattr(method, "_is_whitelisted") or getattr(
                    method, "is_whitelisted", False
                )
                test_results["endpoints"][endpoint] = {"exists": True, "whitelisted": is_whitelisted}
            else:
                test_results["endpoints"][endpoint] = {"exists": False, "error": "Method not found"}

        except Exception as e:
            test_results["endpoints"][endpoint] = {"exists": False, "error": str(e)}

    return test_results


def find_or_create_test_member():
    """Find existing test member or create one for testing"""
    test_results = {"status": "success", "message": "Test member available", "member_info": {}}

    try:
        # Look for existing test members
        test_members = frappe.get_all(
            "Member",
            filters={"email": ["like", "%test%"]},
            fields=["name", "email", "first_name", "last_name", "status"],
            limit=5,
        )

        if test_members:
            test_member = test_members[0]
            test_results["member_info"] = {
                "found_existing": True,
                "member_name": test_member.name,
                "email": test_member.email,
                "status": test_member.status,
            }

            # Check if member has active membership
            membership = frappe.db.get_value(
                "Membership",
                {"member": test_member.name, "status": "Active", "docstatus": 1},
                ["name", "membership_type", "start_date"],
                as_dict=True,
            )

            test_results["member_info"]["has_active_membership"] = bool(membership)
            if membership:
                test_results["member_info"]["membership"] = membership

        else:
            # Create simple test member
            try:
                # Check if we have required data
                membership_types = frappe.get_all("Membership Type", limit=1)
                if not membership_types:
                    # Create basic membership type
                    membership_type = frappe.get_doc(
                        {
                            "doctype": "Membership Type",
                            "membership_type_name": "TEST Standard",
                            "amount": 25.00,
                            "currency": "EUR",
                            "is_active": 1,
                        }
                    )
                    membership_type.insert()
                else:
                    membership_type = frappe.get_doc("Membership Type", membership_types[0].name)

                # Create test member
                test_member = frappe.get_doc(
                    {
                        "doctype": "Member",
                        "first_name": "Debug",
                        "last_name": "TestMember",
                        "email": "debug.test.member@test.invalid",
                        "birth_date": "1990-01-01",
                        "status": "Active",
                    }
                )
                test_member.insert()

                # Create active membership
                membership = frappe.get_doc(
                    {
                        "doctype": "Membership",
                        "member": test_member.name,
                        "membership_type": membership_type.name,
                        "start_date": today(),
                        "status": "Active",
                    }
                )
                membership.insert()
                membership.submit()

                test_results["member_info"] = {
                    "found_existing": False,
                    "member_name": test_member.name,
                    "email": test_member.email,
                    "status": test_member.status,
                    "created_new": True,
                    "has_active_membership": True,
                    "membership": {
                        "name": membership.name,
                        "membership_type": membership.membership_type,
                        "start_date": membership.start_date,
                    },
                }

            except Exception as create_error:
                test_results["status"] = "error"
                test_results["message"] = f"Could not create test member: {str(create_error)}"
                test_results["error"] = str(create_error)

    except Exception as e:
        test_results["status"] = "error"
        test_results["message"] = f"Error with test member: {str(e)}"
        test_results["error"] = str(e)
        frappe.log_error(f"Test member creation error: {str(e)}", "Debug Member Creation")

    return test_results


def test_fee_adjustment_function():
    """Test the submit_fee_adjustment_request function directly"""
    test_results = {"status": "success", "message": "Fee adjustment function works", "tests": {}}

    try:
        # Get or create test member first
        member_result = find_or_create_test_member()
        if member_result["status"] != "success":
            test_results["status"] = "error"
            test_results["message"] = "Could not get test member"
            return test_results

        member_name = member_result["member_info"]["member_name"]

        # Test 1: Get fee calculation info
        try:
            # Temporarily set session user to member's email
            original_user = frappe.session.user
            member_doc = frappe.get_doc("Member", member_name)
            frappe.session.user = member_doc.email

            from verenigingen.templates.pages.membership_fee_adjustment import get_fee_calculation_info

            fee_info = get_fee_calculation_info()

            test_results["tests"]["fee_calculation_info"] = {"status": "success", "data": fee_info}

        except Exception as e:
            test_results["tests"]["fee_calculation_info"] = {"status": "error", "error": str(e)}
        finally:
            frappe.session.user = original_user

        # Test 2: Test fee adjustment submission
        try:
            frappe.session.user = member_doc.email

            from verenigingen.templates.pages.membership_fee_adjustment import submit_fee_adjustment_request

            # Try submitting a fee adjustment
            result = submit_fee_adjustment_request(new_amount=30.00, reason="Debug test fee adjustment")

            test_results["tests"]["fee_adjustment_submission"] = {"status": "success", "result": result}

        except Exception as e:
            test_results["tests"]["fee_adjustment_submission"] = {"status": "error", "error": str(e)}
        finally:
            frappe.session.user = original_user

        # Test 3: Check available membership types
        try:
            frappe.session.user = member_doc.email

            from verenigingen.templates.pages.membership_fee_adjustment import get_available_membership_types

            types_result = get_available_membership_types()

            test_results["tests"]["available_membership_types"] = {
                "status": "success",
                "result": types_result,
            }

        except Exception as e:
            test_results["tests"]["available_membership_types"] = {"status": "error", "error": str(e)}
        finally:
            frappe.session.user = original_user

    except Exception as e:
        test_results["status"] = "error"
        test_results["message"] = f"Function testing failed: {str(e)}"
        test_results["error"] = str(e)

    return test_results


def test_permissions_and_settings():
    """Test permissions and Verenigingen Settings"""
    test_results = {"status": "success", "message": "Permissions and settings OK", "details": {}}

    try:
        # Check Verenigingen Settings
        try:
            settings = frappe.get_single("Verenigingen Settings")
            test_results["details"]["verenigingen_settings"] = {
                "exists": True,
                "enable_member_fee_adjustment": getattr(settings, "enable_member_fee_adjustment", None),
                "max_adjustments_per_year": getattr(settings, "max_adjustments_per_year", None),
                "maximum_fee_multiplier": getattr(settings, "maximum_fee_multiplier", None),
                "member_contact_email": getattr(settings, "member_contact_email", None),
            }
        except Exception as e:
            test_results["details"]["verenigingen_settings"] = {"exists": False, "error": str(e)}

        # Check if user has required roles
        user_roles = frappe.get_roles(frappe.session.user)
        test_results["details"]["user_roles"] = user_roles

        # Check permissions on key DocTypes
        for doctype in ["Member", "Membership", "Contribution Amendment Request"]:
            try:
                has_create = frappe.has_permission(doctype, "create")
                has_read = frappe.has_permission(doctype, "read")
                has_write = frappe.has_permission(doctype, "write")

                test_results["details"][f"{doctype}_permissions"] = {
                    "create": has_create,
                    "read": has_read,
                    "write": has_write,
                }
            except Exception as e:
                test_results["details"][f"{doctype}_permissions"] = {"error": str(e)}

    except Exception as e:
        test_results["status"] = "error"
        test_results["message"] = f"Permissions check failed: {str(e)}"
        test_results["error"] = str(e)

    return test_results


def test_membership_type_change():
    """Test membership type change functionality"""
    test_results = {"status": "success", "message": "Membership type change works", "details": {}}

    try:
        # Get available membership types
        membership_types = frappe.get_all(
            "Membership Type",
            filters={"is_active": 1},
            fields=["name", "membership_type_name", "minimum_amount"],
        )

        test_results["details"]["available_types"] = len(membership_types)
        test_results["details"]["types"] = membership_types[:3]  # Show first 3

        if len(membership_types) < 2:
            test_results["status"] = "warning"
            test_results["message"] = "Need at least 2 membership types for testing"

    except Exception as e:
        test_results["status"] = "error"
        test_results["message"] = f"Membership type test failed: {str(e)}"
        test_results["error"] = str(e)

    return test_results


def generate_recommendations(test_results):
    """Generate recommendations based on test results"""
    recommendations = []

    # Check DocType issues
    if test_results.get("doctype_check", {}).get("status") == "error":
        recommendations.append(
            {
                "priority": "high",
                "issue": "Missing required DocTypes",
                "solution": "Run bench migrate or check app installation",
            }
        )

    # Check API endpoint issues
    api_test = test_results.get("api_endpoints", {})
    if api_test.get("endpoints"):
        for endpoint, result in api_test["endpoints"].items():
            if not result.get("whitelisted", False):
                recommendations.append(
                    {
                        "priority": "high",
                        "issue": f"API endpoint not whitelisted: {endpoint}",
                        "solution": "Add @frappe.whitelist() decorator to the function",
                    }
                )

    # Check member issues
    member_test = test_results.get("test_members", {})
    if member_test.get("status") == "error":
        recommendations.append(
            {
                "priority": "medium",
                "issue": "Cannot create/find test member",
                "solution": "Check Member DocType validation and required fields",
            }
        )

    # Check fee adjustment issues
    fee_test = test_results.get("fee_adjustment_test", {})
    if fee_test.get("status") == "error":
        recommendations.append(
            {
                "priority": "high",
                "issue": "Fee adjustment function failing",
                "solution": "Check error details and fix validation or business logic issues",
            }
        )

    # Check settings
    perm_test = test_results.get("permissions_settings", {})
    settings = perm_test.get("details", {}).get("verenigingen_settings", {})
    if not settings.get("exists"):
        recommendations.append(
            {
                "priority": "medium",
                "issue": "Verenigingen Settings not found",
                "solution": "Create Verenigingen Settings single DocType or check installation",
            }
        )
    elif settings.get("enable_member_fee_adjustment") is False:
        recommendations.append(
            {
                "priority": "medium",
                "issue": "Member fee adjustment disabled in settings",
                "solution": "Enable 'Enable Member Fee Adjustment' in Verenigingen Settings",
            }
        )

    return recommendations


@frappe.whitelist()
def test_api_directly(member_email=None, new_amount=35.00, reason="Direct API test"):
    """
    Test the API endpoints directly with specific parameters
    Can be called from browser console for real-time testing
    """
    try:
        results = {
            "timestamp": frappe.utils.now_datetime(),
            "test_parameters": {"member_email": member_email, "new_amount": new_amount, "reason": reason},
            "tests": {},
        }

        # Find test member if not specified
        if not member_email:
            test_members = frappe.get_all(
                "Member", filters={"email": ["like", "%test%"]}, fields=["email"], limit=1
            )
            if test_members:
                member_email = test_members[0].email
            else:
                return {"error": "No test member found"}

        # Test with the specified member
        original_user = frappe.session.user
        try:
            frappe.session.user = member_email

            # Test get_fee_calculation_info
            from verenigingen.templates.pages.membership_fee_adjustment import get_fee_calculation_info

            fee_info = get_fee_calculation_info()
            results["tests"]["fee_info"] = {"status": "success", "data": fee_info}

            # Test submit_fee_adjustment_request
            from verenigingen.templates.pages.membership_fee_adjustment import submit_fee_adjustment_request

            adjustment_result = submit_fee_adjustment_request(new_amount, reason)
            results["tests"]["fee_adjustment"] = {"status": "success", "result": adjustment_result}

        except Exception as e:
            results["tests"]["fee_adjustment"] = {"status": "error", "error": str(e)}
        finally:
            frappe.session.user = original_user

        return results

    except Exception as e:
        return {"error": str(e), "timestamp": frappe.utils.now_datetime()}


@frappe.whitelist()
def get_debug_summary():
    """Get a quick summary for debugging purposes"""
    try:
        summary = {"timestamp": frappe.utils.now_datetime(), "user": frappe.session.user, "quick_checks": {}}

        # Quick DocType check
        required_doctypes = ["Member", "Membership", "Contribution Amendment Request"]
        for doctype in required_doctypes:
            summary["quick_checks"][doctype] = frappe.db.exists("DocType", doctype)

        # Count test members
        test_member_count = frappe.db.count("Member", {"email": ["like", "%test%"]})
        summary["quick_checks"]["test_members"] = test_member_count

        # Check Verenigingen Settings
        try:
            settings = frappe.get_single("Verenigingen Settings")
            summary["quick_checks"]["settings_exist"] = True
            summary["quick_checks"]["fee_adjustment_enabled"] = getattr(
                settings, "enable_member_fee_adjustment", False
            )
        except:
            summary["quick_checks"]["settings_exist"] = False
            summary["quick_checks"]["fee_adjustment_enabled"] = False

        return summary

    except Exception as e:
        return {"error": str(e)}
