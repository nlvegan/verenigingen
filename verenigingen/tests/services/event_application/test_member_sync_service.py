"""Real-DB integration tests for MijnRoodMemberSyncService.

find_existing_member_or_conflict is a pure DB lookup — exercised against
real Member rows created via the factory. apply_new_member and
apply_changed_member integrate against MijnRood Sync Event +
MemberImportService and use a stub orchestrator for the not-yet-extracted
cross-cutting helpers (create_related_records, process_member_roles,
try_promote_application, check_and_handle_termination,
handle_division_field_change).
"""

import frappe

from verenigingen.mijnrood_sync.services.event_application.member_sync_service import (
    get_member_sync_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFindExistingMemberOrConflict(EnhancedTestCase):
    """Lookup-by-member_id-then-email-then-conflict logic."""

    def test_returns_none_when_no_member_matches(self):
        result_name, result_dict = get_member_sync_service().find_existing_member_or_conflict(
            mijnrood_id="999999999", email="ghost-does-not-exist@example.org"
        )
        self.assertIsNone(result_name)
        self.assertIsNone(result_dict)

    def test_matches_by_member_id_first(self):
        member = self.factory.create_member(
            first_name="Bob",
            last_name="Example",
            email="bob-mid@example.org",
            member_id="MR-12345",
        )

        name, result = get_member_sync_service().find_existing_member_or_conflict(
            mijnrood_id="MR-12345", email="completely-different@example.org"
        )

        self.assertEqual(name, member.name)
        self.assertTrue(result["success"])
        self.assertIn("MR-12345", result["message"])

    def test_matches_by_email_when_member_id_absent(self):
        member = self.factory.create_member(
            first_name="Carol",
            last_name="Example",
            email="carol-email@example.org",
        )

        # EnhancedTestDataFactory uniquifies emails — use the stored value
        name, result = get_member_sync_service().find_existing_member_or_conflict(
            mijnrood_id=None, email=member.email
        )

        self.assertEqual(name, member.name)
        self.assertTrue(result["success"])

    def test_email_match_with_conflicting_member_id_returns_conflict(self):
        existing = self.factory.create_member(
            first_name="Dan",
            last_name="Example",
            email="dan-conflict@example.org",
            member_id="MR-AAA",
        )

        # EnhancedTestDataFactory uniquifies emails — use the stored value
        name, result = get_member_sync_service().find_existing_member_or_conflict(
            mijnrood_id="MR-BBB", email=existing.email
        )

        self.assertIsNone(name)
        self.assertFalse(result["success"])
        self.assertIn("MR-AAA", result["message"])
        self.assertIn("MR-BBB", result["message"])
