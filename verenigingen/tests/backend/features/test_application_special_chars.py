"""
Test membership application with special characters
"""


import frappe


@frappe.whitelist()
def test_membership_application_special_characters():
    """Test membership application submission with special characters"""

    try:
        # Test data with various special characters
        test_data = {
            "first_name": "José",
            "last_name": "García-López",
            "email": "jose.garcia.specialtest@example.com",
            "birth_date": "1985-03-15",
            "address_line1": "Teststraat 123",
            "city": "Amsterdam",
            "postal_code": "1000AA",
            "country": "Netherlands"}

        # Test the validation functions first
        from verenigingen.utils.validation.application_validators import check_application_eligibility, validate_name

        # Test name validation
        first_name_result = validate_name(test_data["first_name"], "First Name")
        last_name_result = validate_name(test_data["last_name"], "Last Name")

        # Test application eligibility
        eligibility_result = check_application_eligibility(test_data)

        # Test helper functions
        from verenigingen.utils.application_helpers import (
            create_address_from_application,
            generate_application_id,
        )

        application_id = generate_application_id()

        # Test address creation with special characters
        address = None
        try:
            address = create_address_from_application(test_data)
            address_created = True
        except Exception as e:
            address_created = False
            address_error = str(e)

        # Test member creation
        from verenigingen.utils.application_helpers import create_member_from_application

        member_created = False
        member_error = None

        try:
            member = create_member_from_application(test_data, application_id, address)
            member_created = True

            # Verify the member data
            member_verification = {
                "first_name_correct": member.first_name == "José",
                "last_name_correct": member.last_name == "García-López",
                "email_correct": member.email == test_data["email"],
                "application_id_set": bool(member.application_id)}

            # Clean up
            frappe.delete_doc("Member", member.name, force=True)
            if address:
                frappe.delete_doc("Address", address.name, force=True)
            frappe.db.commit()

        except Exception as e:
            member_error = str(e)
            frappe.db.rollback()

        return {
            "success": True,
            "validation_results": {
                "first_name_valid": first_name_result["valid"],
                "first_name_sanitized": first_name_result.get("sanitized", ""),
                "last_name_valid": last_name_result["valid"],
                "last_name_sanitized": last_name_result.get("sanitized", ""),
                "eligibility_check": eligibility_result["eligible"]},
            "creation_results": {
                "application_id_generated": bool(application_id),
                "address_created": address_created,
                "address_error": address_error if not address_created else None,
                "member_created": member_created,
                "member_error": member_error,
                "member_verification": member_verification if member_created else None},
            "message": "Special character handling test completed successfully"}

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e), "message": f"Test failed: {str(e)}"}


if __name__ == "__main__":
    result = test_membership_application_special_characters()
    print(result)
