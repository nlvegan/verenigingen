#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def debug_custom_amount_flow(member_name):
    """Debug the custom amount flow for a specific member"""
    try:
        member = frappe.get_doc("Member", member_name)

        result = {
            "member_name": member_name,
            "full_name": member.full_name,
            "has_notes": bool(getattr(member, "notes", None)),
            "notes": getattr(member, "notes", ""),
            "custom_amount_data": None,
            "error": None,
        }

        # Test custom amount extraction
        from verenigingen.utils.application_helpers import get_member_custom_amount_data

        custom_data = get_member_custom_amount_data(member)

        result["custom_amount_data"] = custom_data

        if custom_data:
            result["uses_custom_amount"] = custom_data.get("uses_custom_amount")
            result["membership_amount"] = custom_data.get("membership_amount")

        # Check existing memberships
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member_name},
            fields=["name", "uses_custom_amount", "custom_amount", "subscription"],
        )

        result["memberships"] = memberships

        # Check subscriptions if any
        for membership in memberships:
            if membership.subscription:
                subscription = frappe.get_doc("Subscription", membership.subscription)
                membership["subscription_details"] = {"name": subscription.name, "plans": []}

                for plan in subscription.plans:
                    membership["subscription_details"]["plans"].append(
                        {"plan": plan.plan, "cost": plan.cost, "qty": plan.qty}
                    )

        return result

    except Exception as e:
        return {"error": str(e), "member_name": member_name}


@frappe.whitelist()
def test_custom_amount_regex():
    """Test the regex pattern used for custom amount extraction"""

    # Test cases
    test_cases = [
        'Custom Amount Data: {"membership_amount": 45.0, "uses_custom_amount": true}',
        'Some text\n\nCustom Amount Data: {"membership_amount": 30, "uses_custom_amount": false}\n\nMore text',
        'Custom Amount Data: {"membership_amount": 25.50, "uses_custom_amount": true, "extra": "data"}',
        "No custom data here",
        "Custom Amount Data: {malformed json}",
    ]

    import json
    import re

    results = []
    pattern = r"Custom Amount Data: (\{[^}]*\})"

    for i, test_text in enumerate(test_cases):
        result = {
            "test_case": i + 1,
            "input": test_text,
            "found_match": False,
            "extracted_json": None,
            "parsed_data": None,
            "error": None,
        }

        match = re.search(pattern, test_text, re.DOTALL)

        if match:
            result["found_match"] = True
            json_str = match.group(1)
            result["extracted_json"] = json_str

            try:
                data = json.loads(json_str)
                result["parsed_data"] = data
            except Exception as e:
                result["error"] = str(e)

        results.append(result)

    return results
