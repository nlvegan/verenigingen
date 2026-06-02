"""
Test suite for ERPNext-inspired validation enhancements
Tests custom exceptions, status transitions, and boundary validations
"""

import frappe
from frappe.utils import today
from verenigingen.tests.utils.base import VereningingenTestCase


class TestERPNextInspiredValidations(VereningingenTestCase):
    """Test ERPNext-inspired validation enhancements"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

    def _cancel_auto_schedules(self, member_name):
        """Cancel any dues schedule auto-created on membership submit so a test's
        explicitly-created schedule is the only active one for the member."""
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "status": "Active", "is_template": 0},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")

    def test_status_transition_validation_valid_transitions(self):
        """Test that valid status transitions are allowed"""
        # Create test membership type first
        membership_type = self.create_test_membership_type(
            membership_type_name=f"Status Test Type {frappe.generate_hash(length=6)}", dues_rate=25.0
        )

        # Create a template schedule to avoid member requirements
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"Test-Status-{frappe.generate_hash(length=6)}"
        schedule.membership_type = membership_type.name
        schedule.dues_rate = 25.0
        schedule.status = "Active"
        schedule.is_template = 1
        schedule.billing_frequency = "Monthly"
        schedule.auto_generate = 1
        schedule.next_invoice_date = today()
        schedule.save()
        self.track_doc("Membership Dues Schedule", schedule.name)

        # Test valid transition: Active -> Paused
        schedule.reload()
        schedule.status = "Paused"
        try:
            schedule.save()  # Should succeed
            self.assertEqual(schedule.status, "Paused")
        except Exception as e:
            self.fail(f"Valid transition Active->Paused should not raise exception: {e}")

        # Test valid transition: Paused -> Active
        schedule.reload()
        schedule.status = "Active"
        try:
            schedule.save()  # Should succeed
            self.assertEqual(schedule.status, "Active")
        except Exception as e:
            self.fail(f"Valid transition Paused->Active should not raise exception: {e}")

    def test_status_transition_validation_invalid_transitions(self):
        """Test that invalid status transitions are blocked"""
        # Create test membership type first
        membership_type = self.create_test_membership_type(
            membership_type_name=f"Invalid Test Type {frappe.generate_hash(length=6)}", dues_rate=25.0
        )

        # Create and save a cancelled schedule
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"Test-Invalid-{frappe.generate_hash(length=6)}"
        schedule.membership_type = membership_type.name
        schedule.dues_rate = 25.0
        schedule.status = "Cancelled"
        schedule.is_template = 1
        schedule.billing_frequency = "Monthly"
        schedule.auto_generate = 1
        schedule.next_invoice_date = today()
        schedule.save()
        self.track_doc("Membership Dues Schedule", schedule.name)

        # Test invalid transition: Cancelled -> Active (should fail)
        schedule.reload()
        schedule.status = "Active"

        from verenigingen.utils.exceptions import InvalidStatusTransitionError

        with self.assertRaises(InvalidStatusTransitionError) as context:
            schedule.save()

        self.assertIn("Cannot transition", str(context.exception))
        self.assertIn("Cancelled", str(context.exception))
        self.assertIn("Active", str(context.exception))

    def test_billing_frequency_consistency_validation(self):
        """Test billing frequency consistency validation method directly"""
        # Since the business rules prevent multiple schedules per member,
        # we'll test the validation method directly using mock data

        # Create test member
        test_id = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="Frequency", last_name=f"Tester{test_id}", email=f"frequency.tester.{test_id}@test.com"
        )

        membership_type = self.create_test_membership_type(
            membership_type_name=f"Frequency Test Type {test_id}", dues_rate=30.0
        )

        # Need an ACTIVE membership before creating a real (non-template) schedule.
        membership = self.create_test_membership(member=member.name, membership_type=membership_type.name)
        membership.submit()
        # Reuse the auto-created Active schedule as the existing Monthly schedule.
        existing_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        existing_schedule = frappe.get_doc("Membership Dues Schedule", existing_name)
        existing_schedule.billing_frequency = "Monthly"
        existing_schedule.dues_rate = 30.0
        existing_schedule.save()

        # A new in-memory schedule with a DIFFERENT frequency for the same member
        # must be flagged as a billing-frequency conflict.
        new_schedule = frappe.new_doc("Membership Dues Schedule")
        new_schedule.member = member.name
        new_schedule.billing_frequency = "Annual"  # Different from existing Monthly

        from verenigingen.utils.exceptions import BillingFrequencyConflictError

        with self.assertRaises(BillingFrequencyConflictError) as context:
            new_schedule.validate_billing_frequency_consistency()

        self.assertIn("different billing frequencies", str(context.exception))
        self.assertIn("Monthly", str(context.exception))
        self.assertIn("Annual", str(context.exception))

    def test_rate_boundaries_validation_positive_rate(self):
        """Test that positive rates pass boundary validation"""
        # Create test membership type first
        membership_type = self.create_test_membership_type(
            membership_type_name=f"Positive Test Type {frappe.generate_hash(length=6)}", dues_rate=25.0
        )

        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"Test-Positive-{frappe.generate_hash(length=6)}"
        schedule.membership_type = membership_type.name
        schedule.dues_rate = 25.0  # Positive rate
        schedule.status = "Active"
        schedule.is_template = 1  # Template to avoid member requirements
        schedule.billing_frequency = "Monthly"
        schedule.auto_generate = 1
        schedule.next_invoice_date = today()

        try:
            schedule.save()  # Should succeed
        except Exception as e:
            self.fail(f"Positive rate should not raise exception: {e}")

    def test_rate_boundaries_validation_zero_rate(self):
        """A zero rate below the membership type minimum is rejected.

        NOTE: zero is no longer rejected by a "must be positive" sign check
        (0 is allowed for free memberships); it is only rejected when it falls
        below the membership type's minimum_amount.
        """
        # Create test member and membership
        test_id = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="Zero", last_name=f"Tester{test_id}", email=f"zero.tester.{test_id}@test.com"
        )

        membership_type = self.create_test_membership_type(
            membership_type_name=f"Zero Test Type {test_id}",
            minimum_amount=25.0,
        )

        membership = self.create_test_membership(
            member=member.name, membership_type=membership_type.name, docstatus=0
        )
        membership.submit()
        # Cancel the auto-created schedule so the zero rate (not the duplicate
        # check) is what fails below.
        self._cancel_auto_schedules(member.name)

        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"Test-Zero-{test_id}"
        schedule.member = member.name
        schedule.membership_type = membership_type.name
        schedule.currency = "EUR"
        schedule.dues_rate = 0.0  # Below the €25 minimum - should fail
        schedule.status = "Active"
        schedule.is_template = 0  # Use non-template to trigger validation
        schedule.billing_frequency = "Monthly"
        schedule.auto_generate = 1
        schedule.next_invoice_date = today()

        with self.assertRaises(frappe.ValidationError) as context:
            schedule.save()

        self.assertIn("minimum", str(context.exception).lower())

    def test_rate_boundaries_validation_negative_rate(self):
        """Test that negative rates are rejected by boundary validation"""
        # Create test member and membership
        test_id = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="Negative", last_name=f"Tester{test_id}", email=f"negative.tester.{test_id}@test.com"
        )

        membership_type = self.create_test_membership_type(
            membership_type_name=f"Negative Test Type {test_id}", dues_rate=25.0
        )

        membership = self.create_test_membership(
            member=member.name, membership_type=membership_type.name, docstatus=0
        )
        membership.submit()
        # Submitting auto-creates an Active schedule; cancel it so the negative
        # rate (not the duplicate check) is what fails below.
        self._cancel_auto_schedules(member.name)

        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"Test-Negative-{test_id}"
        schedule.member = member.name
        schedule.membership_type = membership_type.name
        schedule.currency = "EUR"
        schedule.dues_rate = -10.0  # Negative rate - should fail
        schedule.status = "Active"
        schedule.is_template = 0  # Use non-template to trigger validation
        schedule.billing_frequency = "Monthly"
        schedule.auto_generate = 1
        schedule.next_invoice_date = today()

        from verenigingen.utils.exceptions import InvalidDuesRateError

        with self.assertRaises(InvalidDuesRateError) as context:
            schedule.save()

        self.assertIn("cannot be negative", str(context.exception))
        self.assertIn("-10.00", str(context.exception))


class TestCustomExceptionClasses(VereningingenTestCase):
    """Test custom exception classes work correctly"""

    def test_invalid_dues_rate_error(self):
        """Test InvalidDuesRateError exception"""
        from verenigingen.utils.exceptions import InvalidDuesRateError

        with self.assertRaises(InvalidDuesRateError):
            raise InvalidDuesRateError("Test dues rate error")

    def test_membership_type_mismatch_error(self):
        """Test MembershipTypeMismatchError exception"""
        from verenigingen.utils.exceptions import MembershipTypeMismatchError

        with self.assertRaises(MembershipTypeMismatchError):
            raise MembershipTypeMismatchError("Test membership type mismatch error")

    def test_invalid_status_transition_error(self):
        """Test InvalidStatusTransitionError exception"""
        from verenigingen.utils.exceptions import InvalidStatusTransitionError

        with self.assertRaises(InvalidStatusTransitionError):
            raise InvalidStatusTransitionError("Test status transition error")

    def test_billing_frequency_conflict_error(self):
        """Test BillingFrequencyConflictError exception"""
        from verenigingen.utils.exceptions import BillingFrequencyConflictError

        with self.assertRaises(BillingFrequencyConflictError):
            raise BillingFrequencyConflictError("Test billing frequency conflict error")


class TestValidationIntegration(VereningingenTestCase):
    """Test integration of all validation enhancements"""

    def _cancel_auto_schedules(self, member_name):
        """Cancel any dues schedule auto-created on membership submit so a test's
        explicitly-created schedule is the only active one for the member."""
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "status": "Active", "is_template": 0},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")

    def test_multiple_validations_together(self):
        """Test that multiple validations work together correctly"""
        # Create test membership type first
        membership_type = self.create_test_membership_type(
            membership_type_name=f"Integration Test Type {frappe.generate_hash(length=6)}", dues_rate=25.0
        )

        # Create a schedule that passes all validations
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"Test-Integration-{frappe.generate_hash(length=6)}"
        schedule.membership_type = membership_type.name
        schedule.dues_rate = 25.0  # Valid rate
        schedule.status = "Active"  # Valid initial status
        schedule.billing_frequency = "Monthly"  # Valid frequency
        schedule.is_template = 1  # Template to avoid member requirements
        schedule.auto_generate = 1
        schedule.next_invoice_date = today()

        try:
            schedule.save()  # Should pass all validations
            self.track_doc("Membership Dues Schedule", schedule.name)
        except Exception as e:
            self.fail(f"Valid schedule should pass all validations: {e}")

        # Test that it can be modified with valid changes
        schedule.reload()
        schedule.status = "Paused"  # Valid transition
        schedule.dues_rate = 30.0  # Still valid rate

        try:
            schedule.save()  # Should still pass all validations
        except Exception as e:
            self.fail(f"Valid modifications should pass all validations: {e}")

    def test_validation_error_messages_are_helpful(self):
        """Test that validation error messages provide useful information"""
        # Create test member and membership
        test_id = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="Error", last_name=f"Tester{test_id}", email=f"error.tester.{test_id}@test.com"
        )

        membership_type = self.create_test_membership_type(
            membership_type_name=f"Error Test Type {test_id}", dues_rate=25.0
        )

        membership = self.create_test_membership(
            member=member.name, membership_type=membership_type.name, docstatus=0
        )
        membership.submit()
        # Cancel the auto-created schedule so the negative rate (not the
        # duplicate check) is what fails below.
        self._cancel_auto_schedules(member.name)

        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"Test-ErrorMsg-{test_id}"
        schedule.member = member.name
        schedule.membership_type = membership_type.name
        schedule.currency = "EUR"
        schedule.dues_rate = -5.0  # Invalid rate to trigger error
        schedule.status = "Active"
        schedule.is_template = 0  # Use non-template to trigger validation
        schedule.billing_frequency = "Monthly"
        schedule.auto_generate = 1
        schedule.next_invoice_date = today()

        from verenigingen.utils.exceptions import InvalidDuesRateError

        with self.assertRaises(InvalidDuesRateError) as context:
            schedule.save()

        error_message = str(context.exception)

        # Check that error message contains useful information
        self.assertIn("cannot be negative", error_message)
        self.assertIn("-5.00", error_message)  # Shows actual problematic value
        self.assertIn("€", error_message)  # Shows currency formatting
