#!/usr/bin/env python3
"""
Membership Types API Tester
Tests the membership types API functionality for debugging and validation.
"""

import frappe


@frappe.whitelist()
def test_membership_types_api(test_user_email=None):
    """Test the get_available_membership_types API to check fee information

    Args:
        test_user_email: Email of user to test API as (default: current user)
    """

    original_user = frappe.session.user
    try:
        # Import and call the function
        from verenigingen.templates.pages.membership_fee_adjustment import get_available_membership_types

        # Set test user session if provided
        if test_user_email:
            if not frappe.db.exists("User", test_user_email):
                return {"error": f"User {test_user_email} does not exist"}
            frappe.session.user = test_user_email

        current_user = frappe.session.user

        # Call the API
        result = get_available_membership_types()

        # Format results for better readability
        formatted_result = {
            "test_user": current_user,
            "current_type": result.get("current_type"),
            "membership_types_count": len(result.get("membership_types", [])),
            "membership_types": [],
            "raw_result": result,
        }

        for mt in result.get("membership_types", []):
            formatted_result["membership_types"].append(
                {
                    "name": mt.get("name"),
                    "display_name": mt.get("membership_type_name"),
                    "amount": f"€{mt.get('amount', 0):.2f}",
                    "minimum": f"€{mt.get('minimum_amount', 0):.2f}",
                    "description": mt.get("description", "N/A"),
                    "is_active": mt.get("is_active", False),
                }
            )

        return formatted_result

    except Exception as e:
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc(), "test_user": frappe.session.user}
    finally:
        frappe.session.user = original_user


@frappe.whitelist()
def test_api_for_multiple_users(user_emails=None):
    """Test the membership types API for multiple users

    Args:
        user_emails: List of user emails to test (default: gets sample members)
    """

    if not user_emails:
        # Get sample users who are members
        sample_users = frappe.get_all(
            "Member", filters={"user": ["!=", ""]}, fields=["user", "first_name", "last_name"], limit=5
        )
        user_emails = [u.user for u in sample_users if u.user]

    results = []
    for email in user_emails:
        test_result = test_membership_types_api(email)
        test_result["user_email"] = email
        results.append(test_result)

    return {"total_users_tested": len(results), "results": results}
