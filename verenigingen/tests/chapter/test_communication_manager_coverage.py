"""
Additional real-DB coverage for the chapter ``CommunicationManager``
(``verenigingen/verenigingen/doctype/chapter/managers/communication_manager.py``).

The base suite covers template lookup, notify_* guards, bulk/newsletter/statutory
sends and Communication-record creation. This file fills the board-lifecycle
notification surface (``notify_board_of_member_joined`` / ``notify_board_of_member_left``
/ the shared ``_dispatch_board_lifecycle_notification`` / the
``_board_lifecycle_notifications_enabled`` gate) plus a couple of remaining
helper branches. All Chapters/Members/Volunteers/Email Templates are created via
the real factory and run as Administrator.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestCommunicationManagerCoverage(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"CommCov Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        self.member = self.create_test_member(
            first_name="CommCov",
            last_name="Primary",
            email=f"commcov.primary.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        # Save/restore the lifecycle-notification setting around each test.
        self._orig_setting = frappe.db.get_single_value(
            "Verenigingen Settings", "send_chapter_assignment_notifications"
        )

    def tearDown(self):
        frappe.db.set_single_value(
            "Verenigingen Settings", "send_chapter_assignment_notifications", self._orig_setting
        )
        frappe.flags.pop("chapter_transfer", None)
        frappe.flags.is_bulk_import = False
        frappe.flags.suppress_chapter_notifications = False
        super().tearDown()

    @property
    def manager(self):
        return self.chapter.communication_manager

    def _reload(self):
        self.chapter = frappe.get_doc("Chapter", self.chapter.name)
        return self.chapter

    def _enable_notifications(self):
        frappe.db.set_single_value("Verenigingen Settings", "send_chapter_assignment_notifications", 1)

    def _make_template(self, name):
        if not frappe.db.exists("Email Template", name):
            tmpl = frappe.get_doc(
                {
                    "doctype": "Email Template",
                    "name": name,
                    "subject": f"{name} subject",
                    "response": "<p>{{ member_name }}</p>",
                    "use_html": 1,
                }
            ).insert()
            self.track_doc("Email Template", tmpl.name)

    def _seat_board_member(self, first="BoardCov"):
        member = self.create_test_member(
            first_name=first,
            last_name="CommCov",
            email=f"commcov.{first.lower()}.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        volunteer = self.create_test_volunteer(member=member.name)
        role_name = f"CommCovRole{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": role_name, "permissions_level": "Basic"}
        ).insert()
        self.track_doc("Chapter Role", role_name)
        self.add_board_member_to_chapter(self.chapter, volunteer, role_name, email=member.email)
        self._reload()
        return member, volunteer

    # ------------------------------------ _board_lifecycle_notifications_enabled

    def test_lifecycle_gate_off_when_setting_disabled(self):
        frappe.db.set_single_value("Verenigingen Settings", "send_chapter_assignment_notifications", 0)
        self.assertFalse(self.manager._board_lifecycle_notifications_enabled())

    def test_lifecycle_gate_on_when_setting_enabled(self):
        self._enable_notifications()
        self.assertTrue(self.manager._board_lifecycle_notifications_enabled())

    def test_lifecycle_gate_suppressed_by_bulk_import(self):
        self._enable_notifications()
        frappe.flags.is_bulk_import = True
        self.assertFalse(self.manager._board_lifecycle_notifications_enabled())

    def test_lifecycle_gate_suppressed_by_flag(self):
        self._enable_notifications()
        frappe.flags.suppress_chapter_notifications = True
        self.assertFalse(self.manager._board_lifecycle_notifications_enabled())

    # ------------------------------------ notify_board_of_member_joined / left

    def test_notify_board_of_member_joined_disabled_returns_false(self):
        frappe.db.set_single_value("Verenigingen Settings", "send_chapter_assignment_notifications", 0)
        self.assertFalse(self.manager.notify_board_of_member_joined(self.member.name))

    def test_notify_board_of_member_joined_no_board_returns_false(self):
        # Enabled, but the chapter has no active board members -> no recipients.
        self._enable_notifications()
        self.assertFalse(self.manager.notify_board_of_member_joined(self.member.name))

    def test_notify_board_of_member_joined_with_board_returns_true(self):
        self._enable_notifications()
        self._make_template("chapter_board_member_joined")
        self._seat_board_member(first="JoinBoard")
        result = self.chapter.communication_manager.notify_board_of_member_joined(self.member.name)
        self.assertTrue(result, "an active board member + enabled setting must queue a notification")

    def test_notify_board_of_member_joined_transfer_in_uses_transfer_template(self):
        self._enable_notifications()
        self._make_template("chapter_board_member_transferred_in")
        self._seat_board_member(first="TransferInBoard")
        frappe.flags.chapter_transfer = {
            "member": self.member.name,
            "to": self.chapter.name,
            "from": "Some Other Chapter",
        }
        result = self.chapter.communication_manager.notify_board_of_member_joined(self.member.name)
        self.assertTrue(result)

    def test_notify_board_of_member_left_with_board_returns_true(self):
        self._enable_notifications()
        self._make_template("chapter_board_member_left")
        self._seat_board_member(first="LeftBoard")
        result = self.chapter.communication_manager.notify_board_of_member_left(
            self.member.name, leave_reason="moved"
        )
        self.assertTrue(result)

    def test_notify_board_of_member_left_transfer_out_uses_transfer_template(self):
        self._enable_notifications()
        self._make_template("chapter_board_member_transferred_out")
        self._seat_board_member(first="TransferOutBoard")
        frappe.flags.chapter_transfer = {
            "member": self.member.name,
            "from": self.chapter.name,
            "to": "Destination Chapter",
        }
        result = self.chapter.communication_manager.notify_board_of_member_left(self.member.name)
        self.assertTrue(result)

    def test_notify_board_of_member_left_disabled_returns_false(self):
        frappe.db.set_single_value("Verenigingen Settings", "send_chapter_assignment_notifications", 0)
        self.assertFalse(self.manager.notify_board_of_member_left(self.member.name))

    # ------------------------------------ _dispatch dedupes recipients

    def test_dispatch_skips_inactive_board_rows(self):
        # An inactive board member should not receive a lifecycle notification;
        # with only an inactive seat present, dispatch finds no recipients.
        self._enable_notifications()
        self._make_template("chapter_board_member_joined")
        member, volunteer = self._seat_board_member(first="InactiveBoard")
        # Flip the seat inactive.
        self._reload()
        for row in self.chapter.board_members:
            if row.volunteer == volunteer.name:
                row.is_active = 0
        self.chapter.save()
        self._reload()
        result = self.chapter.communication_manager.notify_board_of_member_joined(self.member.name)
        self.assertFalse(result, "inactive-only board yields no recipients")

    # ------------------------------------ _load_email_settings / _validate

    def test_load_email_settings_returns_dict(self):
        # _load_email_settings runs at manager construction; assert the cached shape.
        self.assertIsInstance(self.manager.email_settings, dict)
