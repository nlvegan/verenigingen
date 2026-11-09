"""
Test script to verify the complete membership application submission process
"""

import frappe
from frappe.utils import random_string
from verenigingen.tests.integration.test_application_record_approval import ApprovalCase


class TestApplicationSubmission(ApprovalCase):
    """Test complete application submission process"""

    def test_application_submission(self):
        """Test complete application submission: submit -> confirm -> approve creates the Member"""
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
            "membership_amount": 65.0,  # Custom amount
            "uses_custom_amount": True,
            "custom_amount_reason": "Supporter contribution",
            "payment_method": "SEPA Direct Debit",
            "iban": "NL91ABNA0417164300",
            "bic": "ABNANL2A",
            "bank_account_name": "Test Application User",
            "terms": True,
            "newsletter": True}

        # The real endpoint stages the application; following the emailed link confirms it. No Member
        # exists until approval (#1765), so the Member's fields are checked after approve_application.
        name = self._stage_and_confirm(**form_data)
        self.assertEqual(frappe.db.count("Member", {"email": form_data["email"]}), 0)
        result = self._approve_as(name)
        self.assertTrue(result.get("success"), f"Application approval failed: {result}")

        member_id = result.get("member")
        self.assertIsNotNone(member_id, f"Approval should return the member. Got result: {result}")
        application_id = frappe.db.get_value("Membership Application Submission", name, "application_id")
        self.assertIsNotNone(application_id, "Application should have an application_id")

        member = frappe.get_doc("Member", member_id)
        self.track_doc("Member", member.name)  # Track for cleanup

        # Verify member fields
        self.assertEqual(member.first_name, form_data["first_name"])
        self.assertEqual(member.last_name, form_data["last_name"])
        # The staged application stores the address lower-cased (the confirm link proves that spelling).
        self.assertEqual(member.email, form_data["email"].lower())
        self.assertEqual(member.application_id, application_id)

        # Most importantly - check that NO _pending_fee_change was created
        self.assertFalse(hasattr(member, "_pending_fee_change"),
                        "New application should not create _pending_fee_change!")

        self.assertEqual((member.application_status, member.status), ("Approved", "Active"))

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

        # Verify initial state. application_custom_fee is a Currency field, so
        # an unset value reads back as 0.0 (not None).
        initial_application_custom_fee = existing_member.application_custom_fee
        self.assertIn(
            initial_application_custom_fee,
            (None, 0, 0.0),
            "Initial application custom fee should be unset",
        )

        # Reload to get latest version before making changes (avoid timestamp mismatch from hooks)
        existing_member.reload()

        # Update their application custom fee (doesn't require reason field)
        existing_member.application_custom_fee = 150.0
        existing_member.save()

        # Verify the fee was updated correctly
        existing_member.reload()
        self.assertEqual(existing_member.application_custom_fee, 150.0,
                        "Application custom fee should be updated to 150.0")


# Tests are now part of TestApplicationSubmission class and will be run via the test framework
