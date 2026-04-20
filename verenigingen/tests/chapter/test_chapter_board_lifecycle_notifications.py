"""Integration tests for chapter board member-lifecycle notifications."""

import frappe

from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChapterBoardLifecycleNotifications(EnhancedTestCase):
    """Verify chapter boards get notified on member join/leave/transfer."""

    def setUp(self):
        super().setUp()
        # Ensure the feature setting is on for tests
        frappe.db.set_single_value(
            "Verenigingen Settings", "send_chapter_assignment_notifications", 1
        )
        # Clear any stale flags from other tests
        frappe.flags.chapter_transfer = None
        frappe.flags.is_bulk_import = False
        frappe.flags.suppress_chapter_notifications = False
        # Clear the Email Queue so assertions only see this test's emails
        frappe.db.delete("Email Queue")
        frappe.db.commit()

    def tearDown(self):
        frappe.flags.chapter_transfer = None
        super().tearDown()

    def test_transfer_sets_and_clears_flag(self):
        """transfer_member_between_chapters sets chapter_transfer flag and clears it after."""
        member = self.factory.create_member()
        chapter_a = self.factory.create_chapter()
        chapter_b = self.factory.create_chapter()
        # Pre-assign to chapter A (bypass notifications during setup)
        frappe.flags.suppress_chapter_notifications = True
        ChapterMembershipManager.assign_member_to_chapter(member.name, chapter_a.name)
        frappe.flags.suppress_chapter_notifications = False

        captured = {}
        original = ChapterMembershipManager.assign_member_to_chapter

        def wrapped(member_id, chapter_name, **kw):
            captured["flag_during"] = dict(frappe.flags.get("chapter_transfer") or {})
            return original(member_id, chapter_name, **kw)

        ChapterMembershipManager.assign_member_to_chapter = staticmethod(wrapped)
        try:
            ChapterMembershipManager.transfer_member_between_chapters(
                member.name, chapter_a.name, chapter_b.name
            )
        finally:
            ChapterMembershipManager.assign_member_to_chapter = staticmethod(original)

        self.assertEqual(captured["flag_during"].get("member"), member.name)
        self.assertEqual(captured["flag_during"].get("from"), chapter_a.name)
        self.assertEqual(captured["flag_during"].get("to"), chapter_b.name)
        # Flag cleared afterwards
        self.assertIsNone(frappe.flags.get("chapter_transfer"))

    def test_transfer_clears_flag_on_failure(self):
        """Flag is cleared even when transfer goes through an error path."""
        member = self.factory.create_member()
        chapter_a = self.factory.create_chapter()

        frappe.flags.chapter_transfer = None
        # A nonexistent destination triggers the error path; the wrapper's finally
        # must still clear the flag.
        ChapterMembershipManager.transfer_member_between_chapters(
            member.name, chapter_a.name, "Nonexistent-Chapter-" + frappe.generate_hash(length=6)
        )
        self.assertIsNone(frappe.flags.get("chapter_transfer"))
