"""
Test enhanced contribution amendment system with dues schedule integration.

This test suite validates:
1. Enhanced auto-approval logic with configurable settings
2. Dues schedule integration for fee changes
3. Migration from legacy system to dues schedule system
4. New field tracking (new_dues_schedule, current_dues_schedule)
5. Integration with member portal fee adjustment

Updated to use the new dues schedule system.
"""

import unittest
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, now_datetime, today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestEnhancedContributionAmendmentSystem(VereningingenTestCase):
    """Test enhanced contribution amendment system with dues schedule integration"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        # Create a real User for the member so tests that exercise the
        # member-initiated (self-service) auto-approval path can set
        # frappe.session.user to a valid user and have approved_by recorded as
        # the member's email.
        member_email = "enhanced.amendment@example.com"
        self.member_user = self.create_test_user(email=member_email, roles=["Verenigingen Member"])

        # Create test member linked to that user
        self.test_member = self.create_test_member(
            first_name="Enhanced", last_name="Amendment", email=member_email, user=self.member_user.name
        )

        # Create a membership type whose minimum (15) matches the auto-created
        # dues template rate (€15). The default factory type uses minimum_amount
        # 25, which is above the template rate and fails dues-schedule creation
        # with "Template dues rate (€15) cannot be less than minimum (€25)".
        self.test_membership_type = self.create_test_membership_type(minimum_amount=15.0)

        # Create test membership and submit so it is ACTIVE (the factory only
        # inserts a Draft; amendments require a submitted Active membership).
        self.test_membership = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name,
            status="Active",
        )
        if self.test_membership.docstatus == 0:
            self.test_membership.submit()

        # Track for cleanup
        self.track_doc("Member", self.test_member.name)
        self.track_doc("Membership", self.test_membership.name)

    @contextmanager
    def _session_user(self, user):
        """Temporarily set frappe.session.user without mock.patch.

        mock.patch("frappe.session.user", ...) fails under Python 3.14
        ("'NoneType' object is not subscriptable") when patching a plain
        attribute; assign/restore directly instead.
        """
        original = frappe.session.user
        frappe.session.user = user
        try:
            yield
        finally:
            frappe.session.user = original

    def _approve_if_pending(self, amendment, notes="Test approval"):
        """Approve an amendment only if it is still Pending Approval.

        The approval service auto-approves any Fee Change that respects the
        minimum fee, so fee increases (and most changes) arrive already Approved;
        calling approve_amendment() on them throws "Only pending amendments can
        be approved". Reload first to pick up the auto-approval status set in
        before_insert/after_insert.
        """
        amendment.reload()
        if amendment.status == "Pending Approval":
            amendment.approve_amendment(notes)

    def _active_schedule_with_amount(self, amount):
        """Return the member's active dues schedule set to `amount`.

        Submitting the membership in setUp auto-creates an active Membership Dues
        Schedule, so creating another one trips the "already has an active dues
        schedule" guard. Reuse the existing one and set its rate.
        """
        existing = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.test_member.name, "is_template": 0},
            "name",
        )
        schedule = frappe.get_doc("Membership Dues Schedule", existing)
        schedule.dues_rate = amount
        schedule.status = "Active"
        schedule.save()
        return schedule

    def test_enhanced_auto_approval_logic(self):
        """Test enhanced auto-approval with configurable settings"""

        # Test 1: Auto-approval for fee increase by member
        with self._session_user(self.test_member.email):
            amendment = frappe.get_doc(
                {
                    "doctype": "Contribution Amendment Request",
                    "membership": self.test_membership.name,
                    "member": self.test_member.name,
                    "amendment_type": "Fee Change",
                    "requested_amount": 25.00,  # Increase from typical €15
                    "reason": "I can afford to contribute more",
                    "effective_date": add_days(today(), 30),
                }
            )

            # Members create amendments through a self-service API in production,
            # not direct doc.insert(); bypass DocPerm here so the auto-approval
            # logic (which records approved_by = session user) can be exercised.
            amendment.insert(ignore_permissions=True)
            self.track_doc("Contribution Amendment Request", amendment.name)

            # Should be auto-approved for fee increase by member
            self.assertEqual(amendment.status, "Approved")
            self.assertEqual(amendment.approved_by, self.test_member.email)
            self.assertIn("Auto-approved", amendment.internal_notes or "")

    def test_manual_approval_required_for_decreases(self):
        """Test that fee decreases require manual approval"""

        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership.name,
                "member": self.test_member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 10.00,  # Decrease from typical €15
                "reason": "Financial hardship",
                "effective_date": add_days(today(), 30),
            }
        )

        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)

        # A decrease below the €15 minimum requires manual approval.
        self.assertEqual(amendment.status, "Pending Approval")
        self.assertIn("below minimum fee", amendment.internal_notes or "")

    def test_dues_schedule_creation_on_application(self):
        """Test that applying amendments creates dues schedules"""

        # Create and approve amendment
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership.name,
                "member": self.test_member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 30.00,
                "reason": "Testing dues schedule creation",
                "effective_date": today(),
            }
        )

        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)

        # Approve the amendment
        self._approve_if_pending(amendment, "Test approval")

        # Apply the amendment
        result = amendment.apply_amendment()

        # Check that application was successful
        self.assertEqual(result["status"], "success")
        self.assertEqual(amendment.status, "Applied")

        # Check that dues schedule was created
        self.assertIsNotNone(amendment.new_dues_schedule)

        # Verify the dues schedule
        dues_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", dues_schedule.name)

        self.assertEqual(dues_schedule.dues_rate, 30.00)
        self.assertEqual(dues_schedule.member, self.test_member.name)
        self.assertEqual(dues_schedule.status, "Active")
        # create_dues_schedule_for_amendment sets contribution_mode "Fixed"
        # (it no longer marks the schedule as a custom amount).
        self.assertEqual(dues_schedule.contribution_mode, "Fixed")

    def test_current_dues_schedule_detection(self):
        """Test that amendments detect current dues schedules"""

        # Create an active dues schedule first
        dues_schedule = self._active_schedule_with_amount(20.00)

        # Create amendment
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership.name,
                "member": self.test_member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 35.00,
                "reason": "Testing current dues schedule detection",
            }
        )

        # Validate should set current details
        amendment.validate()

        # Should detect current dues schedule
        self.assertEqual(amendment.current_dues_schedule, dues_schedule.name)
        self.assertEqual(amendment.current_amount, 20.00)

    def test_existing_schedule_deactivation(self):
        """Test that an amendment updates the member's existing active schedule.

        When a current active dues schedule is detected, the approval service
        updates it in place (rate + amendment note) rather than cancelling it and
        creating a new one; new_dues_schedule then points at that same schedule.
        """

        # Create initial dues schedule
        initial_schedule = self._active_schedule_with_amount(20.00)

        # Create and apply amendment
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership.name,
                "member": self.test_member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 30.00,
                "reason": "Testing schedule deactivation",
                "effective_date": today(),
            }
        )

        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)

        # Approve and apply
        self._approve_if_pending(amendment, "Test approval")
        amendment.apply_amendment()

        # The existing active schedule is updated in place (not cancelled).
        self.assertEqual(amendment.new_dues_schedule, initial_schedule.name)
        initial_schedule.reload()
        self.assertEqual(initial_schedule.status, "Active")
        self.assertEqual(initial_schedule.dues_rate, 30.00)

    def test_legacy_override_field_maintenance(self):
        """Test that legacy override fields are maintained for backward compatibility"""

        # Create and apply amendment
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership.name,
                "member": self.test_member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 40.00,
                "reason": "Testing legacy field maintenance",
                "effective_date": today(),
            }
        )

        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)

        # Approve and apply
        self._approve_if_pending(amendment, "Test approval")
        amendment.apply_amendment()

        # Check that legacy override fields are updated
        self.test_member.reload()
        self.assertEqual(self.test_member.dues_rate, 40.00)
        self.assertIn("Amendment:", self.test_member.fee_override_reason)
        # fee_override_date is a Date field (datetime.date); compare via getdate.
        self.assertEqual(getdate(self.test_member.fee_override_date), getdate(today()))

    def test_zero_amount_handling(self):
        """A zero requested amount is rejected.

        The Fee Change validation (validate_amount_changes) throws "Requested
        amount must be greater than 0" for requested_amount <= 0, so a zero-amount
        amendment cannot be created (there is no free-membership-via-amendment path).
        """

        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership.name,
                "member": self.test_member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 0.00,
                "reason": "Financial hardship - free membership",
                "effective_date": today(),
            }
        )

        with self.assertRaises(frappe.ValidationError):
            amendment.insert()

    def test_dues_schedule_system_integration(self):
        """Test integration with dues schedule system.

        The amendment updates the member's existing active dues schedule in place
        (Membership has no `dues_schedule` field and the amendment has no
        `old_dues_schedule_cancelled` field), so the schedule stays Active with the
        new rate and new_dues_schedule references it.
        """

        # The member already has an active dues schedule (auto-created on submit).
        dues_schedule = self._active_schedule_with_amount(30.00)

        # Create and apply amendment
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership.name,
                "member": self.test_member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 50.00,
                "reason": "Testing dues schedule integration",
                "effective_date": today(),
            }
        )

        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)

        # Approve and apply
        self._approve_if_pending(amendment, "Test approval")
        amendment.apply_amendment()

        # The existing schedule was updated in place to the new amount.
        self.assertEqual(amendment.new_dues_schedule, dues_schedule.name)
        dues_schedule.reload()
        self.assertEqual(dues_schedule.status, "Active")
        self.assertEqual(dues_schedule.dues_rate, 50.00)

    def test_small_adjustment_auto_approval(self):
        """Test auto-approval for small adjustments (< 5% change)"""

        # Set up current amount of €20
        initial_schedule = self._active_schedule_with_amount(20.00)

        # Create amendment with small change (€0.50 = 2.5% of €20)
        with self._session_user(self.test_member.email):
            amendment = frappe.get_doc(
                {
                    "doctype": "Contribution Amendment Request",
                    "membership": self.test_membership.name,
                    "member": self.test_member.name,
                    "amendment_type": "Fee Change",
                    "requested_amount": 20.50,
                    "reason": "Small adjustment",
                    "effective_date": add_days(today(), 30),
                }
            )

            amendment.insert(ignore_permissions=True)
            self.track_doc("Contribution Amendment Request", amendment.name)

            # A change that respects the minimum fee is auto-approved.
            self.assertEqual(amendment.status, "Approved")
            self.assertIn("Auto-approved", amendment.internal_notes or "")

    def test_amendment_metadata_tracking(self):
        """Test that amendment metadata is properly tracked"""

        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership.name,
                "member": self.test_member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 25.00,
                "reason": "Testing metadata tracking",
                "effective_date": today(),
            }
        )

        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)

        # Approve and apply
        self._approve_if_pending(amendment, "Test approval")
        amendment.apply_amendment()

        # Check that dues schedule has proper metadata
        dues_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", dues_schedule.name)

        # The in-place update records "Amended via <amendment> on <date>: EUR..."
        self.assertIn(amendment.name, dues_schedule.notes)
        self.assertIn("amended via", dues_schedule.notes.lower())

        # Check that a comment referencing the amendment was added.
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Membership Dues Schedule", "reference_name": dues_schedule.name},
            fields=["content"],
        )

        self.assertTrue(any(amendment.name in comment.content for comment in comments))

    def test_new_doctype_fields_exist(self):
        """Test that new DocType fields exist and are properly configured"""

        # Test field existence
        doctype = frappe.get_doc("DocType", "Contribution Amendment Request")
        field_names = [field.fieldname for field in doctype.fields]

        self.assertIn("new_dues_schedule", field_names)
        self.assertIn("current_dues_schedule", field_names)

        # Test field properties
        new_dues_field = None
        current_dues_field = None

        for field in doctype.fields:
            if field.fieldname == "new_dues_schedule":
                new_dues_field = field
            elif field.fieldname == "current_dues_schedule":
                current_dues_field = field

        self.assertIsNotNone(new_dues_field)
        self.assertIsNotNone(current_dues_field)

        # Check field types
        self.assertEqual(new_dues_field.fieldtype, "Link")
        self.assertEqual(new_dues_field.options, "Membership Dues Schedule")
        self.assertTrue(new_dues_field.read_only)

        self.assertEqual(current_dues_field.fieldtype, "Link")
        self.assertEqual(current_dues_field.options, "Membership Dues Schedule")
        self.assertTrue(current_dues_field.read_only)


class TestAmendmentApprovalGenuineThrows(VereningingenTestCase):
    """Genuine rejection paths in ContributionAmendmentApprovalService.

    Covers throws that PROPAGATE (not the graceful apply_amendment() error-dict
    surface):
      - approve_amendment() on a non-pending amendment (line 161)
      - reject_amendment() on a non-pending amendment (line 192)
      - apply_billing_change() (unconditional not-implemented guard, line 384)
    """

    def setUp(self):
        super().setUp()
        member_email = f"amend-throws-{frappe.generate_hash(length=6)}@example.com"
        self.member_user = self.create_test_user(email=member_email, roles=["Verenigingen Member"])
        self.member = self.create_test_member(
            first_name="Amend", last_name="Throws", email=member_email, user=self.member_user.name
        )
        # Template rate is €15; match the type minimum so dues-schedule creation
        # on submit does not fail with a min>rate error.
        self.membership_type = self.create_test_membership_type(minimum_amount=15.0)
        self.membership = self.create_test_membership(
            member=self.member.name, membership_type=self.membership_type.name, status="Active"
        )
        if self.membership.docstatus == 0:
            self.membership.submit()

    def _auto_approved_amendment(self):
        """A fee INCREASE respects the minimum, so it is auto-approved on insert
        (status 'Approved', not 'Pending Approval')."""
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.membership.name,
                "member": self.member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 30.00,  # increase from the €15 template rate
                "reason": "Auto-approved increase for throw test",
                "effective_date": add_days(today(), 30),
            }
        )
        # Runs in the default Administrator context (no user switch), which holds
        # create permission on Contribution Amendment Request — no ignore_permissions
        # bypass needed (unlike the member self-service tests above).
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        amendment.reload()
        # Precondition for the throws under test: must NOT be Pending Approval.
        self.assertEqual(amendment.status, "Approved")
        return amendment

    def test_approve_non_pending_amendment_throws(self):
        """Approving an already-Approved amendment is rejected (line 161)."""
        amendment = self._auto_approved_amendment()
        with self.assertRaises(frappe.ValidationError) as ctx:
            amendment.approve_amendment("second approval attempt")
        self.assertIn("Only pending amendments can be approved", str(ctx.exception))

    def test_reject_non_pending_amendment_throws(self):
        """Rejecting an already-Approved amendment is rejected (line 192)."""
        amendment = self._auto_approved_amendment()
        with self.assertRaises(frappe.ValidationError) as ctx:
            amendment.reject_amendment("cannot reject an approved one")
        self.assertIn("Only pending amendments can be rejected", str(ctx.exception))

    def test_apply_billing_change_not_implemented_throws(self):
        """apply_billing_change() is an unconditional not-implemented guard (line 384).

        Exercise the service method directly: via apply_amendment() the throw is
        caught and downgraded to an error dict, so the propagating behaviour is
        only observable on the direct call.
        """
        from verenigingen.services.approval.contribution_amendment_approval_service import (
            get_contribution_amendment_approval_service,
        )

        amendment = self._auto_approved_amendment()
        service = get_contribution_amendment_approval_service(amendment)
        with self.assertRaises(frappe.ValidationError) as ctx:
            service.apply_billing_change(self.membership)
        self.assertIn("Billing interval changes are not yet implemented", str(ctx.exception))


def run_enhanced_amendment_tests():
    """Run the enhanced contribution amendment tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestEnhancedContributionAmendmentSystem)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\\n=== ENHANCED CONTRIBUTION AMENDMENT TEST RESULTS ===")
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


if __name__ == "__main__":
    run_enhanced_amendment_tests()
