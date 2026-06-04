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
        # The EmailService skips sending (before reaching the patched frappe.sendmail) when
        # there is no active default-outgoing Email Account. Fresh test sites have none, so
        # ensure one exists; otherwise board-notification emails are never queued/captured.
        self._ensure_outgoing_email_account()
        # The EmailService also gates per-notification-type via Verenigingen Email
        # Configuration; ensure the board-lifecycle notification types are enabled.
        self._enable_chapter_notification_types()
        # Clear any stale flags from other tests
        frappe.flags.chapter_transfer = None
        frappe.flags.is_bulk_import = False
        frappe.flags.suppress_chapter_notifications = False
        # EnhancedTestCase._setup_email_mocking() patches frappe.sendmail so emails
        # are captured in self.captured_emails rather than hitting the DB.
        # Reset the capture list at the start of each test so assertions are clean.
        self.captured_emails = []

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

    # ------------------------------------------------------------------
    # Helpers for board-notification tests
    # ------------------------------------------------------------------

    def _ensure_outgoing_email_account(self):
        """Ensure an active default-outgoing Email Account exists for the send path."""
        existing = frappe.get_all(
            "Email Account",
            filters={"enable_outgoing": 1, "default_outgoing": 1},
            limit=1,
        )
        if existing:
            return
        frappe.get_doc({
            "doctype": "Email Account",
            "email_account_name": "Test Outgoing",
            "email_id": "test-outgoing@test.invalid",
            "enable_outgoing": 1,
            "default_outgoing": 1,
            "smtp_server": "localhost",
            "login_id_is_different": 0,
        }).insert(ignore_permissions=True)

    def _enable_chapter_notification_types(self):
        """Ensure the chapter board-lifecycle notification types exist and are enabled.

        EmailService gates each notification via Verenigingen Email Configuration's
        notification_types child table; a missing/disabled row blocks the email.
        """
        config = frappe.get_single("Verenigingen Email Configuration")
        wanted = {
            "chapter_member_joined": "Chapter Member Joined",
            "chapter_member_left": "Chapter Member Left",
        }
        existing = {nt.notification_key: nt for nt in config.notification_types}
        changed = False
        for key, label in wanted.items():
            if key in existing:
                if not existing[key].enabled:
                    existing[key].enabled = 1
                    changed = True
            else:
                config.append(
                    "notification_types",
                    {
                        "notification_key": key,
                        "label": label,
                        "category": "System",
                        "enabled": 1,
                    },
                )
                changed = True
        if changed:
            config.save(ignore_permissions=True)

    def _ensure_chapter_role(self):
        """Ensure a basic Chapter Role exists for board-member rows."""
        name = "Test Board Role"
        if not frappe.db.exists("Chapter Role", name):
            frappe.get_doc({
                "doctype": "Chapter Role",
                "role_name": name,
                "permissions_level": "Basic",
                "is_chair": 0,
                "is_unique": 0,
            }).insert(ignore_permissions=True)
        return name

    def _emails_sent_to(self, recipient_email):
        """Return list of subjects of emails sent to the given recipient.

        EnhancedTestCase patches ``frappe.sendmail`` so emails never reach the
        DB.  They are captured in ``self.captured_emails`` instead.  Use the
        ``get_sent_emails(to=...)`` helper to filter by recipient.
        """
        return [
            e.get("subject", "")
            for e in self.get_sent_emails(to=recipient_email)
        ]

    def _make_chapter_with_board(self, emails):
        """Create a chapter with active board members (one volunteer per email).

        Returns (chapter, [volunteer_docs]).  Each volunteer's email is taken
        from the Volunteer record (which may have been adjusted for uniqueness
        by the factory) — callers should use volunteer.email for assertions.
        """
        chapter = self.factory.create_chapter()
        role = self._ensure_chapter_role()
        volunteers = []
        for email in emails:
            # Create a volunteer with this email (factory may adjust for uniqueness)
            volunteer = self.factory.create_volunteer(email=email)
            chapter.append(
                "board_members",
                {
                    "volunteer": volunteer.name,
                    "volunteer_name": volunteer.volunteer_name,
                    "email": volunteer.email,
                    "is_active": 1,
                    "chapter_role": role,
                    "from_date": frappe.utils.today(),
                },
            )
            volunteers.append(volunteer)
        chapter.save()
        return chapter, volunteers

    # ------------------------------------------------------------------
    # Board-notification tests
    # ------------------------------------------------------------------

    def test_plain_join_notifies_board(self):
        """Adding a ChapterMember (no transfer flag) sends chapter_board_member_joined to the board."""
        chapter, volunteers = self._make_chapter_with_board(["board1@example.com", "board2@example.com"])
        member = self.factory.create_member()

        ChapterMembershipManager.assign_member_to_chapter(member.name, chapter.name, notify=True)

        # Use the actual volunteer emails (factory may have adjusted them)
        v1_email = volunteers[0].email
        v2_email = volunteers[1].email
        # Debug: print all captured emails to understand what was sent
        print(f"\nDEBUG: captured_emails count={len(self.captured_emails)}")
        for e in self.captured_emails:
            print(f"  subject={e.get('subject')!r} recipients={e.get('recipients')} to={e.get('to')}")
        subjects1 = self._emails_sent_to(v1_email)
        self.assertTrue(
            any(f"New member in {chapter.name}" in s for s in subjects1),
            f"Expected 'joined' email to {v1_email} in {subjects1}",
        )
        subjects2 = self._emails_sent_to(v2_email)
        self.assertTrue(
            any(f"New member in {chapter.name}" in s for s in subjects2),
            f"Expected 'joined' email to {v2_email} in {subjects2}",
        )

    def test_plain_leave_notifies_board(self):
        """Removing a ChapterMember (no transfer flag) sends chapter_board_member_left to the board."""
        chapter, volunteers = self._make_chapter_with_board(["bleft@example.com"])
        member = self.factory.create_member()
        frappe.flags.suppress_chapter_notifications = True
        ChapterMembershipManager.assign_member_to_chapter(member.name, chapter.name)
        frappe.flags.suppress_chapter_notifications = False
        frappe.db.delete("Email Queue")
        frappe.db.commit()

        ChapterMembershipManager.leave_chapter(member.name, chapter.name, leave_reason="Moving away")

        v_email = volunteers[0].email
        subjects = self._emails_sent_to(v_email)
        self.assertTrue(
            any(f"Member left {chapter.name}" in s for s in subjects),
            f"Expected 'left' email to {v_email} in {subjects}",
        )

    def test_setting_disabled_blocks_notification(self):
        """send_chapter_assignment_notifications=0 blocks emails even when notify=True."""
        frappe.db.set_single_value("Verenigingen Settings", "send_chapter_assignment_notifications", 0)
        chapter, volunteers = self._make_chapter_with_board(["setting@example.com"])
        member = self.factory.create_member()

        ChapterMembershipManager.assign_member_to_chapter(member.name, chapter.name, notify=True)

        self.assertEqual(self._emails_sent_to(volunteers[0].email), [])

    def test_bulk_import_flag_blocks_notification(self):
        """frappe.flags.is_bulk_import=True blocks board emails."""
        chapter, volunteers = self._make_chapter_with_board(["bulk@example.com"])
        member = self.factory.create_member()

        frappe.flags.is_bulk_import = True
        try:
            ChapterMembershipManager.assign_member_to_chapter(member.name, chapter.name, notify=True)
        finally:
            frappe.flags.is_bulk_import = False

        self.assertEqual(self._emails_sent_to(volunteers[0].email), [])

    def test_suppress_flag_blocks_notification(self):
        """frappe.flags.suppress_chapter_notifications=True blocks board emails."""
        chapter, volunteers = self._make_chapter_with_board(["supp@example.com"])
        member = self.factory.create_member()

        frappe.flags.suppress_chapter_notifications = True
        try:
            ChapterMembershipManager.assign_member_to_chapter(member.name, chapter.name)
        finally:
            frappe.flags.suppress_chapter_notifications = False

        self.assertEqual(self._emails_sent_to(volunteers[0].email), [])

    def test_inactive_board_members_not_notified(self):
        """Only is_active=1 board rows receive the email."""
        chapter = self.factory.create_chapter()
        role = self._ensure_chapter_role()
        active_vol = self.factory.create_volunteer(email="active-bm@example.com")
        inactive_vol = self.factory.create_volunteer(email="inactive-bm@example.com")
        chapter.append("board_members", {
            "volunteer": active_vol.name,
            "volunteer_name": active_vol.volunteer_name,
            "email": active_vol.email,
            "is_active": 1,
            "chapter_role": role,
            "from_date": frappe.utils.today(),
        })
        chapter.append("board_members", {
            "volunteer": inactive_vol.name,
            "volunteer_name": inactive_vol.volunteer_name,
            "email": inactive_vol.email,
            "is_active": 0,
            "chapter_role": role,
            "from_date": frappe.utils.today(),
        })
        chapter.save()
        member = self.factory.create_member()

        ChapterMembershipManager.assign_member_to_chapter(member.name, chapter.name, notify=True)

        self.assertTrue(self._emails_sent_to(active_vol.email))
        self.assertFalse(self._emails_sent_to(inactive_vol.email))
