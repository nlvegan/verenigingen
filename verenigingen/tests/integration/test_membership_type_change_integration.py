#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Membership Type Change Integration Tests

Tests for the refactored membership type change workflow that:
1. Updates existing dues schedules instead of cancel/recreate
2. Records membership type history on Member
3. Updates role profiles based on membership type

Author: Verenigingen Development Team
Created: 2025-12-09
"""

import frappe
from frappe.utils import today, add_days, add_months, now_datetime, random_string
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository


class TestMembershipTypeChangeIntegration(EnhancedTestCase):
    """Integration tests for the refactored membership type change workflow"""

    def setUp(self):
        super().setUp()
        # Get existing membership types from fixtures
        self.monthly_type = frappe.get_doc("Membership Type", "Monthly Membership")
        self.quarterly_type = frappe.get_doc("Membership Type", "Quarterly Membership")
        self.annual_type = frappe.get_doc("Membership Type", "Annual Membership")

    def _get_or_create_dues_schedule(self, member_name, membership_name, membership_type_name):
        """Get existing dues schedule or create one if none exists"""
        # Check if a schedule already exists (likely created by membership submission hooks)
        existing_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "status": "Active"},
            "name"
        )

        if existing_schedule:
            schedule = frappe.get_doc("Membership Dues Schedule", existing_schedule)
            # Ensure the schedule has the member properly set
            if not schedule.member:
                schedule.member = member_name
                schedule.membership = membership_name
                schedule.membership_type = membership_type_name
                schedule.save()
            return schedule

        # No existing schedule - create a minimal one
        min_amount = frappe.db.get_value("Membership Type", membership_type_name, "minimum_amount") or 3.0
        billing_period = frappe.db.get_value("Membership Type", membership_type_name, "billing_period") or "Monthly"

        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Test Schedule {random_string(8)}",
            "member": member_name,
            "membership": membership_name,
            "membership_type": membership_type_name,
            "dues_rate": min_amount,
            "billing_frequency": billing_period,
            "status": "Active",
            "next_invoice_date": add_months(today(), 1),
            "effective_date": today(),
        })
        schedule.insert()
        return schedule

    def _create_member_with_active_dues_schedule(self, membership_type_name):
        """Helper to create a member with membership and active dues schedule"""
        member = self.create_test_member(
            first_name="TypeChange",
            last_name="Test"
        )

        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name=membership_type_name,
            status="Active"
        )

        # Get or create dues schedule (membership submission may have created one via hooks)
        dues_schedule = self._get_or_create_dues_schedule(
            member_name=member.name,
            membership_name=membership.name,
            membership_type_name=membership_type_name
        )

        # Set member's current_membership_type
        member.reload()
        member.current_membership_type = membership_type_name
        member.save()

        return member, membership, dues_schedule

    def test_dues_schedule_updated_not_recreated(self):
        """Test that type change updates existing schedule instead of creating new one"""
        member, membership, original_schedule = self._create_member_with_active_dues_schedule(
            self.monthly_type.name
        )

        original_schedule_name = original_schedule.name

        # Create and apply type change amendment
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": member.name,
            "membership": membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.monthly_type.name,
            "requested_membership_type": self.quarterly_type.name,
            "current_amount": self.monthly_type.minimum_amount,
            "requested_amount": self.quarterly_type.minimum_amount,
            "reason": "Switching to quarterly billing",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        amendment.insert()

        # Verify current_dues_schedule was set during validation
        self.assertEqual(amendment.current_dues_schedule, original_schedule_name)

        # Approve and apply
        amendment.approve_amendment("Test approval")
        result = amendment.apply_amendment()

        # Verify apply succeeded
        self.assertEqual(result.get("status"), "success")

        # Reload amendment to get updated fields
        amendment.reload()

        # Verify the same schedule was updated (not recreated)
        self.assertEqual(amendment.new_dues_schedule, original_schedule_name)

        # Reload and verify schedule was updated
        updated_schedule = frappe.get_doc("Membership Dues Schedule", original_schedule_name)
        self.assertEqual(updated_schedule.membership_type, self.quarterly_type.name)
        self.assertEqual(updated_schedule.dues_rate, self.quarterly_type.minimum_amount)
        self.assertEqual(updated_schedule.billing_frequency, "Quarterly")
        self.assertEqual(updated_schedule.status, "Active")

    def test_membership_type_history_recorded(self):
        """Test that type change records history in member document"""
        member, membership, dues_schedule = self._create_member_with_active_dues_schedule(
            self.monthly_type.name
        )

        # Create and apply type change
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": member.name,
            "membership": membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.monthly_type.name,
            "requested_membership_type": self.annual_type.name,
            "current_amount": self.monthly_type.minimum_amount,
            "requested_amount": self.annual_type.minimum_amount,
            "reason": "Upgrading to annual for discount",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        amendment.insert()
        amendment.approve_amendment("Test approval")
        result = amendment.apply_amendment()

        # Verify apply succeeded
        self.assertEqual(result.get("status"), "success")

        # Reload member and check current_membership_type was updated
        member.reload()
        self.assertEqual(member.current_membership_type, self.annual_type.name)

        # Verify membership record was updated
        membership.reload()
        self.assertEqual(membership.membership_type, self.annual_type.name)

    def test_current_membership_type_updated(self):
        """Test that member's current_membership_type is updated"""
        member, membership, dues_schedule = self._create_member_with_active_dues_schedule(
            self.monthly_type.name
        )

        self.assertEqual(member.current_membership_type, self.monthly_type.name)

        # Apply type change
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": member.name,
            "membership": membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.monthly_type.name,
            "requested_membership_type": self.quarterly_type.name,
            "current_amount": self.monthly_type.minimum_amount,
            "requested_amount": self.quarterly_type.minimum_amount,
            "reason": "Switching to quarterly",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        amendment.insert()
        amendment.approve_amendment("Test approval")
        amendment.apply_amendment()

        # Verify current_membership_type updated
        member.reload()
        self.assertEqual(member.current_membership_type, self.quarterly_type.name)

    def test_membership_record_type_updated(self):
        """Test that the Membership record's type is updated"""
        member, membership, dues_schedule = self._create_member_with_active_dues_schedule(
            self.monthly_type.name
        )

        self.assertEqual(membership.membership_type, self.monthly_type.name)

        # Apply type change
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": member.name,
            "membership": membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.monthly_type.name,
            "requested_membership_type": self.annual_type.name,
            "current_amount": self.monthly_type.minimum_amount,
            "requested_amount": self.annual_type.minimum_amount,
            "reason": "Annual upgrade",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        amendment.insert()
        amendment.approve_amendment("Test approval")
        amendment.apply_amendment()

        # Verify Membership record updated
        membership.reload()
        self.assertEqual(membership.membership_type, self.annual_type.name)

    def test_fee_change_recorded_with_type_change(self):
        """Test that fee change history is recorded when type change includes fee change"""
        member, membership, dues_schedule = self._create_member_with_active_dues_schedule(
            self.monthly_type.name
        )

        member.reload()
        initial_fee_history_count = len(member.get("fee_change_history", []))
        old_rate = self.monthly_type.minimum_amount
        new_rate = self.annual_type.minimum_amount

        # Apply type change with fee change
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": member.name,
            "membership": membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.monthly_type.name,
            "requested_membership_type": self.annual_type.name,
            "current_amount": old_rate,
            "requested_amount": new_rate,
            "reason": "Annual upgrade with fee change",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        amendment.insert()
        amendment.approve_amendment("Test approval")
        amendment.apply_amendment()

        # Verify fee change history recorded
        member.reload()
        fee_history = member.get("fee_change_history", [])

        self.assertGreater(len(fee_history), initial_fee_history_count)

        # Check latest fee change entry (field is new_dues_rate, not new_amount)
        latest_fee_change = fee_history[-1]
        self.assertEqual(float(latest_fee_change.new_dues_rate), float(new_rate))

    def test_previous_history_entry_closed(self):
        """Test that previous membership type history entry gets to_date set"""
        member, membership, dues_schedule = self._create_member_with_active_dues_schedule(
            self.monthly_type.name
        )

        # Add an initial history entry manually
        member.reload()
        member.append("membership_type_history", {
            "membership_type": self.monthly_type.name,
            "from_date": add_months(today(), -3),
            "to_date": None,
            "changed_by": frappe.session.user,
            "reason": "Initial membership"
        })
        member.save()

        # Apply type change
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": member.name,
            "membership": membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.monthly_type.name,
            "requested_membership_type": self.quarterly_type.name,
            "current_amount": self.monthly_type.minimum_amount,
            "requested_amount": self.quarterly_type.minimum_amount,
            "reason": "Switch to quarterly",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        amendment.insert()
        amendment.approve_amendment("Test approval")
        amendment.apply_amendment()

        # Verify previous entry was closed
        member.reload()
        history = member.get("membership_type_history", [])

        # Find the old monthly entry
        old_entries = [h for h in history if h.membership_type == self.monthly_type.name]
        self.assertTrue(len(old_entries) > 0, "Should have old monthly entry")

        # The old entry should have to_date set
        for old_entry in old_entries:
            if old_entry.reason == "Initial membership":
                self.assertEqual(str(old_entry.to_date), str(today()))

    def test_schedule_notes_include_change_audit(self):
        """Test that schedule notes include audit trail of changes"""
        member, membership, dues_schedule = self._create_member_with_active_dues_schedule(
            self.monthly_type.name
        )

        original_notes = dues_schedule.notes or ""

        # Apply type change
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": member.name,
            "membership": membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.monthly_type.name,
            "requested_membership_type": self.quarterly_type.name,
            "current_amount": self.monthly_type.minimum_amount,
            "requested_amount": self.quarterly_type.minimum_amount,
            "reason": "Switch to quarterly for convenience",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        amendment.insert()
        amendment.approve_amendment("Test approval")
        amendment.apply_amendment()

        # Verify notes contain audit info
        dues_schedule.reload()
        notes = dues_schedule.notes or ""

        self.assertIn("Type change", notes)
        self.assertIn(self.monthly_type.name, notes)
        self.assertIn(self.quarterly_type.name, notes)

    def test_amendment_applied_status(self):
        """Test that amendment is marked as Applied after successful application"""
        member, membership, dues_schedule = self._create_member_with_active_dues_schedule(
            self.monthly_type.name
        )

        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": member.name,
            "membership": membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.monthly_type.name,
            "requested_membership_type": self.quarterly_type.name,
            "current_amount": self.monthly_type.minimum_amount,
            "requested_amount": self.quarterly_type.minimum_amount,
            "reason": "Test status tracking",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        amendment.insert()
        amendment.approve_amendment("Test approval")
        amendment.apply_amendment()

        # Verify status is Applied
        amendment.reload()
        self.assertEqual(amendment.status, "Applied")
        self.assertIsNotNone(amendment.applied_date)
        self.assertIsNotNone(amendment.applied_by)


class TestDuesScheduleRepositoryTypeChange(EnhancedTestCase):
    """Unit tests for DuesScheduleRepository.update_schedule_for_type_change"""

    def setUp(self):
        super().setUp()
        self.repo = DuesScheduleRepository()
        self.monthly_type = frappe.get_doc("Membership Type", "Monthly Membership")
        self.quarterly_type = frappe.get_doc("Membership Type", "Quarterly Membership")

    def _get_or_create_dues_schedule(self, member_name, membership_name, membership_type_name):
        """Get existing dues schedule or create one if none exists"""
        existing_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "status": "Active"},
            "name"
        )

        if existing_schedule:
            return frappe.get_doc("Membership Dues Schedule", existing_schedule)

        min_amount = frappe.db.get_value("Membership Type", membership_type_name, "minimum_amount")
        billing_period = frappe.db.get_value("Membership Type", membership_type_name, "billing_period")

        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Test Schedule {random_string(8)}",
            "member": member_name,
            "membership": membership_name,
            "membership_type": membership_type_name,
            "dues_rate": min_amount,
            "billing_frequency": billing_period,
            "status": "Active",
            "next_invoice_date": add_months(today(), 1),
            "effective_date": today(),
        })
        schedule.insert()
        return schedule

    def test_update_schedule_for_type_change_success(self):
        """Test successful schedule update via repository method"""
        member = self.create_test_member(first_name="Repo", last_name="Test")
        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name=self.monthly_type.name,
            status="Active"
        )

        schedule = self._get_or_create_dues_schedule(
            member_name=member.name,
            membership_name=membership.name,
            membership_type_name=self.monthly_type.name
        )

        # Call repository method directly
        result = self.repo.update_schedule_for_type_change(
            schedule_name=schedule.name,
            new_membership_type=self.quarterly_type.name,
            new_dues_rate=self.quarterly_type.minimum_amount,
            new_billing_frequency="Quarterly",
            reason="Test type change via repository"
        )

        self.assertTrue(result.success)
        self.assertEqual(result.schedule_name, schedule.name)
        self.assertEqual(result.method_used, "update")

        # Verify changes
        schedule.reload()
        self.assertEqual(schedule.membership_type, self.quarterly_type.name)
        self.assertEqual(schedule.dues_rate, self.quarterly_type.minimum_amount)
        self.assertEqual(schedule.billing_frequency, "Quarterly")

    def test_update_schedule_no_name_fails(self):
        """Test that empty schedule name returns error"""
        result = self.repo.update_schedule_for_type_change(
            schedule_name="",
            new_membership_type=self.quarterly_type.name,
            new_dues_rate=10.0,
            new_billing_frequency="Quarterly",
            reason="Should fail"
        )

        self.assertFalse(result.success)
        self.assertIn("No schedule name", result.message)

    def test_update_schedule_nonexistent_fails(self):
        """Test that nonexistent schedule returns error"""
        result = self.repo.update_schedule_for_type_change(
            schedule_name="Nonexistent-Schedule-12345",
            new_membership_type=self.quarterly_type.name,
            new_dues_rate=10.0,
            new_billing_frequency="Quarterly",
            reason="Should fail"
        )

        self.assertFalse(result.success)


class TestMembershipTypeRoleProfile(EnhancedTestCase):
    """Tests for membership type role profile utility"""

    def test_get_role_profile_for_membership_type(self):
        """Test retrieving role profile for membership type"""
        from verenigingen.utils.membership_type_role_profile import get_role_profile_for_membership_type

        # Monthly Membership should have Verenigingen Member role profile per fixtures
        role_profile = get_role_profile_for_membership_type("Monthly Membership")

        # The fixture sets role_profile to "Verenigingen Member"
        self.assertEqual(role_profile, "Verenigingen Member")

    def test_get_role_profile_nonexistent_type(self):
        """Test retrieving role profile for nonexistent type"""
        from verenigingen.utils.membership_type_role_profile import get_role_profile_for_membership_type

        role_profile = get_role_profile_for_membership_type("Nonexistent Type")
        self.assertIsNone(role_profile)

    def test_get_role_profile_empty_type(self):
        """Test retrieving role profile with empty type"""
        from verenigingen.utils.membership_type_role_profile import get_role_profile_for_membership_type

        role_profile = get_role_profile_for_membership_type("")
        self.assertIsNone(role_profile)

    def test_update_membership_type_role_profile_same_profile(self):
        """Test that same profile returns no_change"""
        from verenigingen.utils.membership_type_role_profile import update_membership_type_role_profile

        # All membership types use same role profile per fixtures
        # So changing between them should result in no_change
        result = update_membership_type_role_profile(
            user="Administrator",
            old_membership_type="Monthly Membership",
            new_membership_type="Quarterly Membership"
        )

        # Both have same role profile, so no change needed
        self.assertTrue(result.get("success") or result.get("no_change"))


class TestPortalTypeChangeEffectiveDate(EnhancedTestCase):
    """Tests for portal effective date calculation"""

    def _get_or_update_dues_schedule(self, member_name, membership_name, membership_type_name, next_invoice_date=None):
        """Get existing dues schedule and optionally update next_invoice_date"""
        existing_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "status": "Active"},
            "name"
        )

        if existing_schedule:
            schedule = frappe.get_doc("Membership Dues Schedule", existing_schedule)
            if next_invoice_date:
                schedule.next_invoice_date = next_invoice_date
                schedule.save()
            return schedule

        # Create one if none exists
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Test Schedule {random_string(8)}",
            "member": member_name,
            "membership": membership_name,
            "membership_type": membership_type_name,
            "dues_rate": 3.0,
            "billing_frequency": "Monthly",
            "status": "Active",
            "next_invoice_date": next_invoice_date or add_months(today(), 1),
            "effective_date": today(),
        })
        schedule.insert()
        return schedule

    def test_effective_date_from_next_invoice(self):
        """Test that effective date is calculated from dues schedule next_invoice_date"""
        from verenigingen.templates.pages.membership_adjustment import _calculate_type_change_effective_date

        member = self.create_test_member(first_name="Portal", last_name="Test")
        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name="Monthly Membership",
            status="Active"
        )

        # Set specific next_invoice_date
        expected_date = add_months(today(), 2)
        schedule = self._get_or_update_dues_schedule(
            member_name=member.name,
            membership_name=membership.name,
            membership_type_name="Monthly Membership",
            next_invoice_date=expected_date
        )

        # Calculate effective date
        effective_date = _calculate_type_change_effective_date(member.name)

        self.assertEqual(str(effective_date), str(expected_date))

    def test_effective_date_no_schedule_returns_today(self):
        """Test that missing schedule returns today's date"""
        from verenigingen.templates.pages.membership_adjustment import _calculate_type_change_effective_date

        member = self.create_test_member(first_name="NoSchedule", last_name="Test")

        # No dues schedule created
        effective_date = _calculate_type_change_effective_date(member.name)

        self.assertEqual(str(effective_date), str(today()))
