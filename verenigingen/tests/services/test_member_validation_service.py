# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Integration tests for member_validation_service (orchestrator).

Covers execute_validation end-to-end on real Member docs plus the conditional
branches: application-status clearing rules, status-sync skip flag, and duration
update gating.
"""

import unittest

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.services.member.validation.member_validation_service import (
    MemberValidationService,
    get_member_validation_service,
)


class TestExecuteValidation(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = MemberValidationService()

    def test_validation_succeeds_on_real_member(self):
        """A well-formed member passes the full validation orchestration."""
        member = self.create_test_member(
            first_name="Valid",
            last_name="Member",
            email="valid.member@example.com",
            birth_date="1985-05-05",
        )
        result = self.service.execute_validation(member)
        self.assertTrue(result.success)
        # All six validation slots present
        for key in (
            "core_fields",
            "duration",
            "payment",
            "member_id",
            "status_sync",
            "application_status",
        ):
            self.assertIn(key, result.data)

    def test_singleton_accessor(self):
        a = get_member_validation_service()
        b = get_member_validation_service()
        self.assertIs(a, b)


class TestClearApplicationStatus(EnhancedTestCase):
    """_clear_application_status_if_needed branch coverage."""

    def setUp(self):
        super().setUp()
        self.service = MemberValidationService()

    def _doc(self, status, app_status, ignore=False):
        return frappe._dict(
            status=status,
            application_status=app_status,
            flags=frappe._dict(ignore_status_validation=ignore),
        )

    def test_clears_when_active_and_workflow_app_status(self):
        doc = self._doc("Active", "Approved")
        result = self.service._clear_application_status_if_needed(doc)
        self.assertTrue(result["cleared"])
        self.assertIsNone(doc.application_status)

    def test_does_not_clear_when_pending(self):
        doc = self._doc("Pending", "Pending")
        result = self.service._clear_application_status_if_needed(doc)
        self.assertFalse(result["cleared"])
        self.assertEqual(doc.application_status, "Pending")

    def test_does_not_clear_when_rejected(self):
        doc = self._doc("Rejected", "Rejected")
        result = self.service._clear_application_status_if_needed(doc)
        self.assertFalse(result["cleared"])

    def test_skips_when_ignore_flag_set(self):
        doc = self._doc("Active", "Approved", ignore=True)
        result = self.service._clear_application_status_if_needed(doc)
        self.assertFalse(result["cleared"])
        self.assertEqual(result["reason"], "ignore_status_validation")
        # application_status preserved
        self.assertEqual(doc.application_status, "Approved")

    def test_no_clear_when_app_status_not_workflow(self):
        doc = self._doc("Active", "Terminated")
        result = self.service._clear_application_status_if_needed(doc)
        self.assertFalse(result["cleared"])
        self.assertEqual(result["reason"], "conditions_not_met")


class TestSyncStatusSkipFlag(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = MemberValidationService()

    def test_sync_skipped_when_flag_set(self):
        member = self.create_test_member(
            first_name="Sync",
            last_name="Skip",
            email="sync.skip@example.com",
        )
        member.flags.ignore_status_validation = True
        result = self.service._sync_status_fields_if_needed(member)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "ignore_status_validation")

    def test_sync_runs_when_flag_absent(self):
        member = self.create_test_member(
            first_name="Sync",
            last_name="Run",
            email="sync.run@example.com",
        )
        member.flags.ignore_status_validation = False
        result = self.service._sync_status_fields_if_needed(member)
        self.assertTrue(result["synced"])


class TestDurationUpdateGating(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = MemberValidationService()

    def test_duration_not_updated_for_existing_unflagged_member(self):
        """A persisted member without the force flag skips duration recompute."""
        member = self.create_test_member(
            first_name="Dur",
            last_name="Gate",
            email="dur.gate@example.com",
        )
        member.reload()  # no longer new
        result = self.service._update_duration_if_needed(member)
        self.assertFalse(result["updated"])
        self.assertEqual(result["reason"], "not_needed")

    def test_duration_updated_when_forced(self):
        member = self.create_test_member(
            first_name="Dur",
            last_name="Forced",
            email="dur.forced@example.com",
        )
        member.reload()
        member._force_duration_update = True
        result = self.service._update_duration_if_needed(member)
        self.assertTrue(result["updated"])


if __name__ == "__main__":
    unittest.main()
