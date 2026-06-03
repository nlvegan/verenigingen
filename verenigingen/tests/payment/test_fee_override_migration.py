# -*- coding: utf-8 -*-
"""
Test suite for fee override migration and new dues schedule architecture
Tests the migration from legacy override fields to child DocType approach
"""

import frappe
from frappe.utils import flt, today
from verenigingen.tests.support.sepa_test_company import ensure_sepa_payment_terms_template
from verenigingen.tests.utils.base import VereningingenTestCase


class TestFeeOverrideMigration(VereningingenTestCase):
    """Test fee resolution and the Contribution Amendment Request (CAR) workflow.

    The legacy "direct dues schedule creation" portal path is permanently
    deprecated; all fee adjustments now flow through the CAR workflow, and a
    submitted Membership always auto-creates exactly one Active dues schedule.
    These tests assert that current model rather than the removed override model.
    """

    def setUp(self):
        super().setUp()
        # Applying an amendment can (re)create a dues schedule whose
        # payment_terms_template = "SEPA Direct Debit"; ensure that master exists.
        ensure_sepa_payment_terms_template()
        self.test_member = self.create_test_member()
        self.test_membership_type = self.create_test_membership_type()

    def test_effective_fee_uses_active_dues_schedule(self):
        """get_effective_fee_for_member returns the active dues schedule's rate."""
        from verenigingen.templates.pages.membership_adjustment import get_effective_fee_for_member

        membership = self.create_test_membership()
        # Reconfigures the membership's auto-created Active schedule to €25.
        self.create_test_dues_schedule(25.0)

        fee_info = get_effective_fee_for_member(self.test_member, membership)
        self.assertEqual(fee_info["source"], "dues_schedule")
        self.assertEqual(flt(fee_info["amount"]), 25.0)
        self.assertIn("schedule_name", fee_info)

    def test_effective_fee_falls_back_to_legacy_override(self):
        """With no Active dues schedule, the legacy member.dues_rate is used.

        The auto-created schedule must be cancelled first; this exercises the
        PRIORITY 3 ('member_override') branch that is otherwise shadowed by the
        always-present Active schedule.
        """
        from verenigingen.templates.pages.membership_adjustment import get_effective_fee_for_member

        membership = self.create_test_membership()

        # Cancel the auto-created Active schedule so no Active schedule remains.
        schedule = self.create_test_dues_schedule(20.0)
        schedule.status = "Cancelled"
        schedule.save()

        # Set a legacy override directly (db.set_value bypasses the fee-change
        # history tracking that a doc.save() would trigger), then reload so the
        # in-memory member carries the override.
        frappe.db.set_value("Member", self.test_member.name, "dues_rate", 30.0, update_modified=False)
        self.test_member.reload()

        fee_info = get_effective_fee_for_member(self.test_member, membership)
        self.assertEqual(fee_info["source"], "member_override")
        self.assertEqual(flt(fee_info["amount"]), 30.0)
        self.assertIn("Legacy fee override", fee_info["reason"])

    def test_direct_dues_schedule_creation_is_deprecated(self):
        """create_new_dues_schedule() is permanently deprecated and always raises."""
        from verenigingen.templates.pages.membership_adjustment import create_new_dues_schedule

        self.create_test_membership()

        with self.assertRaises(frappe.ValidationError) as ctx:
            create_new_dues_schedule(self.test_member, 35.0, "Testing new schedule")
        self.assertIn("no longer allowed", str(ctx.exception))
        self.assertIn("Contribution Amendment Request", str(ctx.exception))

    def test_zero_amount_fee_change_rejected(self):
        """A Fee Change amendment with a non-positive amount is rejected."""
        membership = self.create_test_membership()
        self.create_test_dues_schedule(25.0)

        with self.assertRaises(frappe.ValidationError) as ctx:
            amendment = frappe.get_doc(
                {
                    "doctype": "Contribution Amendment Request",
                    "member": self.test_member.name,
                    "membership": membership.name,
                    "amendment_type": "Fee Change",
                    "requested_amount": 0.0,
                    "reason": "Free membership",
                    "effective_date": today(),
                }
            )
            amendment.insert()
        self.assertIn("greater than 0", str(ctx.exception))

    def test_fee_history_reflects_amendments(self):
        """get_member_fee_history surfaces Fee Change amendment requests."""
        from verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request import (
            create_fee_change_amendment,
        )
        from verenigingen.templates.pages.membership_adjustment import get_member_fee_history

        self.create_test_membership()
        self.create_test_dues_schedule(100.0)

        amendment = create_fee_change_amendment(
            self.test_member.name, 150.0, "Voluntary increase"
        )
        self.track_doc("Contribution Amendment Request", amendment.name)

        history = get_member_fee_history(self.test_member.name)
        self.assertTrue(history, "Fee history should not be empty")

        amendment_entries = [h for h in history if h["source"] == "amendment_request"]
        self.assertTrue(
            amendment_entries, "Fee history should include the amendment request"
        )
        self.assertTrue(any(flt(h["amount"]) == 150.0 for h in amendment_entries))
        self.assertTrue(any("Voluntary increase" in (h["reason"] or "") for h in amendment_entries))

    def test_migration_data_integrity(self):
        """Test that migration preserves data integrity

        NOTE: This test is currently skipped because the migration script
        (migrate_fee_overrides_to_dues_schedules.py) has not been implemented yet.
        When implementing the migration script, uncomment this test.
        """
        self.skipTest("Migration script migrate_fee_overrides_to_dues_schedules.py not yet implemented")

        # Create member with override
        self.test_member.dues_rate = 45.0
        self.test_member.fee_override_reason = "Special case"
        self.test_member.fee_override_date = today()
        self.test_member.save()

        # Simulate migration
        from scripts.migration.migrate_fee_overrides_to_dues_schedules import migrate_member_override

        membership = self.create_test_membership()

        member_data = {
            "name": self.test_member.name,
            "full_name": self.test_member.full_name,
            "dues_rate": 45.0,
            "fee_override_reason": "Special case",
            "fee_override_date": today(),
        }

        migrate_member_override(member_data)

        # Verify dues schedule was created
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.test_member.name, "custom_amount_reason": ["like", "%Special case%"]},
            ["name", "dues_rate", "custom_amount_reason"],
            as_dict=True,
        )

        self.assertIsNotNone(dues_schedule)
        self.assertEqual(dues_schedule.dues_rate, 45.0)
        self.assertIn("Special case", dues_schedule.custom_amount_reason)

    def test_enhanced_fee_calculation_api(self):
        """Test the enhanced fee calculation API"""
        from verenigingen.templates.pages.membership_adjustment import get_fee_calculation_info

        # Create membership
        membership = self.create_test_membership()

        # Create dues schedule
        dues_schedule = self.create_test_dues_schedule(30.0)

        # get_fee_calculation_info is a MEDIUM-security endpoint (Volunteer/Staff/
        # Admin), and it resolves the member via the User link. Create a staff user
        # linked to the member so the call both passes the security contract and
        # resolves to this member.
        staff_email = f"feecalc.staff.{frappe.generate_hash(length=6)}@example.com"
        staff_user = self.create_test_user(staff_email, roles=["Verenigingen Staff"])
        frappe.db.set_value("Member", self.test_member.name, "user", staff_user.name)
        frappe.db.commit()

        # Mock user session
        original_user = frappe.session.user
        frappe.session.user = staff_user.name

        try:
            # Get fee calculation info
            fee_info = get_fee_calculation_info()

            # Verify enhanced information is returned
            self.assertIn("current_fee", fee_info)
            self.assertIn("current_source", fee_info)
            self.assertIn("current_reason", fee_info)
            self.assertIn("fee_history", fee_info)
            self.assertIn("active_dues_schedule", fee_info)

            # Verify current fee comes from dues schedule
            self.assertEqual(fee_info["current_fee"], 30.0)
            self.assertEqual(fee_info["current_source"], "dues_schedule")
            self.assertEqual(fee_info["active_dues_schedule"], dues_schedule.name)

        finally:
            frappe.session.user = original_user

    # Helper methods

    def create_test_membership(self):
        """Create a test membership for the test member"""
        # Check if membership already exists
        existing_membership = frappe.db.get_value(
            "Membership", {"member": self.test_member.name, "status": "Active"}, "name"
        )

        if existing_membership:
            return frappe.get_doc("Membership", existing_membership)

        membership = frappe.new_doc("Membership")
        membership.member = self.test_member.name
        membership.membership_type = self.test_membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        membership.submit()
        self.track_doc("Membership", membership.name)
        return membership

    def create_test_dues_schedule(self, amount):
        """Create a test dues schedule (reusing the membership's auto-created one).

        Submitting a Membership auto-creates one Active dues schedule and only
        one active schedule per member is allowed, so reconfigure that schedule
        rather than insert a colliding new one.
        """
        # The local create_test_membership() helper takes no arguments and
        # already submits (which auto-creates the Active dues schedule).
        self.create_test_membership()

        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.test_member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        dues_schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        # "Custom" contribution_mode was renamed to "Fixed"; custom amounts are
        # represented as Fixed + uses_custom_amount.
        dues_schedule.contribution_mode = "Fixed"
        dues_schedule.dues_rate = amount
        dues_schedule.uses_custom_amount = 1
        dues_schedule.custom_amount_approved = 1
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.payment_method = "Bank Transfer"
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule

    def create_test_membership_type(self):
        """Create a test membership type.

        NOTE: contribution_mode was removed from Membership Type (contribution
        config now lives on the Dues Schedule Template). A low minimum keeps the
        auto-created template rate (€15) valid.
        """
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Test Migration Type {frappe.generate_hash(length=6)}"
        membership_type.minimum_amount = 5.0
        membership_type.is_active = 1
        membership_type.role_profile = frappe.db.get_value(
            "Role Profile", {"name": ["like", "%Member%"]}, "name"
        ) or frappe.db.get_value("Role Profile", {}, "name")
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type
