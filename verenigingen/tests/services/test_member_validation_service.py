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
        # All five validation slots present
        for key in (
            "core_fields",
            "duration",
            "payment",
            "member_id",
            "status_sync",
        ):
            self.assertIn(key, result.data)

    def test_execute_validation_propagates_core_field_error(self):
        """A core-field validation failure must propagate (block the save).

        _validate_core_fields catches and re-raises delegated validation errors
        so they surface out of execute_validation. Here an invalid last-name
        character makes validate_member_name_fields throw; the orchestrator must
        NOT swallow it into a success/failure result but let it propagate, or an
        invalid member could be persisted silently.
        """
        member = self.create_test_member(
            first_name="Prop",
            last_name="Agate",
            email="prop.agate@example.com",
            birth_date="1985-05-05",
        )
        # Inject an invalid character in-memory (not saved) — validate_name
        # rejects '!' as it is outside the allowed name pattern.
        member.last_name = "Bad!Name"
        with self.assertRaises(frappe.ValidationError):
            self.service.execute_validation(member)

    def test_singleton_accessor(self):
        a = get_member_validation_service()
        b = get_member_validation_service()
        self.assertIs(a, b)


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
