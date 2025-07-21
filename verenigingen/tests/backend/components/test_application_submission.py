"""
Test script to verify the complete membership application submission process
"""

import frappe
from frappe.utils import random_string
from verenigingen.tests.utils.base import VereningingenTestCase


class TestApplicationSubmission(VereningingenTestCase):
    """Test complete application submission process"""

    def test_application_submission(self):
        """Test complete application submission"""
        # Get an existing membership type or create one
        membership_types = frappe.get_all("Membership Type", limit=1)
        if not membership_types:
            # Create a test membership type
            membership_type = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type": "Test Standard",
                "amount": 50.0
            })
            membership_type.insert()
            self.track_doc("Membership Type", membership_type.name)
            selected_membership_type = membership_type.name
        else:
            selected_membership_type = membership_types[0]["name"]
        
        # Create test data that mimics form submission
        form_data = {
            "first_name": "TestApp",
            "last_name": "User" + random_string(4),
            "email": f"testapp.user.{random_string(6)}@example.com",
            "contact_number": "+31612345678",
            "birth_date": "1990-05-15",
            "address_line1": "Test Application Street 123",
            "city": "Amsterdam",
            "postal_code": "1012AB",
            "country": "Netherlands",
            "selected_membership_type": selected_membership_type,
            "membership_amount": 65.0,  # Custom amount
            "uses_custom_amount": True,
            "custom_amount_reason": "Supporter contribution",
            "payment_method": "SEPA Direct Debit",
            "iban": "NL91ABNA0417164300",
            "bic": "ABNANL2A",
            "bank_account_name": "Test Application User",
            "terms": True,
            "newsletter": True}

        # Call the API method that handles form submissions
        result = frappe.call(
            "verenigingen.api.membership_application.submit_application", **form_data
        )

        # Verify result
        self.assertIsNotNone(result, "Application submission should return a result")
        self.assertTrue(result.get("success"), f"Application submission failed: {result}")

        # Verify the created member
        member_id = result.get("member_record")
        self.assertIsNotNone(member_id, f"Application should return a member_record. Got result: {result}")
        
        # Also verify application ID
        application_id = result.get("application_id")
        self.assertIsNotNone(application_id, "Application should return an application_id")
        
        member = frappe.get_doc("Member", member_id)
        self.track_doc("Member", member.name)  # Track for cleanup
        
        # Verify member fields
        self.assertEqual(member.first_name, form_data["first_name"])
        self.assertEqual(member.last_name, form_data["last_name"])
        self.assertEqual(member.email, form_data["email"])
        
        # Most importantly - check that NO _pending_fee_change was created
        self.assertFalse(hasattr(member, "_pending_fee_change"),
                        "New application should not create _pending_fee_change!")
        
        # Verify status (check what the actual status is)
        # Based on the result, status should be "pending_review"
        self.assertEqual(result.get("status"), "pending_review")
        
        # Verify application was submitted successfully
        self.assertEqual(result.get("success"), True)


    def test_backend_fee_adjustment(self):
        """Test backend fee adjustment for existing member"""
        # Create an existing member using factory method
        existing_member = self.create_test_member(
            first_name="Backend",
            last_name="TestMember" + random_string(4),
            email=f"backend.test.{random_string(6)}@example.com",
            birth_date="1985-03-10",
            status="Active",
            application_status="Active"
        )

        # Verify initial state
        initial_application_custom_fee = existing_member.application_custom_fee
        self.assertIsNone(initial_application_custom_fee, "Initial application custom fee should be None")

        # Update their application custom fee (doesn't require reason field)
        existing_member.application_custom_fee = 150.0
        existing_member.save()

        # Verify the fee was updated correctly
        existing_member.reload()
        self.assertEqual(existing_member.application_custom_fee, 150.0,
                        "Application custom fee should be updated to 150.0")


# Tests are now part of TestApplicationSubmission class and will be run via the test framework
