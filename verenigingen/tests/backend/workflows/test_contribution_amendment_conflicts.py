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
from verenigingen.tests.support.sepa_test_company import ensure_sepa_payment_terms_template
import unittest


class TestContributionAmendmentConflicts(EnhancedTestCase):
    """Test contribution amendment conflict resolution"""

    def setUp(self):
        """Set up test data using Enhanced Test Factory"""
        super().setUp()
        self.test_amendments = []
        # Dues schedules set payment_terms_template = "SEPA Direct Debit".
        ensure_sepa_payment_terms_template()

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
        
        # The membership auto-creates an Active dues schedule (one-active-per-
        # member rule), so reuse it instead of creating a second. Configure it
        # for a custom approved amount used by the conflict scenarios.
        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.test_member_name, "is_template": 0, "status": "Active"},
            "name",
        )
        self.test_dues_schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        # "Custom" is a removed pre-v2_0 contribution mode; the field offers
        # Fixed/Income-Based/Flexible. The custom amount is carried by
        # uses_custom_amount below, and no production branch reads "Custom".
        self.test_dues_schedule.contribution_mode = "Fixed"
        self.test_dues_schedule.uses_custom_amount = 1
        self.test_dues_schedule.custom_amount_approved = 1
        self.test_dues_schedule.dues_rate = 100.0  # respect membership type minimum
        self.test_dues_schedule.save()

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

    def _insert_amendment(self, requested_amount, reason):
        """Insert a Fee Change amendment for the test member and track it."""
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": requested_amount,
                "reason": reason,
                "effective_date": add_days(today(), 30),
            }
        )
        amendment.insert()
        self.test_amendments.append(amendment.name)
        return amendment

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
        # Create amendments one at a time, pinning each to a known status right
        # after insert so the conflict-prevention rule (which blocks creating a
        # new request while another "Pending Approval" exists) doesn't fire
        # between inserts. The scenario under test is the cancellation method,
        # not the creation-time conflict guard.
        amendment1 = self._insert_amendment(75.0, "First amendment")
        frappe.db.set_value(
            "Contribution Amendment Request", amendment1.name, "status", "Approved"
        )

        amendment2 = self._insert_amendment(75.0, "Second amendment")
        frappe.db.set_value(
            "Contribution Amendment Request", amendment2.name, "status", "Approved"
        )

        # Third amendment (the "winner") that cancels the conflicting ones.
        amendment3 = self._insert_amendment(75.0, "Third amendment")
        amendment3.reload()

        # Restore the two conflicting amendments to states the cancellation
        # method acts on, then run it.
        frappe.db.set_value(
            "Contribution Amendment Request", amendment1.name, "status", "Pending Approval"
        )
        frappe.db.set_value(
            "Contribution Amendment Request", amendment2.name, "status", "Pending Approval"
        )

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
        # Create first amendment, then move it to "Cancelled" (the controller
        # recomputes status on insert, so set the terminal status afterwards).
        amendment1 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 75.0,
                "reason": "First amendment",
                "effective_date": add_days(today(), 30),
            }
        )
        amendment1.insert()
        self.test_amendments.append(amendment1.name)
        frappe.db.set_value("Contribution Amendment Request", amendment1.name, "status", "Cancelled")

        # Create second amendment - allowed since the first is cancelled. Use an
        # amount that differs from the current rate (100) and is below the minimum
        # so it stays "Pending Approval".
        amendment2 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 75.0,
                "reason": "Second amendment",
                "effective_date": add_days(today(), 30),
            }
        )
        amendment2.insert()
        self.test_amendments.append(amendment2.name)

        # Should succeed without validation errors
        self.assertEqual(amendment2.status, "Pending Approval")

    def test_applied_amendments_dont_conflict(self):
        """Test that applied amendments don't count as conflicts"""
        # Create first amendment, then move it to "Applied". The controller
        # recomputes status on insert (auto-approval), so set the terminal status
        # directly afterwards rather than via the create dict.
        amendment1 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 75.0,
                "reason": "First amendment",
                "effective_date": add_days(today(), 30),
            }
        )
        amendment1.insert()
        self.test_amendments.append(amendment1.name)
        frappe.db.set_value("Contribution Amendment Request", amendment1.name, "status", "Applied")

        # Create second amendment - allowed since the first is Applied (only
        # "Pending Approval" amendments block new requests).
        amendment2 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership_name,
                "member": self.test_member_name,
                "amendment_type": "Fee Change",
                "requested_amount": 75.0,  # below minimum -> stays Pending Approval
                "reason": "Second amendment",
                "effective_date": add_days(today(), 30),
            }
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
