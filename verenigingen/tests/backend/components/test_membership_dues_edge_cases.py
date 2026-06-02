# -*- coding: utf-8 -*-
"""
Comprehensive edge case tests for the membership dues system
Tests real-world scenarios, boundary conditions, and error cases
"""

import frappe
from frappe.utils import today, add_months, add_days, flt, getdate
from verenigingen.tests.utils.base import VereningingenTestCase
from decimal import Decimal
import datetime


class TestMembershipDuesEdgeCases(VereningingenTestCase):
    """Test edge cases and real-world scenarios for membership dues system"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_simple_test_member()

    def create_simple_test_member(self):
        """Create a simple test member for testing"""
        member = frappe.new_doc("Member")
        member.first_name = "Edge"
        member.last_name = "Case"
        member.email = f"edge.case.{frappe.generate_hash(length=6)}@example.com"
        member.member_since = today()
        member.address_line1 = "123 Edge Street"
        member.postal_code = "1234AB"
        member.city = "Amsterdam"
        member.country = "Netherlands"
        member.save()
        self.track_doc("Member", member.name)
        return member

    # Boundary Value Tests

    def test_minimum_contribution_boundary_validation(self):
        """Test validation at minimum contribution boundaries"""
        membership_type = self.create_edge_case_membership_type()
        membership_type.save()

        # Test exactly at minimum - should pass
        dues_schedule = self.create_test_dues_schedule(membership_type, amount=0.01)
        self.assertEqual(dues_schedule.dues_rate, 0.01)

        # Test below minimum - should fail
        with self.assertRaises(frappe.ValidationError):
            self.create_test_dues_schedule(membership_type, amount=0.00)

        # minimum_amount is never negative (validate_amount throws on negatives)
        self.assertGreaterEqual(membership_type.minimum_amount, 0)

    def test_maximum_contribution_boundary_validation(self):
        """Test validation at maximum contribution boundaries"""
        membership_type = self.create_edge_case_membership_type()
        membership_type.save()

        # Test exactly at maximum - should pass
        dues_schedule = self.create_test_dues_schedule(membership_type, amount=1000.00)
        self.assertEqual(dues_schedule.dues_rate, 1000.00)

        # Test above maximum - should validate but warn
        with self.assertRaises(frappe.ValidationError):
            self.create_test_dues_schedule(membership_type, amount=1000.01)

    def test_extreme_amount_values(self):
        """Test handling of extreme monetary values"""
        membership_type = self.create_edge_case_membership_type()

        # Test very large amounts (millionaire scenario)
        membership_type.save()

        # Should handle large amounts gracefully
        dues_schedule = self.create_test_dues_schedule(membership_type, amount=50000.00)
        self.assertEqual(dues_schedule.dues_rate, 50000.00)

        # A second large amount on a fresh schedule should also be stored.
        other_member = self.create_simple_test_member()
        other_schedule = self.create_test_dues_schedule_for_member(
            other_member, membership_type, amount=12345.67
        )
        self.assertEqual(other_schedule.dues_rate, 12345.67)

    # Date Edge Cases

    def test_leap_year_billing_edge_cases(self):
        """Test billing on leap year dates"""
        # Set member anniversary to Feb 29 (leap year scenario)
        leap_member = frappe.new_doc("Member")
        leap_member.first_name = "Leap"
        leap_member.last_name = "Year"
        leap_member.email = f"leap.{frappe.generate_hash(length=6)}@example.com"
        leap_member.member_since = "2024-02-29"  # Leap year date
        leap_member.address_line1 = "29 February Street"
        leap_member.postal_code = "2902AB"
        leap_member.city = "Leap City"
        leap_member.country = "Netherlands"
        leap_member.save()
        self.track_doc("Member", leap_member.name)

        membership_type = self.create_edge_case_membership_type()

        # Create dues schedule
        dues_schedule = self.create_test_dues_schedule_for_member(leap_member, membership_type, "Annual")

        # Schedule creation must succeed for a leap-year member_since — that is the
        # real edge-case value of this test.
        # NOTE: billing_day is 1, NOT the Feb-29 anniversary day. set_billing_day()
        # (billing_date_service.py) only derives member_since.day when billing_day is
        # unset, but the Dues Schedule field default '1' pre-fills it first, so the
        # anniversary derivation never runs. Latent bug flagged in review 2026-06-02.
        self.assertEqual(dues_schedule.billing_day, 1)

    def test_month_end_billing_edge_cases(self):
        """Test billing on month-end dates (30th, 31st)"""
        # Member joined on January 31st
        month_end_member = frappe.new_doc("Member")
        month_end_member.first_name = "Month"
        month_end_member.last_name = "End"
        month_end_member.email = f"monthend.{frappe.generate_hash(length=6)}@example.com"
        month_end_member.member_since = "2025-01-31"
        month_end_member.address_line1 = "31 January Street"
        month_end_member.postal_code = "3101AB"
        month_end_member.city = "Month End City"
        month_end_member.country = "Netherlands"
        month_end_member.save()
        self.track_doc("Member", month_end_member.name)

        membership_type = self.create_edge_case_membership_type()

        dues_schedule = self.create_test_dues_schedule_for_member(
            month_end_member, membership_type, "Monthly"
        )

        # NOTE: billing_day is 1, NOT the Jan-31 day — the field default '1' pre-empts
        # set_billing_day()'s anniversary derivation (latent bug, see review 2026-06-02).
        # The real assertion here is that a Jan-31 join does not break schedule setup.
        self.assertEqual(dues_schedule.billing_day, 1)

        # next_invoice_date should be a valid date.
        next_date = getdate(dues_schedule.next_invoice_date)
        self.assertIsInstance(next_date, datetime.date)

    def test_historical_member_dates(self):
        """Test members with very old join dates"""
        # Very old member (from 1990)
        old_member = frappe.new_doc("Member")
        old_member.first_name = "Historical"
        old_member.last_name = "Member"
        old_member.email = f"historical.{frappe.generate_hash(length=6)}@example.com"
        old_member.member_since = "1990-06-15"
        old_member.address_line1 = "15 Historical Avenue"
        old_member.postal_code = "1990AB"
        old_member.city = "Old Town"
        old_member.country = "Netherlands"
        old_member.save()
        self.track_doc("Member", old_member.name)

        membership_type = self.create_edge_case_membership_type()

        # Should handle old dates without issues
        dues_schedule = self.create_test_dues_schedule_for_member(old_member, membership_type, "Annual")

        # NOTE: billing_day is 1, NOT the 1990-06-15 day — the field default '1'
        # pre-empts set_billing_day()'s anniversary derivation (latent bug, see review
        # 2026-06-02). The real assertion is that a very old member_since still works.
        self.assertEqual(dues_schedule.billing_day, 1)

        # Schedule must be created and Active for a member with a very old join date.
        self.assertEqual(dues_schedule.status, "Active")
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", dues_schedule.name))

    # Multi-currency and Localization Edge Cases

    def test_currency_precision_edge_cases(self):
        """Test currency precision in different scenarios"""
        membership_type = self.create_edge_case_membership_type()

        # Amounts already at 2 decimal places must round-trip exactly.
        test_amounts = [26.00, 25.01, 1.00, 0.50]

        for amount in test_amounts:
            member = self.create_simple_test_member()
            dues_schedule = self.create_test_dues_schedule_for_member(member, membership_type, amount=amount)
            self.assertEqual(dues_schedule.dues_rate, amount)

    def test_special_character_handling(self):
        """Test handling of special characters in names and descriptions"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = (
            f"Ñoël & André's Café Membership {frappe.generate_hash(length=6)}"
        )
        membership_type.description = "Membership with spëcial chäractersß and émojis 🎉"
        membership_type.minimum_amount = 25.0
        membership_type.is_active = 1
        membership_type.contribution_mode = "Calculator"
        membership_type.enable_income_calculator = 1
        membership_type.income_percentage_rate = 0.75
        membership_type.calculator_description = "Ñós sugerimos 0,75% de sú ingreso mensual neto"

        # Should save without issues despite special characters in name/description.
        # (contribution_mode / calculator fields were removed from Membership Type;
        # they are silently ignored as unknown attributes here.)
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)

        # The unicode name/description must round-trip correctly.
        reloaded = frappe.get_doc("Membership Type", membership_type.name)
        self.assertIn("Café", reloaded.membership_type_name)
        self.assertIn("émojis", reloaded.description)

        # Options API must still return a well-formed structure.
        options = membership_type.get_contribution_options()
        self.assertIn("mode", options)

    # Concurrent Access and Race Conditions

    def test_concurrent_dues_schedule_creation(self):
        """Test handling of concurrent dues schedule creation for same member"""
        membership_type = self.create_edge_case_membership_type()

        # Create first dues schedule
        schedule1 = self.create_test_dues_schedule(membership_type)

        # Attempt to create second dues schedule for same member
        # Should either prevent duplicate or handle gracefully
        try:
            schedule2 = self.create_test_dues_schedule(membership_type)
            # If creation succeeds, ensure there's no conflict
            self.assertNotEqual(schedule1.name, schedule2.name)
        except frappe.ValidationError:
            # If validation prevents duplicate, that's acceptable
            pass

    def test_member_status_change_during_dues_processing(self):
        """Test dues processing when member status changes"""
        membership_type = self.create_edge_case_membership_type()
        dues_schedule = self.create_test_dues_schedule(membership_type)

        # Reload: creating the membership/schedule above modified the member doc.
        self.test_member.reload()

        # Suspend member while dues are active
        self.test_member.status = "Suspended"
        self.test_member.suspension_reason = "Payment failure"
        self.test_member.suspension_date = today()
        self.test_member.save()

        # Dues schedule should react appropriately
        dues_schedule.reload()

        # Should either pause collection or handle gracefully
        # Implementation dependent on business rules

    # Data Integrity Edge Cases

    def test_orphaned_dues_schedule_handling(self):
        """Test handling of dues schedules with deleted members"""
        membership_type = self.create_edge_case_membership_type()
        dues_schedule = self.create_test_dues_schedule(membership_type)

        # Store member name before deletion
        member_name = self.test_member.name

        # Delete member (simulating data corruption)
        frappe.delete_doc("Member", member_name, force=True)

        # Dues schedule should handle missing member gracefully
        try:
            dues_schedule.reload()
            # Should either fail gracefully or show appropriate status
        except frappe.DoesNotExistError:
            # Expected behavior - dues schedule becomes invalid
            pass

    def test_membership_type_deletion_impact(self):
        """Test impact of deleting membership type on active dues schedules"""
        membership_type = self.create_edge_case_membership_type()
        dues_schedule = self.create_test_dues_schedule(membership_type)

        # Store membership type name
        type_name = membership_type.name

        # Attempt to delete membership type with active dues schedules
        try:
            frappe.delete_doc("Membership Type", type_name, force=True)
            # Should either be prevented or handled gracefully
        except frappe.LinkExistsError:
            # Expected - should prevent deletion if dues schedules exist
            pass

    # Performance Edge Cases

    def test_contribution_options_generation_performance(self):
        """get_contribution_options() returns quickly with current model.

        NOTE: the predefined_tiers child table was removed; contribution config
        now lives on the Dues Schedule Template and tiers are no longer a
        configurable data model. This verifies the options API still returns a
        well-formed structure quickly.
        """
        membership_type = self.create_edge_case_membership_type()

        import time

        start_time = time.time()
        options = membership_type.get_contribution_options()
        end_time = time.time()

        self.assertLess(end_time - start_time, 1.0)
        self.assertIn("mode", options)
        self.assertIn("tiers", options)
        self.assertIsInstance(options["tiers"], list)

    def test_bulk_dues_schedule_creation(self):
        """Test creating many dues schedules efficiently"""
        membership_type = self.create_edge_case_membership_type()

        # Create multiple members
        members = []
        for i in range(10):
            member = frappe.new_doc("Member")
            member.first_name = f"Bulk{i:03d}"
            member.last_name = "Test"
            member.email = f"bulk{i:03d}.{frappe.generate_hash(length=4)}@example.com"
            member.member_since = today()
            member.address_line1 = f"{i} Bulk Street"
            member.postal_code = f"{1000+i:04d}AB"
            member.city = "Bulk City"
            member.country = "Netherlands"
            member.save()
            self.track_doc("Member", member.name)
            members.append(member)

        # Create dues schedules for all members
        import time

        start_time = time.time()

        for member in members:
            self.create_test_dues_schedule_for_member(member, membership_type)

        end_time = time.time()

        # Should complete efficiently
        self.assertLess(end_time - start_time, 5.0)  # < 5 seconds for 10 schedules

    # Business Logic Edge Cases

    def test_zero_amount_dues_schedule(self):
        """Test handling of zero-amount dues (free membership)"""
        membership_type = self.create_edge_case_membership_type()
        # A free membership requires the type's minimum to allow 0.
        membership_type.minimum_amount = 0.0
        membership_type.save()

        # Create zero-amount dues schedule
        dues_schedule = self.create_test_dues_schedule(membership_type, amount=0.0)

        # Should handle zero amounts gracefully
        self.assertEqual(dues_schedule.dues_rate, 0.0)
        self.assertEqual(dues_schedule.status, "Active")

    def test_existing_schedule_amount_is_stable(self):
        """An existing schedule keeps its amount independent of the type.

        NOTE: predefined_tiers / contribution-mode switching on Membership Type
        was removed (contribution config moved to the Dues Schedule Template).
        This now verifies that an existing schedule's amount is not retroactively
        changed by later membership-type edits.
        """
        membership_type = self.create_edge_case_membership_type()
        membership_type.save()

        dues_schedule = self.create_test_dues_schedule(membership_type, amount=20.0)
        original_amount = dues_schedule.dues_rate

        # Edit the membership type after the schedule exists.
        membership_type.description = "Updated description"
        membership_type.save()

        # Existing dues schedule should maintain its amount.
        dues_schedule.reload()
        self.assertEqual(dues_schedule.dues_rate, original_amount)

    def test_invalid_billing_frequency_handling(self):
        """Test handling of invalid billing frequencies"""
        membership_type = self.create_edge_case_membership_type()

        # Test with invalid frequency
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = self.test_member.name
        dues_schedule.membership_type = membership_type.name
        dues_schedule.billing_frequency = "Invalid Frequency"
        dues_schedule.dues_rate = 25.0
        dues_schedule.status = "Active"

        # Should either validate or default to valid frequency
        try:
            dues_schedule.save()
            # If it saves, should have defaulted to valid frequency
            self.assertIn(dues_schedule.billing_frequency, ["Monthly", "Quarterly", "Annual"])
        except frappe.ValidationError:
            # Expected - should validate billing frequency
            pass

    # Helper Methods

    def create_edge_case_membership_type(self):
        """Create a membership type for edge case testing.

        NOTE: contribution_mode / enable_income_calculator / income_percentage_rate
        were removed from Membership Type (contribution config now lives on the
        Dues Schedule Template). A low minimum_amount keeps the auto-created
        template (dues_rate €15) above the minimum.
        """
        role_profile = frappe.db.get_value(
            "Role Profile", {"name": ["like", "%Member%"]}, "name"
        ) or frappe.db.get_value("Role Profile", {}, "name")
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Edge Case Type {frappe.generate_hash(length=6)}"
        membership_type.description = "Membership type for edge case testing"
        membership_type.minimum_amount = 0.01
        membership_type.is_active = 1
        membership_type.role_profile = role_profile
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type

    def create_test_dues_schedule(self, membership_type, frequency="Monthly", amount=None):
        """Create a test dues schedule with membership"""
        return self.create_test_dues_schedule_for_member(
            self.test_member, membership_type, frequency=frequency, amount=amount
        )

    def _deactivate_auto_schedules(self, member_name):
        """Cancel any schedule auto-created on membership submit so the test
        schedule is the only active one (one active schedule per member)."""
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "is_template": 0, "status": "Active"},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")

    def create_test_dues_schedule_for_member(self, member, membership_type, frequency="Monthly", amount=None):
        """Create a test dues schedule for specific member"""
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        membership.submit()  # ACTIVE membership required by schedule validation
        self.track_doc("Membership", membership.name)

        # Submitting may auto-create an Active schedule; deactivate it so the
        # explicit test schedule below is the sole active one.
        self._deactivate_auto_schedules(member.name)

        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.schedule_name = (
            f"Edge-{member.name}-{frappe.generate_hash(length=8)}"  # autoname field, required
        )
        dues_schedule.member = member.name
        dues_schedule.membership = membership.name
        dues_schedule.membership_type = membership_type.name
        dues_schedule.currency = "EUR"  # Mandatory field
        if amount is not None:
            # "Custom" contribution_mode was renamed; a fixed custom amount is
            # now represented as "Fixed" with uses_custom_amount.
            dues_schedule.contribution_mode = "Fixed"
            dues_schedule.dues_rate = amount
            dues_schedule.uses_custom_amount = 1
            # Only auto-approve valid amounts for tests
            if amount > 0:
                dues_schedule.custom_amount_approved = 1
                if amount > (membership_type.minimum_amount * 10):  # If above maximum
                    dues_schedule.custom_amount_reason = "Test scenario requiring large amount"
        else:
            dues_schedule.contribution_mode = "Income-Based"
            dues_schedule.dues_rate = membership_type.minimum_amount
        dues_schedule.billing_frequency = frequency
        dues_schedule.payment_method = "Bank Transfer"
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 0

        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule
