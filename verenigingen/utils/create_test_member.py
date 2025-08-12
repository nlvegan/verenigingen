#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Create Test Member with Active Membership for Fee Adjustment Testing
"""

import frappe
from frappe.utils import add_days, today


@frappe.whitelist()
def create_test_member_with_membership():
    """Create a test member with active membership for testing fee adjustment"""
    try:
        # Check if test member already exists
        existing_member = frappe.db.get_value("Member", {"email": "debug.feetest@test.invalid"}, "name")

        if existing_member:
            member_doc = frappe.get_doc("Member", existing_member)
            result = {"member": existing_member, "created_new": False}
        else:
            # Create test member
            member_doc = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "FeeTest",
                    "last_name": "Member",
                    "email": "debug.feetest@test.invalid",
                    "birth_date": "1990-01-01",
                    "status": "Active",
                    "contact_number": "+31 6 90000001",
                }
            )
            member_doc.insert()
            result = {"member": member_doc.name, "created_new": True}

        # Check for active membership
        membership = frappe.db.get_value(
            "Membership",
            {"member": member_doc.name, "status": "Active", "docstatus": 1},
            ["name", "membership_type"],
            as_dict=True,
        )

        if not membership:
            # Get or create membership type
            membership_types = frappe.get_all(
                "Membership Type",
                filters={"is_active": 1},
                fields=["name", "membership_type_name", "minimum_amount"],
                limit=1,
            )

            if not membership_types:
                # Create test membership type
                membership_type = frappe.get_doc(
                    {
                        "doctype": "Membership Type",
                        "membership_type_name": "Test Standard Membership",
                        "minimum_amount": 25.00,
                        "billing_period": "Yearly",
                        "billing_period_in_months": 12,
                        "is_active": 1,
                    }
                )
                membership_type.insert()
                membership_type_name = membership_type.name
                result["created_membership_type"] = True
            else:
                membership_type_name = membership_types[0].name
                result["created_membership_type"] = False

            # Create active membership
            membership_doc = frappe.get_doc(
                {
                    "doctype": "Membership",
                    "member": member_doc.name,
                    "membership_type": membership_type_name,
                    "start_date": today(),
                    "status": "Active",
                }
            )
            membership_doc.insert()
            membership_doc.submit()

            # Create dues schedule for the membership
            dues_schedule_doc = frappe.get_doc(
                {
                    "doctype": "Dues Schedule",
                    "member": member_doc.name,
                    "membership": membership_doc.name,
                    "amount": 25.00,
                    "frequency": "Yearly",
                    "start_date": today(),
                    "is_active": 1,
                    "status": "Active",
                }
            )
            dues_schedule_doc.insert()

            result["membership"] = membership_doc.name
            result["dues_schedule"] = dues_schedule_doc.name
            result["created_membership"] = True
        else:
            result["membership"] = membership.name
            result["created_membership"] = False

        # Add member details
        result["member_email"] = member_doc.email
        result["member_name"] = f"{member_doc.first_name} {member_doc.last_name}"

        return result

    except Exception as e:
        frappe.log_error(f"Error creating test member: {str(e)}", "Test Member Creation")
        return {"error": str(e)}


@frappe.whitelist()
def test_fee_adjustment_with_member(member_email="debug.feetest@test.invalid"):
    """Test fee adjustment functionality with specific member"""
    try:
        # Set session user to member email
        original_user = frappe.session.user
        frappe.session.user = member_email

        results = {"member_email": member_email, "timestamp": frappe.utils.now_datetime(), "tests": {}}

        try:
            # Test 1: Get fee calculation info
            from verenigingen.templates.pages.membership_fee_adjustment import get_fee_calculation_info

            fee_info = get_fee_calculation_info()
            results["tests"]["fee_calculation_info"] = {"status": "success", "data": fee_info}
        except Exception as e:
            results["tests"]["fee_calculation_info"] = {"status": "error", "error": str(e)}

        try:
            # Test 2: Submit fee adjustment
            from verenigingen.templates.pages.membership_fee_adjustment import submit_fee_adjustment_request

            adjustment_result = submit_fee_adjustment_request(
                new_amount=35.00, reason="Test fee adjustment via debug script"
            )
            results["tests"]["fee_adjustment"] = {"status": "success", "result": adjustment_result}
        except Exception as e:
            results["tests"]["fee_adjustment"] = {"status": "error", "error": str(e)}

        try:
            # Test 3: Get available membership types
            from verenigingen.templates.pages.membership_fee_adjustment import get_available_membership_types

            types_result = get_available_membership_types()
            results["tests"]["membership_types"] = {"status": "success", "result": types_result}
        except Exception as e:
            results["tests"]["membership_types"] = {"status": "error", "error": str(e)}

        return results

    except Exception as e:
        return {"error": str(e)}
    finally:
        frappe.session.user = original_user


@frappe.whitelist()
def get_member_context_debug(member_email="debug.feetest@test.invalid"):
    """Debug the get_context function for membership fee adjustment page"""
    try:
        # Set session user to member email
        original_user = frappe.session.user
        user_doc = frappe.get_doc("User", member_email)
        frappe.session.user = member_email

        try:
            from verenigingen.templates.pages.membership_fee_adjustment import get_context

            # Create a mock context object
            context = frappe._dict()

            # Call get_context
            get_context(context)

            # Return relevant context data
            result = {
                "status": "success",
                "context_keys": list(context.keys()),
                "member": context.get("member", {}).get("name") if context.get("member") else None,
                "membership": context.get("membership"),
                "can_adjust_fee": context.get("can_adjust_fee"),
                "current_fee": context.get("current_fee"),
                "minimum_fee": context.get("minimum_fee"),
                "standard_fee": context.get("standard_fee"),
                "error": None,
            }

            return result

        except Exception as e:
            return {"status": "error", "error": str(e), "error_type": type(e).__name__}
        finally:
            frappe.session.user = original_user

    except Exception as e:
        return {"error": f"Outer error: {str(e)}"}
