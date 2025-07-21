#!/usr/bin/env python3
"""Debug API functions"""

import frappe
from frappe.utils import today

from verenigingen.api.membership_application import submit_application


@frappe.whitelist()
def test_membership_application():
    """Debug application submission"""

    # Sample application data
    test_data = {
        "first_name": "Debug",
        "last_name": "Tester",
        "email": "debug.test.duplicate@example.com",  # Fixed email for duplicate test
        "birth_date": "1990-01-01",
        "address_line1": "123 Test Street",
        "city": "Amsterdam",
        "postal_code": "1234AB",
        "country": "Netherlands",
        "contact_number": "+31612345678",
        "interested_in_volunteering": 0,
        "newsletter_opt_in": 1,
        "application_source": "Website",
    }

    print("Testing membership application submission...")
    print("Application data:")
    for key, value in test_data.items():
        print(f"  {key}: {value}")

    print("\nCalling submit_application...")
    try:
        result = submit_application(**test_data)
        print(f"\nResult: {result}")

        if result.get("success"):
            print("\n✅ Success! Application submitted.")
            print(f"Member record: {result.get('member_record')}")
            print(f"Application ID: {result.get('application_id')}")
        else:
            print(f"\n❌ Failed: {result.get('error', 'Unknown error')}")
            if "message" in result:
                print(f"Message: {result['message']}")
            if "issues" in result:
                print(f"Issues: {result['issues']}")

        return result

    except Exception as e:
        print(f"\n💥 Exception: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e)}
