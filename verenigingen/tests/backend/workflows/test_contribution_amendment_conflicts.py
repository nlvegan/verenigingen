"""
Test contribution amendment conflict resolution functionality.

This test suite validates:
1. Amendment conflict detection and prevention
2. Automatic cancellation of conflicting amendments on approval
3. Validation preventing multiple pending amendments
4. Proper workflow for amendment lifecycle
"""

import frappe
from frappe.utils import add_days, now_datetime, today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest


class TestContributionAmendmentConflicts(EnhancedTestCase):
    """Test contribution amendment conflict resolution"""

    def setUp(self):
        """Set up test data using Enhanced Test Factory"""
        super().setUp()
        self.test_amendments = []
        
        # Create test member with Enhanced Test Factory
        self.test_member = self.create_test_member(
            first_name="Amendment",
            last_name="TestUser",
            birth_date="1990-01-01"
        )
        self.test_member_name = self.test_member.name
        
        # Create test membership  
        self.test_membership = self.create_test_membership(
            member=self.test_member.name,
            status="Active",
            start_date=today()
        )
        self.test_membership_name = self.test_membership.name
        
        # Create initial dues schedule for testing
        self.test_dues_schedule = self.create_test_dues_schedule(
            member=self.test_member_name,
            membership=self.test_membership_name,
            amount=50.0,
            contribution_mode="Custom",
            uses_custom_amount=1,
            custom_amount_approved=1,
            status="Active"
        )

    def tearDown(self):
        """Clean up test data - Enhanced Test Factory handles most cleanup"""
        try:
            # Clean up test amendments (not handled by Enhanced Test Factory)
            for amendment_name in self.test_amendments:
                if frappe.db.exists("Contribution Amendment Request", amendment_name):
                    frappe.delete_doc("Contribution Amendment Request", amendment_name, force=True)
        except Exception as e:
            print(f"Amendment cleanup error (non-critical): {str(e)}")
        
        # Enhanced Test Factory handles Member, Membership, and Dues Schedule cleanup
        super().tearDown()

    def test_amendment_conflict_detection(self):
        """Test that the system detects conflicting amendments"""
        # Create first amendment
        amendment1 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 75.0,
                "reason": "First amendment",
                "effective_date": add_days(today(), 30),
                "status": "Pending Approval"}
        )
        amendment1.insert()
        self.test_amendments.append(amendment1.name)

        # Try to create second amendment (should be prevented by validation)
        with self.assertRaises(frappe.ValidationError) as context:
            amendment2 = frappe.get_doc(
                {
                    "doctype": "Contribution Amendment Request",
                    "membership": self.test_membership_name,
                    "member": self.test_member_name,
                    "amendment_type": "Fee Change",
                    "requested_amount": 100.0,
                    "reason": "Second amendment",
                    "effective_date": add_days(today(), 30),
                    "status": "Pending Approval"}
            )
            amendment2.insert()

        self.assertIn("pending amendments", str(context.exception))

    def test_automatic_conflict_cancellation_on_approval(self):
        """Test that approving an amendment cancels conflicting ones"""
        # Create first amendment and approve it
        amendment1 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 75.0,
                "reason": "First amendment",
                "effective_date": add_days(today(), 30),
                "status": "Pending Approval"}
        )
        amendment1.insert()
        self.test_amendments.append(amendment1.name)

        # Manually change to approved to simulate having multiple approved (legacy scenario)
        amendment1.status = "Approved"
        amendment1.approved_by = frappe.session.user
        amendment1.approved_date = now_datetime()
        amendment1.flags.ignore_validate_update_after_submit = True
        amendment1.save()

        # Create second amendment and set to pending
        amendment2 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 100.0,
                "reason": "Second amendment",
                "effective_date": add_days(today(), 30),
                "status": "Draft"}
        )
        # Bypass validation for testing
        amendment2.flags.ignore_validate = True
        amendment2.insert()
        self.test_amendments.append(amendment2.name)

        # Manually set to pending approval
        amendment2.status = "Pending Approval"
        amendment2.flags.ignore_validate_update_after_submit = True
        amendment2.save()

        # Approve the second amendment - this should cancel the first
        amendment2.approve_amendment("Test approval")

        # Check that first amendment was cancelled
        amendment1.reload()
        self.assertEqual(amendment1.status, "Cancelled")
        self.assertIn("Cancelled due to approval of newer amendment", amendment1.internal_notes or "")

        # Check that second amendment is approved
        amendment2.reload()
        self.assertEqual(amendment2.status, "Approved")

    def test_cancel_conflicting_amendments_method(self):
        """Test the cancel_conflicting_amendments method directly"""
        # Create multiple amendments with different statuses
        amendment1 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 75.0,
                "reason": "First amendment",
                "effective_date": add_days(today(), 30),
                "status": "Approved"}
        )
        amendment1.insert()
        self.test_amendments.append(amendment1.name)

        amendment2 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 100.0,
                "reason": "Second amendment",
                "effective_date": add_days(today(), 30),
                "status": "Pending Approval"}
        )
        # Bypass validation for testing
        amendment2.flags.ignore_validate = True
        amendment2.insert()
        self.test_amendments.append(amendment2.name)

        # Create third amendment to test the cancellation
        amendment3 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 125.0,
                "reason": "Third amendment",
                "effective_date": add_days(today(), 30),
                "status": "Pending Approval"}
        )
        amendment3.flags.ignore_validate = True
        amendment3.insert()
        self.test_amendments.append(amendment3.name)

        # Test the cancellation method
        amendment3.cancel_conflicting_amendments()

        # Check that other amendments were cancelled
        amendment1.reload()
        amendment2.reload()

        self.assertEqual(amendment1.status, "Cancelled")
        self.assertEqual(amendment2.status, "Cancelled")

        # Check cancellation notes were added
        self.assertIn("Cancelled due to approval of newer amendment", amendment1.internal_notes or "")
        self.assertIn("Cancelled due to approval of newer amendment", amendment2.internal_notes or "")

    def test_no_conflicts_when_only_one_amendment(self):
        """Test that single amendments work normally without conflicts"""
        # Create single amendment
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 75.0,
                "reason": "Single amendment",
                "effective_date": add_days(today(), 30),
                "status": "Pending Approval"}
        )
        amendment.insert()
        self.test_amendments.append(amendment.name)

        # Approve it - should work without issues
        amendment.approve_amendment("Test approval")

        # Check it was approved successfully
        amendment.reload()
        self.assertEqual(amendment.status, "Approved")
        self.assertEqual(amendment.approved_by, frappe.session.user)
        self.assertIsNotNone(amendment.approved_date)

    def test_cancelled_amendments_dont_conflict(self):
        """Test that cancelled amendments don't count as conflicts"""
        # Create and cancel first amendment
        amendment1 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 75.0,
                "reason": "First amendment",
                "effective_date": add_days(today(), 30),
                "status": "Cancelled"}
        )
        amendment1.insert()
        self.test_amendments.append(amendment1.name)

        # Create second amendment - this should be allowed since first is cancelled
        amendment2 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 100.0,
                "reason": "Second amendment",
                "effective_date": add_days(today(), 30),
                "status": "Pending Approval"}
        )
        amendment2.insert()
        self.test_amendments.append(amendment2.name)

        # Should succeed without validation errors
        self.assertEqual(amendment2.status, "Pending Approval")

    def test_applied_amendments_dont_conflict(self):
        """Test that applied amendments don't count as conflicts"""
        # Create and apply first amendment
        amendment1 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 75.0,
                "reason": "First amendment",
                "effective_date": add_days(today(), 30),
                "status": "Applied"}
        )
        amendment1.insert()
        self.test_amendments.append(amendment1.name)

        # Create second amendment - this should be allowed since first is applied
        amendment2 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 100.0,
                "reason": "Second amendment",
                "effective_date": add_days(today(), 30),
                "status": "Pending Approval"}
        )
        amendment2.insert()
        self.test_amendments.append(amendment2.name)

        # Should succeed without validation errors
        self.assertEqual(amendment2.status, "Pending Approval")


def run_amendment_tests():
    """Run the contribution amendment conflict tests"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        # Run the test suite
        suite = unittest.TestLoader().loadTestsFromTestCase(TestContributionAmendmentConflicts)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        print("\\n=== CONTRIBUTION AMENDMENT CONFLICT TEST RESULTS ===")
        print(f"Tests run: {result.testsRun}")
        print(f"Failures: {len(result.failures)}")
        print(f"Errors: {len(result.errors)}")

        if result.failures:
            print("\\nFAILURES:")
            for test, traceback in result.failures:
                print(f"- {test}: {traceback}")

        if result.errors:
            print("\\nERRORS:")
            for test, traceback in result.errors:
                print(f"- {test}: {traceback}")

        return result.wasSuccessful()

    finally:
        frappe.destroy()


if __name__ == "__main__":
    run_amendment_tests()
