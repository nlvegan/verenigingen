#!/usr/bin/env python3

"""
Test script to debug the custom amount flow from member application to subscription
"""

import json
import re

import frappe


def test_custom_amount_extraction():
    """Test the extraction of custom amount data from member notes"""

    # Test sample member notes with custom amount data
    sample_notes = """
Some general notes about the member.

Custom Amount Data: {"membership_amount": 45.0, "uses_custom_amount": true}

Additional notes here.
"""

    print("Testing custom amount extraction...")
    print(f"Sample notes: {sample_notes}")

    # Test the regex pattern used in get_member_custom_amount_data
    pattern = r"Custom Amount Data: (\{[^}]*\})"
    match = re.search(pattern, sample_notes, re.DOTALL)

    if match:
        json_str = match.group(1)
        print(f"Extracted JSON string: {json_str}")

        try:
            data = json.loads(json_str)
            print(f"Parsed data: {data}")
            print(f"Uses custom amount: {data.get('uses_custom_amount')}")
            print(f"Membership amount: {data.get('membership_amount')}")
            return data
        except Exception as e:
            print(f"Error parsing JSON: {e}")
            return None
    else:
        print("No match found!")
        return None


def test_with_real_member(member_name):
    """Test with a real member record"""
    try:
        member = frappe.get_doc("Member", member_name)
        print(f"\nTesting with real member: {member_name}")
        print(f"Member notes: {member.notes}")

        # Test extraction
        from verenigingen.utils.application_helpers import get_member_custom_amount_data

        custom_data = get_member_custom_amount_data(member)

        print(f"Extracted custom data: {custom_data}")

        if custom_data:
            print(f"Uses custom amount: {custom_data.get('uses_custom_amount')}")
            print(f"Membership amount: {custom_data.get('membership_amount')}")

        return custom_data

    except Exception as e:
        print(f"Error testing with member {member_name}: {e}")
        return None


def test_membership_creation_flow(member_name):
    """Test the full flow from member to membership"""
    try:
        member = frappe.get_doc("Member", member_name)
        print(f"\nTesting membership creation flow for: {member_name}")

        # Extract custom amount data
        from verenigingen.utils.application_helpers import get_member_custom_amount_data

        custom_amount_data = get_member_custom_amount_data(member)

        print(f"Step 1 - Custom amount data: {custom_amount_data}")

        if custom_amount_data and custom_amount_data.get("uses_custom_amount"):
            membership_amount = custom_amount_data.get("membership_amount")
            print(f"Step 2 - Would set membership.uses_custom_amount = 1")
            print(f"Step 3 - Would set membership.custom_amount = {membership_amount}")

            # Check if this would work in subscription creation
            print(f"Step 4 - Subscription would use amount: {membership_amount}")
        else:
            print("Step 2 - No custom amount data found")

    except Exception as e:
        print(f"Error in membership creation flow: {e}")


if __name__ == "__main__":
    # Initialize Frappe
    frappe.init()
    frappe.connect()

    print("=== Testing Custom Amount Flow ===")

    # Test 1: Test extraction logic with sample data
    test_custom_amount_extraction()

    # Test 2: Test with real member (you'll need to provide a member name)
    # Replace with actual member name that has custom amount
    test_member_name = "Assoc-Member-2025-06-0131"  # The one mentioned in the conversation

    try:
        test_with_real_member(test_member_name)
        test_membership_creation_flow(test_member_name)
    except Exception as e:
        print(f"Could not test with member {test_member_name}: {e}")
        print("Try with a different member name or check if the member exists")

    print("\n=== Test Complete ===")
