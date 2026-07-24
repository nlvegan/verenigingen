# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""
Integration test for api.member.financial_api.sync_member_dues_rate.

Member.dues_rate is a denormalized mirror of the authoritative Membership Dues
Schedule rate. sync_member_dues_rate re-copies the active schedule's rate onto
the member and flags the save as a system update (_system_update=True) so Member
validate skips fee-override permission/validation handling — the write is a
denormalization mirror, not a user fee override.
"""

import frappe

from verenigingen.api.member.financial_api import sync_member_dues_rate
from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSyncMemberDuesRate(EnhancedTestCase):
    def test_sync_copies_active_schedule_rate_onto_member(self):
        """A stale Member.dues_rate is re-synced from the active dues schedule.

        The dues-schedule controller recomputes dues_rate from the membership
        type, so the authoritative rate is read from the same source the API
        uses (DuesScheduleRepository.get_active_schedule) rather than assumed.
        """
        member = self.create_test_member()
        self.create_test_membership(member=member.name)
        self.create_test_dues_schedule(member=member.name)

        schedule = DuesScheduleRepository().get_active_schedule(member.name, fields=["name", "dues_rate"])
        self.assertIsNotNone(schedule, "test setup should leave an active dues schedule")
        expected_rate = schedule.dues_rate

        # Corrupt the denormalized copy so it differs from the schedule rate.
        frappe.db.set_value("Member", member.name, "dues_rate", expected_rate + 13, update_modified=False)

        result = sync_member_dues_rate(member.name)

        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertEqual(result["dues_rate"], expected_rate)
        self.assertEqual(frappe.db.get_value("Member", member.name, "dues_rate"), expected_rate)

    def test_sync_reports_no_active_schedule(self):
        """With no active schedule, sync reports failure rather than raising."""
        member = self.create_test_member()

        result = sync_member_dues_rate(member.name)

        self.assertFalse(result["success"])
        self.assertIn("No active dues schedule", result["message"])
