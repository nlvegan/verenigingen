"""
Test Member Lifecycle with IBAN History
Tests IBAN validation and history tracking throughout member lifecycle
"""

import unittest

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.test_data_factory import TestDataFactory


class TestMemberLifecycleIBAN(unittest.TestCase):
    """Test Member lifecycle with IBAN validation and history"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        cls.factory = TestDataFactory()

    def setUp(self):
        """Set up test case"""
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after test"""
        frappe.db.rollback()

    def create_test_member(self, **kwargs):
        """Helper to create test members"""
        member_data = {
            "doctype": "Member",
            "first_name": kwargs.get("first_name", "Test"),
            "last_name": kwargs.get("last_name", "Member"),
            "email": kwargs.get("email", f"test{frappe.utils.random_string(5)}@example.com")}
        # Add optional fields
        for field in ["iban", "bic", "bank_account_name", "payment_method"]:
            if field in kwargs:
                member_data[field] = kwargs[field]

        member = frappe.get_doc(member_data)
        member.insert()
        return member

    def create_test_membership(self, **kwargs):
        """Helper to create test memberships"""
        membership_data = {
            "doctype": "Membership",
            "member": kwargs.get("member"),
            "membership_type": kwargs.get("membership_type", "Regular"),
            "start_date": kwargs.get("start_date", today())}
        membership = frappe.get_doc(membership_data)
        membership.insert()
        return membership

    def test_member_application_with_iban(self):
        """Test member application with IBAN validation"""
        # Create application with IBAN
        application_data = {
            "first_name": "Test",
            "last_name": "Application",
            "email": "test.application.iban@example.com",
            "payment_method": "SEPA Direct Debit",
            "iban": "NL13TEST0123456789",
            "bank_account_name": "Test Application"}

        # Submit application
        application = frappe.get_doc({"doctype": "Membership Application", **application_data})
        application.insert()

        # Validate IBAN is formatted
        self.assertEqual(application.iban, "NL91 ABNA 0417 1643 00")

        # Approve application
        application.status = "Approved"
        application.save()

        # Get created member
        member = frappe.get_doc("Member", {"email": application_data["email"]})

        # Check IBAN was transferred
        self.assertEqual(member.iban, "NL91 ABNA 0417 1643 00")
        self.assertEqual(member.bic, "ABNANL2A")
        self.assertEqual(member.bank_account_name, "Test Application")

        # Check initial IBAN history (created during approval)
        history_records = frappe.get_all("Member IBAN History", filters={"parent": member.name}, fields=["*"])
        self.assertEqual(len(history_records), 1)
        self.assertEqual(history_records[0].change_reason, "Other")

    def test_member_iban_change_lifecycle(self):
        """Test IBAN changes during member lifecycle"""
        # Create member
        member = self.create_test_member(
            first_name="IBAN",
            last_name="Change",
            email="iban.change@example.com",
            iban="NL82MOCK0123456789",
            bank_account_name="Initial Account",
            payment_method="SEPA Direct Debit",
        )

        # Create membership
        membership = self.create_test_membership(
            member=member.name, membership_type="Regular", start_date=today()
        )

        # Simulate bank change
        member.iban = "NL69INGB0123456789"
        member.bank_account_name = "New Bank Account"
        member.save()

        # Check history
        member.reload()
        self.assertEqual(len(member.iban_history), 2)

        # Verify old IBAN is inactive
        old_history = next((h for h in member.iban_history if "RABO" in h.iban), None)
        self.assertIsNotNone(old_history)
        self.assertFalse(old_history.is_active)

        # Verify new IBAN is active
        new_history = next((h for h in member.iban_history if "INGB" in h.iban), None)
        self.assertIsNotNone(new_history)
        self.assertTrue(new_history.is_active)
        self.assertEqual(new_history.bic, "INGBNL2A")

    def test_payment_processing_with_iban_validation(self):
        """Test payment processing with IBAN validation"""
        # Create member with valid IBAN
        member = self.create_test_member(
            first_name="Payment",
            last_name="Test",
            email="payment.test@example.com",
            iban="NL63TRIO0212345678",
            bank_account_name="Payment Test",
            payment_method="SEPA Direct Debit",
        )

        # Create membership
        membership = self.create_test_membership(
            member=member.name, membership_type="Regular", start_date=today()
        )

        # Create SEPA mandate
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": member.name,
                "member_name": member.full_name,
                "mandate_id": f"TEST-{member.name}-001",
                "iban": member.iban,
                "bic": member.bic,
                "account_holder_name": member.bank_account_name,
                "mandate_type": "RCUR",
                "sign_date": today(),
                "used_for_memberships": 1,
                "status": "Active",
                "is_active": 1}
        )
        mandate.insert()
        mandate.submit()

        # Link mandate to member
        member.append(
            "sepa_mandates",
            {
                "sepa_mandate": mandate.name,
                "mandate_reference": mandate.mandate_id,
                "is_current": 1,
                "status": "Active",
                "valid_from": today()},
        )
        member.save()

        # Verify payment can be processed
        self.assertTrue(member.has_active_sepa_mandate())
        self.assertEqual(member.get_default_sepa_mandate().name, mandate.name)

    def test_invalid_iban_blocks_sepa_payment(self):
        """Test that invalid IBAN blocks SEPA payment method"""
        member = self.create_test_member(
            first_name="Invalid", last_name="IBAN", email="invalid.iban@example.com"
        )

        # Try to set SEPA with invalid IBAN
        member.payment_method = "SEPA Direct Debit"
        member.iban = "NL00INVALID0000000"
        member.bank_account_name = "Invalid Test"

        with self.assertRaises(frappe.ValidationError) as context:
            member.save()

        self.assertIn("Invalid", str(context.exception))

    def test_iban_history_after_termination(self):
        """Test IBAN history is preserved after member termination"""
        # Create member with IBAN history
        member = self.create_test_member(
            first_name="Terminated",
            last_name="Member",
            email="terminated.member@example.com",
            iban="NL82MOCK0123456789",
            bank_account_name="Initial Account",
            payment_method="SEPA Direct Debit",
        )

        # Change IBAN once
        member.iban = "NL69INGB0123456789"
        member.save()

        # Create and terminate membership
        membership = self.create_test_membership(
            member=member.name, membership_type="Regular", start_date=add_days(today(), -365)
        )

        # Create termination request
        termination = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member.name,
                "membership": membership.name,
                "reason": "Member Request",
                "termination_date": today(),
                "status": "Pending"}
        )
        termination.insert()

        # Execute termination
        termination.status = "Executed"
        termination.save()

        # Verify IBAN history is preserved
        member.reload()
        self.assertEqual(len(member.iban_history), 2)

        # All history should be preserved
        for history in member.iban_history:
            self.assertIsNotNone(history.iban)
            self.assertIsNotNone(history.from_date)


def run_tests():
    """Run all Member lifecycle IBAN tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMemberLifecycleIBAN)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    unittest.main()
