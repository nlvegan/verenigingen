# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Real-DB coverage tests for MemberFeeChangeHistoryService.

The existing test_member_fee_change_history_service.py focuses on the billing
frequency validation helper using mocks. This module exercises the two public
methods against a real Member document, pinning:

- add_fee_change_to_history: append new entry, update existing by schedule,
  match/update by amendment_request, billing-frequency normalization
- update_fee_change_in_history: update existing entry in place; add when the
  schedule is not yet present (and when history is empty)
"""

import frappe

from verenigingen.services.member.history.member_fee_change_history_service import (
    MemberFeeChangeHistoryService,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberFeeChangeHistoryServiceRealDB(EnhancedTestCase):
    """Exercise fee-change-history mutation against a real Member."""

    def setUp(self):
        super().setUp()
        self.service = MemberFeeChangeHistoryService()
        self.member = self.create_test_member(first_name="Fee", last_name="History")

    def _rows(self):
        return self.member.fee_change_history or []

    # ----- add_fee_change_to_history -----

    def test_add_appends_new_entry(self):
        """A first add appends a single entry with the supplied values."""
        self.service.add_fee_change_to_history(
            self.member,
            {
                "name": "DUES-SCHED-A",
                "schedule_name": "Schedule A",
                "dues_rate": 25.0,
                "billing_frequency": "Monthly",
                "change_type": "Schedule Created",
            },
        )
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].dues_schedule, "DUES-SCHED-A")
        self.assertEqual(rows[0].new_dues_rate, 25.0)
        self.assertEqual(rows[0].billing_frequency, "Monthly")

    def test_add_updates_existing_entry_for_same_schedule(self):
        """Re-adding the same schedule updates the existing row instead of duplicating."""
        payload = {
            "name": "DUES-SCHED-B",
            "dues_rate": 10.0,
            "billing_frequency": "Monthly",
        }
        self.service.add_fee_change_to_history(self.member, payload)
        # Same schedule, new rate.
        self.service.add_fee_change_to_history(
            self.member,
            {"name": "DUES-SCHED-B", "dues_rate": 30.0, "billing_frequency": "Annual"},
        )
        rows = [r for r in self._rows() if r.dues_schedule == "DUES-SCHED-B"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].new_dues_rate, 30.0)
        self.assertEqual(rows[0].billing_frequency, "Annual")

    def test_add_invalid_billing_frequency_normalized_to_custom(self):
        """An unsupported billing frequency is stored as 'Custom'."""
        self.service.add_fee_change_to_history(
            self.member,
            {"name": "DUES-SCHED-C", "dues_rate": 5.0, "billing_frequency": "Fortnightly"},
        )
        row = [r for r in self._rows() if r.dues_schedule == "DUES-SCHED-C"][0]
        self.assertEqual(row.billing_frequency, "Custom")

    def test_add_matches_existing_by_amendment_request(self):
        """An entry carrying an amendment_request is matched/updated by that key."""
        self.service.add_fee_change_to_history(
            self.member,
            {
                "amendment_request": "AMEND-001",
                "dues_rate": 12.0,
                "billing_frequency": "Monthly",
                "change_type": "Fee Adjustment",
            },
        )
        # Second add with the same amendment_request should update, not append.
        self.service.add_fee_change_to_history(
            self.member,
            {
                "amendment_request": "AMEND-001",
                "dues_rate": 18.0,
                "billing_frequency": "Monthly",
                "change_type": "Fee Adjustment",
            },
        )
        rows = [r for r in self._rows() if r.amendment_request == "AMEND-001"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].new_dues_rate, 18.0)

    # ----- update_fee_change_in_history -----

    def test_update_when_history_empty_adds_entry(self):
        """Updating with no existing history falls back to an add."""
        self.assertEqual(len(self._rows()), 0)
        self.service.update_fee_change_in_history(
            self.member,
            {"name": "DUES-SCHED-D", "dues_rate": 40.0, "billing_frequency": "Monthly"},
        )
        rows = [r for r in self._rows() if r.dues_schedule == "DUES-SCHED-D"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].new_dues_rate, 40.0)

    def test_update_not_found_adds_new_entry(self):
        """When history exists but lacks the schedule, update falls through to add.

        Seed history with one schedule (add path, no save), then update for a
        DIFFERENT schedule: the 'not found' branch routes to add_fee_change_to_history,
        leaving both entries in memory.
        """
        self.service.add_fee_change_to_history(
            self.member,
            {"name": "DUES-SCHED-F1", "dues_rate": 10.0, "billing_frequency": "Monthly"},
        )
        self.service.update_fee_change_in_history(
            self.member,
            {"name": "DUES-SCHED-F2", "dues_rate": 22.0, "billing_frequency": "Monthly"},
        )
        schedules = {r.dues_schedule for r in self._rows()}
        self.assertIn("DUES-SCHED-F1", schedules)
        self.assertIn("DUES-SCHED-F2", schedules)

    def _member_with_real_schedule(self):
        """Create a member that owns a REAL Membership Dues Schedule.

        The fee_change_history.dues_schedule field is a Link to Membership Dues
        Schedule, so persisting the member (outside the link-validation bypass)
        requires a real target row to exist. create_test_member_with_schedule
        builds the membership + schedule end-to-end.
        """
        membership_type = self.create_test_membership_type(amount=10.0)
        member, schedule = self.create_test_member_with_schedule(
            first_name="FeeUpd",
            last_name="Real",
            membership_type_name=membership_type.name,
            start_date=frappe.utils.today(),
        )
        return member, schedule.name

    def test_update_found_persists_via_secure_operation(self):
        """The 'found' branch mutates the matched row and saves via secure_document_operation.

        Seed a persisted row referencing a REAL dues schedule (add + member.save),
        then update the SAME schedule. The found branch updates fields in place and
        persists them through secure_document_operation, so a reload shows the new rate.
        """
        member, schedule_name = self._member_with_real_schedule()
        self.service.add_fee_change_to_history(
            member,
            {"name": schedule_name, "dues_rate": 10.0, "billing_frequency": "Monthly"},
        )
        member.save()
        member.reload()

        self.service.update_fee_change_in_history(
            member,
            {
                "name": schedule_name,
                "dues_rate": 33.0,
                "billing_frequency": "Annual",
                "reason": "Rate bump",
            },
        )

        fresh = frappe.get_doc("Member", member.name)
        rows = [r for r in (fresh.fee_change_history or []) if r.dues_schedule == schedule_name]
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0].new_dues_rate), 33.0)
        self.assertEqual(rows[0].billing_frequency, "Annual")
        self.assertEqual(rows[0].reason, "Rate bump")

    def test_update_found_default_reason_when_missing(self):
        """When no reason is supplied, the found branch backfills 'Updated: <schedule>'."""
        member, schedule_name = self._member_with_real_schedule()
        self.service.add_fee_change_to_history(
            member,
            {"name": schedule_name, "dues_rate": 10.0, "billing_frequency": "Monthly"},
        )
        member.save()
        member.reload()

        self.service.update_fee_change_in_history(
            member,
            {"name": schedule_name, "dues_rate": 14.0, "billing_frequency": "Monthly"},
        )
        fresh = frappe.get_doc("Member", member.name)
        rows = [r for r in (fresh.fee_change_history or []) if r.dues_schedule == schedule_name]
        self.assertEqual(rows[0].reason, f"Updated: {schedule_name}")

    def test_add_truncates_history_to_50_entries(self):
        """Adding past 50 unique schedules truncates the child table to 50 rows."""
        for i in range(55):
            self.service.add_fee_change_to_history(
                self.member,
                {"name": f"DUES-SCHED-LIMIT-{i:03d}", "dues_rate": float(i), "billing_frequency": "Monthly"},
            )
        self.assertLessEqual(len(self._rows()), 50)

    def test_add_default_reason_from_schedule_name(self):
        """With no explicit reason, add composes 'Dues schedule: <name>'."""
        self.service.add_fee_change_to_history(
            self.member,
            {"schedule_name": "Gold Plan", "dues_rate": 9.0, "billing_frequency": "Monthly"},
        )
        rows = [r for r in self._rows() if r.dues_schedule == "Gold Plan"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].reason, "Dues schedule: Gold Plan")
