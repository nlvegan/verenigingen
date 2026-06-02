# File: verenigingen/tests/test_membership_commitment_period.py
"""
Unit tests for membership commitment period tracking and validation.

Tests the new commitment_end_date field and validation logic that prevents
members from quitting before their welcome gift commitment period ends.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, today, getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMembershipCommitmentPeriod(EnhancedTestCase):
    """Test commitment period tracking on Membership records"""

    def tearDown(self):
        """Clean up test data"""
        frappe.db.rollback()
        super().tearDown()

    def test_commitment_end_date_set_on_new_membership(self):
        """Test that commitment_end_date is automatically set to 1 year from start"""
        # Create a test member
        member = self.create_test_member(first_name="Test", last_name="Commitment", birth_date="1990-01-01")

        # Create membership type
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Test Annual",
                "billing_period": "Annual",
                "minimum_amount": 50.0,
                "role_profile": "Verenigingen Staff",
                "is_active": 1,
            }
        ).insert()

        # Create membership
        start_date = today()
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "start_date": start_date,
            }
        )
        membership.insert()
        membership.reload()

        # Verify commitment_end_date is set to 1 year from start
        expected_commitment_end = add_to_date(start_date, months=12)
        self.assertEqual(getdate(membership.commitment_end_date), getdate(expected_commitment_end))

    def test_commitment_end_date_historic_import(self):
        """Test that historic CSV imports calculate commitment from original start date"""
        # Create a test member
        member = self.create_test_member(first_name="Historic", last_name="Import", birth_date="1990-01-01")

        # Create membership type with enforce_minimum_period=True (default)
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Test Historic",
                "billing_period": "Annual",
                "minimum_amount": 50.0,
                "role_profile": "Verenigingen Staff",
                "is_active": 1,
                "enforce_minimum_period": 1,
            }
        ).insert()

        # Create membership with historic start date and CSV import flag
        historic_start = add_to_date(today(), months=-6)
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "start_date": historic_start,
            }
        )
        membership._is_csv_import = True
        membership.insert()

        # Verify commitment_end_date is calculated from original start_date
        # (not from import date - that was the bug we fixed)
        expected_commitment_end = add_to_date(historic_start, months=12)
        self.assertEqual(getdate(membership.commitment_end_date), getdate(expected_commitment_end))

    def test_commitment_end_date_not_set_when_enforce_minimum_disabled(self):
        """Test that commitment_end_date is NOT set when enforce_minimum_period is disabled"""
        # Create a test member
        member = self.create_test_member(first_name="No", last_name="Minimum", birth_date="1990-01-01")

        # Create membership type with enforce_minimum_period DISABLED
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Test No Minimum",
                "billing_period": "Annual",
                "minimum_amount": 50.0,
                "role_profile": "Verenigingen Staff",
                "is_active": 1,
                "enforce_minimum_period": 0,  # Disabled!
            }
        ).insert()

        # Create membership (with or without CSV import flag - shouldn't matter)
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "start_date": today(),
            }
        )
        membership._is_csv_import = True  # Even with CSV import flag
        membership.insert()

        # Verify commitment_end_date is NOT set
        self.assertIsNone(membership.commitment_end_date)

    def test_commitment_end_date_not_overwritten(self):
        """Test that commitment_end_date is not overwritten if already set"""
        # Create a test member
        member = self.create_test_member(first_name="Keep", last_name="Existing", birth_date="1990-01-01")

        # Create membership type
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Test Keep",
                "billing_period": "Annual",
                "minimum_amount": 50.0,
                "role_profile": "Verenigingen Staff",
                "is_active": 1,
            }
        ).insert()

        # Create membership with pre-set commitment_end_date
        custom_commitment_date = add_to_date(today(), months=18)
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "start_date": today(),
                "commitment_end_date": custom_commitment_date,
            }
        )
        membership.insert()

        # Verify the custom commitment date was preserved
        self.assertEqual(getdate(membership.commitment_end_date), getdate(custom_commitment_date))


class TestMembershipTerminationCommitmentValidation(EnhancedTestCase):
    """Test commitment period validation in termination requests"""

    def tearDown(self):
        """Clean up test data"""
        frappe.db.rollback()
        super().tearDown()

    def test_voluntary_termination_blocked_before_commitment_end(self):
        """Test that voluntary terminations are blocked before commitment period ends"""
        # Create member with active membership
        member = self.create_test_member(first_name="Early", last_name="Quitter", birth_date="1990-01-01")

        # Create membership type
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Test Block Early",
                "billing_period": "Annual",
                "minimum_amount": 50.0,
                "role_profile": "Verenigingen Staff",
                "is_active": 1,
            }
        ).insert()

        # Create membership that started recently
        start_date = add_to_date(today(), months=-3)  # 3 months ago
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "start_date": start_date,
            }
        )
        membership.insert()
        membership.submit()

        # Link membership to member
        member.reload()
        member.current_membership_plan = membership.name
        member.save()

        # Try to create voluntary termination request before commitment end
        termination_date = add_to_date(today(), months=1)  # Only 4 months in
        termination = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member.name,
                "termination_type": "Voluntary",
                "termination_date": termination_date,
                "termination_reason": "Want to quit early",
            }
        )

        # Should raise validation error
        with self.assertRaises(frappe.ValidationError) as context:
            termination.insert()

        self.assertIn("commitment period", str(context.exception).lower())

    def test_voluntary_termination_allowed_after_commitment_end(self):
        """Test that voluntary terminations are allowed after commitment period"""
        # Create member with active membership
        member = self.create_test_member(first_name="Patient", last_name="Member", birth_date="1990-01-01")

        # Create membership type
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Test Allow After",
                "billing_period": "Annual",
                "minimum_amount": 50.0,
                "role_profile": "Verenigingen Staff",
                "is_active": 1,
            }
        ).insert()

        # Create membership that started over a year ago
        start_date = add_to_date(today(), months=-15)  # 15 months ago
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "start_date": start_date,
            }
        )
        membership.insert()
        membership.submit()

        # Link membership to member
        member.reload()
        member.current_membership_plan = membership.name
        member.save()

        # Create voluntary termination request after commitment end
        termination = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member.name,
                "termination_type": "Voluntary",
                "termination_date": today(),
                "termination_reason": "Completed commitment, now leaving",
            }
        )

        # Should succeed without error
        termination.insert()
        self.assertEqual(termination.termination_type, "Voluntary")

    def test_disciplinary_termination_bypasses_commitment_check(self):
        """Test that disciplinary terminations bypass commitment period validation"""
        # Create member with active membership
        member = self.create_test_member(first_name="Discipline", last_name="Case", birth_date="1990-01-01")

        # Create membership type
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Test Disciplinary Bypass",
                "billing_period": "Annual",
                "minimum_amount": 50.0,
                "role_profile": "Verenigingen Staff",
                "is_active": 1,
            }
        ).insert()

        # Create membership that started recently
        start_date = add_to_date(today(), months=-2)  # 2 months ago
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "start_date": start_date,
            }
        )
        membership.insert()
        membership.submit()

        # Link membership to member
        member.reload()
        member.current_membership_plan = membership.name
        member.save()

        # Create disciplinary termination (should bypass commitment check)
        termination = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member.name,
                "termination_type": "Policy Violation",
                "termination_date": today(),
                "termination_reason": "Violated code of conduct",
                "disciplinary_documentation": "Evidence of policy violation",
                "secondary_approver": frappe.session.user,
            }
        )

        # Should succeed even though commitment period not complete
        termination.insert()
        self.assertEqual(termination.termination_type, "Policy Violation")

    def test_termination_allowed_if_no_commitment_set(self):
        """Test that termination is allowed if no commitment_end_date is set"""
        # Create member with active membership
        member = self.create_test_member(first_name="No", last_name="Commitment", birth_date="1990-01-01")

        # Create membership type
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Test No Commitment",
                "billing_period": "Annual",
                "minimum_amount": 50.0,
                "role_profile": "Verenigingen Staff",
                "is_active": 1,
            }
        ).insert()

        # Create membership
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "start_date": today(),
            }
        )
        membership.insert()
        membership.submit()

        # Manually clear commitment_end_date to simulate legacy data
        frappe.db.set_value(
            "Membership",
            membership.name,
            "commitment_end_date",
            None,
            update_modified=False,
        )

        # Link membership to member
        member.reload()
        member.current_membership_plan = membership.name
        member.save()

        # Create voluntary termination - should succeed with no commitment set
        termination = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member.name,
                "termination_type": "Voluntary",
                "termination_date": today(),
                "termination_reason": "No commitment to check",
            }
        )

        # Should succeed
        termination.insert()
        self.assertEqual(termination.termination_type, "Voluntary")
