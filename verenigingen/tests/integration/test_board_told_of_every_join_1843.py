"""#1843: the chapter board is told about EVERY real join, exactly once.

A real join is a Chapter Member row that becomes enabled + Active for an Active member: a new row
(add_member), a re-enabled row (rejoin) and a Pending row activated at application approval. The single
trigger is Chapter.on_update -> MemberManager.notify_board_of_joins, which diffs the saved table.

The spy wraps CommunicationManager.notify_board_of_member_joined and calls through, recording
(chapter, member, returned). Approval is the real flow (submit -> confirm -> approve_application); the
rejoin is the real remove_member(permanent=False) + add_member. PROBE SHORTCUTS, stated: the "enabled row of a
Suspended member" control sets Member.status with db.set_value before a direct append + save, standing in
for a member suspended after their row was written.
"""

from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.integration.test_application_record_approval import ApprovalCase
from verenigingen.verenigingen.doctype.chapter.managers.communication_manager import CommunicationManager
from verenigingen.verenigingen.doctype.chapter.managers.member_manager import MemberManager

SETTING = "send_chapter_assignment_notifications"


class TestBoardToldOfEveryJoin(ApprovalCase):
    def setUp(self):
        super().setUp()
        self._orig_setting = frappe.db.get_single_value("Verenigingen Settings", SETTING)
        frappe.db.set_single_value("Verenigingen Settings", SETTING, 1)
        frappe.flags.is_bulk_import = False
        frappe.flags.suppress_chapter_notifications = False
        self.calls = []
        original = CommunicationManager.notify_board_of_member_joined

        def spy(manager, member_id):
            result = original(manager, member_id)
            self.calls.append((manager.chapter_name, member_id, result))
            return result

        patcher = patch.object(CommunicationManager, "notify_board_of_member_joined", autospec=True, side_effect=spy)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        frappe.db.set_single_value("Verenigingen Settings", SETTING, self._orig_setting)
        super().tearDown()

    def _joins(self, member):
        return [c for c in self.calls if c[0] == self.chapter.name and c[1] == member]

    def _chapter_manager(self):
        return MemberManager(frappe.get_doc("Chapter", self.chapter.name))

    def _approved_member(self):
        name = self._stage_and_confirm()
        self.assertTrue(self._approve_as(name)["success"])
        member = frappe.db.get_value("Member", {"email": self.email}, "name")
        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Active", "premise")
        return member

    def test_approval_tells_the_board_once(self):
        member = self._approved_member()
        row = frappe.db.get_value(
            "Chapter Member", {"parent": self.chapter.name, "member": member}, ["status", "enabled"], as_dict=True
        )
        self.assertEqual((row.status, row.enabled), ("Active", 1), "premise: the Pending row was activated")
        self.assertEqual(len(self._joins(member)), 1, self.calls)

    def test_rejoin_tells_the_board_again(self):
        member = self._approved_member()
        manager = self._chapter_manager()
        manager.remove_member(member, leave_reason="test", permanent=False, notify=False)
        self.assertEqual(frappe.db.get_value("Chapter Member", {"parent": self.chapter.name, "member": member}, "enabled"), 0)
        self.assertEqual(len(self._joins(member)), 1, "leaving is not a join")

        result = self._chapter_manager().add_member(member, notify=False)

        self.assertEqual(result["action"], "re-enabled", result)
        self.assertEqual(len(self._joins(member)), 2, self.calls)

    def test_new_row_for_active_member_tells_the_board_exactly_once(self):
        member = self.create_test_member(email=self.email, status="Active").name

        result = self._chapter_manager().add_member(member, notify=True)

        self.assertEqual(result["action"], "added", result)
        self.assertEqual(len(self._joins(member)), 1, "no second mail from add_member itself")

    def test_direct_append_for_active_member_tells_the_board(self):
        member = self.create_test_member(email=self.email, status="Active").name
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.append("members", {"member": member, "enabled": 1, "status": "Active", "chapter_join_date": today()})
        chapter.save()
        self.assertEqual(len(self._joins(member)), 1, self.calls)

    def test_resaving_an_already_enabled_row_is_not_a_join(self):
        member = self.create_test_member(email=self.email, status="Active").name
        self._chapter_manager().add_member(member, notify=False)
        self.assertEqual(len(self._joins(member)), 1, "premise")
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.members[-1].introduction = "edited"
        chapter.save()
        self.assertEqual(len(self._joins(member)), 1, "a re-save must not mail again")

    def test_pending_row_is_not_a_join(self):
        """Control with a real row: a Pending (enabled) row for an Active member waits for approval."""
        member = self.create_test_member(email=self.email, status="Active").name
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.append("members", {"member": member, "enabled": 1, "status": "Pending", "chapter_join_date": today()})
        chapter.save()
        self.assertTrue(frappe.db.exists("Chapter Member", {"parent": chapter.name, "member": member, "status": "Pending"}))
        self.assertEqual(self._joins(member), [])

    def test_enabled_row_of_a_non_active_member_is_not_a_join(self):
        member = self.create_test_member(email=self.email, status="Active").name
        frappe.db.set_value("Member", member, "status", "Suspended")  # probe shortcut, see docstring
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.append("members", {"member": member, "enabled": 1, "status": "Active", "chapter_join_date": today()})
        chapter.save()
        self.assertTrue(frappe.db.exists("Chapter Member", {"parent": chapter.name, "member": member, "enabled": 1}))
        self.assertEqual(self._joins(member), [])

    def test_disabled_row_of_a_suspended_member_is_not_a_join(self):
        member = self.create_test_member(email=self.email, status="Suspended").name
        self._chapter_manager().add_member(member, notify=False)
        self.assertEqual(frappe.db.get_value("Chapter Member", {"parent": self.chapter.name, "member": member}, "enabled"), 0)
        self.assertEqual(self._joins(member), [])

    def test_setting_off_sends_nothing_through_approval(self):
        frappe.db.set_single_value("Verenigingen Settings", SETTING, 0)
        member = self._approved_member()
        joins = self._joins(member)
        self.assertEqual(len(joins), 1, "the trigger still runs; the existing gate decides")
        self.assertFalse(joins[0][2], "setting off: nothing is dispatched")

    def test_seating_a_board_member_is_not_a_join(self):
        """Seating auto-adds the volunteer's Member row (board_manager); that is not announced."""
        volunteer = self.factory.create_volunteer(email=f"seat.{frappe.generate_hash(length=6)}@example.org")
        member = volunteer.member
        self.assertTrue(member, "premise: the volunteer has a Member")
        role = frappe.get_all("Chapter Role", pluck="name", limit=1)[0]
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "volunteer_name": volunteer.volunteer_name,
                "email": volunteer.email,
                "is_active": 1,
                "chapter_role": role,
                "from_date": today(),
            },
        )
        chapter.save()
        self.assertTrue(
            frappe.db.exists("Chapter Member", {"parent": chapter.name, "member": member, "enabled": 1}),
            "premise: seating wrote an enabled Member row",
        )
        self.assertEqual(self._joins(member), [])
