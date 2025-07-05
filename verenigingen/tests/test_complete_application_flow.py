"""
Test complete application submission flow with special characters
"""

import frappe


@frappe.whitelist()
def test_complete_application_submission():
    """Test the complete application submission with special characters"""

    try:
        # Test data with special characters that previously failed
        test_data = {
            "first_name": "José María",
            "last_name": "García-López",
            "email": "jose.maria.complete.test@example.com",
            "birth_date": "1985-03-15",
            "address_line1": "Calle de los Ángeles 123",
            "city": "Amsterdam",
            "postal_code": "1000AA",
            "country": "Netherlands",
            "selected_membership_type": "Test Membership",
            "interested_in_volunteering": 0,
            "payment_method": "Bank Transfer",
        }

        # Import and call the actual API function
        from verenigingen.api.membership_application import submit_application

        result = submit_application(data=test_data)

        # Check the result
        if result.get("success"):
            application_id = result.get("application_id")
            member_record = result.get("member_record")

            # Verify the member was created with correct data
            member = frappe.get_doc("Member", member_record)

            verification = {
                "application_successful": True,
                "application_id": application_id,
                "first_name_stored": member.first_name,
                "last_name_stored": member.last_name,
                "email_stored": member.email,
                "status": member.application_status,
                "names_match": (member.first_name == "José María" and member.last_name == "García-López"),
            }

            # Check if address was created properly
            if member.primary_address:
                address = frappe.get_doc("Address", member.primary_address)
                verification["address_title"] = address.address_title
                verification["address_created"] = True
            else:
                verification["address_created"] = False

            # Clean up test data
            if member.primary_address:
                frappe.delete_doc("Address", member.primary_address, force=True)
            frappe.delete_doc("Member", member_record, force=True)
            frappe.db.commit()

            return {
                "success": True,
                "message": "Complete application submission with special characters successful",
                "verification": verification,
            }
        else:
            return {
                "success": False,
                "message": f"Application submission failed: {result.get('message')}",
                "error": result.get("error"),
                "full_result": result,
            }

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "message": f"Test failed with exception: {str(e)}", "error": str(e)}


if __name__ == "__main__":
    result = test_complete_application_submission()
    print(result)
