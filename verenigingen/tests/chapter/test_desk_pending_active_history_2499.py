"""#2499: a Desk edit of a Chapter Member row from Pending to Active must move the member's
Chapter Membership History entry from Pending to Active (sibling of #2430, which fixed only
`approve_member_request`).

Flows are real: the applicant asks through `request_to_join` / `join_chapter`, and the "Desk edit"
is a real `Chapter.save()` after changing the child row's `status`, exactly what the form posts.
PROBE SHORTCUT: `test_reenable_beside_a_stale_pending_entry...` writes the stale Pending entry with a
direct child-row insert, because no real flow leaves a Pending entry beside a DISABLED row
(disabling ends the entry as Quit); it only proves the branch cannot silently refuse.
"""

import frappe
from frappe.utils import getdate, today

from verenigingen.services.member.approval.application_helpers import (
    activate_pending_chapter_membership,
    create_active_chapter_membership,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.chapter.chapter import join_chapter, leave_chapter


class TestDeskPendingActiveHistory2499(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"TEST 2499 Chapter {frappe.generate_hash()[:6]}", region="Test Region 2499"
        )
        email = f"dk2499-{frappe.generate_hash()[:8]}0@example.com"
        self.applicant = self.create_test_member(
            first_name="Dk", last_name="Applicant", email=email, birth_date="1990-01-01"
        )
        self.applicant.db_set("status", "Active")

    def _request_join_2499(self):
        manager = frappe.get_doc("Chapter", self.chapter.name).member_manager
        result = manager.request_to_join(self.applicant.name, notify=False)
        self.assertTrue(result["success"], result)

    def _desk_edit(self, **changes):
        """Edit the child row the way the Desk form does, then save the Chapter."""
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        row = next(m for m in chapter.members if m.member == self.applicant.name)
        for field, value in changes.items():
            setattr(row, field, value)
        chapter.save()
        return row

    def _entries_2499(self):
        return frappe.get_all(
            "Chapter Membership History",
            filters={
                "parent": self.applicant.name,
                "chapter_name": self.chapter.name,
                "assignment_type": "Member",
            },
            fields=["status", "start_date", "end_date", "reason"],
            order_by="idx asc",
        )

    def test_desk_pending_to_active_activates_the_history_entry(self):
        self._request_join_2499()
        self.assertEqual([h.status for h in self._entries_2499()], ["Pending"])

        self._desk_edit(status="Active")

        history = self._entries_2499()
        self.assertEqual([h.status for h in history], ["Active"], history)
        self.assertIsNone(history[0].end_date)

    def test_desk_activation_after_a_rejoin_keeps_the_earlier_period(self):
        self.add_member_to_test_chapter(self.applicant.name, self.chapter.name)
        self.assertTrue(leave_chapter(self.applicant.name, self.chapter.name, "moving")["removed"])
        self.assertTrue(join_chapter(self.applicant.name, self.chapter.name, "back")["success"])
        before = self._entries_2499()
        self.assertEqual(before[-1].status, "Pending", before)

        self._desk_edit(status="Active")

        after = self._entries_2499()
        self.assertEqual(len(after), len(before), after)
        self.assertEqual(after[-1].status, "Active", after)
        self.assertEqual([h.reason for h in after if h.status == "Quit"], ["moving"], after)

    def test_a_save_that_leaves_the_row_pending_keeps_the_entry_pending(self):
        """Control: an unrelated edit of a Pending row must not activate its entry."""
        self._request_join_2499()

        self._desk_edit(introduction="edited, still waiting")

        self.assertEqual([h.status for h in self._entries_2499()], ["Pending"])

    def test_desk_activation_of_a_row_with_no_history_records_one_active_entry(self):
        """Legacy: the request wrote no history; the edit must still leave exactly one Active entry."""
        self._request_join_2499()
        frappe.db.delete(
            "Chapter Membership History", {"parent": self.applicant.name, "chapter_name": self.chapter.name}
        )

        self._desk_edit(status="Active")

        self.assertEqual([h.status for h in self._entries_2499()], ["Active"])

    def test_reenable_beside_a_stale_pending_entry_does_not_leave_it_pending(self):
        """Probe: the row goes disabled Pending -> enabled Active in one save while a Pending entry sits
        in the history (written directly, see module docstring)."""
        self._request_join_2499()
        self._desk_edit(enabled=0)
        member = frappe.get_doc("Member", self.applicant.name)
        member.append(
            "chapter_membership_history",
            {
                "chapter_name": self.chapter.name,
                "assignment_type": "Member",
                "start_date": today(),
                "status": "Pending",
                "reason": "stale",
            },
        )
        member.save()

        self._desk_edit(enabled=1, status="Active")

        statuses = [h.status for h in self._entries_2499()]
        self.assertNotIn("Pending", statuses, statuses)
        self.assertIn("Active", statuses, statuses)

    def test_an_unrelated_edit_of_an_active_row_leaves_a_pending_entry_alone(self):
        """Control: the entry is only activated by a Pending -> Active transition of the ROW.
        PROBE SHORTCUT: the Pending entry beside an enabled Active row is written with db.set_value
        (no real flow leaves that state); it gives the always-True mutant a real row to wrongly touch."""
        self.add_member_to_test_chapter(self.applicant.name, self.chapter.name)
        entry = self._entries_2499_names()
        frappe.db.set_value("Chapter Membership History", entry[0], "status", "Pending")

        self._desk_edit(introduction="unrelated edit")

        self.assertEqual([h.status for h in self._entries_2499()], ["Pending"])

    def _entries_2499_names(self):
        return frappe.get_all(
            "Chapter Membership History",
            filters={"parent": self.applicant.name, "chapter_name": self.chapter.name},
            pluck="name",
            order_by="idx asc",
        )

    def test_a_writers_reason_does_not_label_a_later_row_on_the_same_chapter_object(self):
        other_email = f"dk2499-{frappe.generate_hash()[:8]}1@example.com"
        other = self.create_test_member(
            first_name="Dk", last_name="Other", email=other_email, birth_date="1990-01-01"
        )
        other.db_set("status", "Active")
        self._request_join_2499()
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        self.assertTrue(chapter.member_manager.request_to_join(other.name, notify=False)["success"])
        chapter = frappe.get_doc("Chapter", self.chapter.name)

        result = chapter.member_manager.approve_member_request(
            self.applicant.name, approved_by="approver-2499@example.com"
        )
        self.assertTrue(result["success"], result)
        row = next(m for m in chapter.members if m.member == other.name)
        row.status = "Active"
        chapter.save()

        mine = self._entries_2499()
        self.assertIn("approver-2499@example.com", mine[0].reason, mine)
        theirs = frappe.get_all(
            "Chapter Membership History",
            filters={"parent": other.name, "chapter_name": self.chapter.name},
            fields=["status", "reason"],
        )
        self.assertEqual([h.status for h in theirs], ["Active"], theirs)
        self.assertNotIn("approver-2499@example.com", theirs[0].reason, theirs)

    def test_create_active_chapter_membership_activates_an_existing_pending_entry(self):
        """The existing-row branch flips Pending -> Active on the row and never touched history."""
        self._request_join_2499()

        create_active_chapter_membership(self.applicant, self.chapter.name)

        self.assertEqual([h.status for h in self._entries_2499()], ["Active"])

    def test_application_approval_writes_its_own_reason_on_the_entry(self):
        self._request_join_2499()

        activate_pending_chapter_membership(self.applicant, self.chapter.name)

        entries = self._entries_2499()
        self.assertEqual([h.status for h in entries], ["Active"], entries)
        self.assertEqual(entries[0].reason, f"Membership application approved for {self.chapter.name} chapter")

    def test_approve_member_request_names_the_approver_in_the_reason(self):
        """approved_by differs from the session user (Administrator), so the assertion is not vacuous."""
        self._request_join_2499()
        chapter = frappe.get_doc("Chapter", self.chapter.name)

        result = chapter.member_manager.approve_member_request(
            self.applicant.name, approved_by="approver-2499@example.com"
        )

        self.assertTrue(result["success"], result)
        entries = self._entries_2499()
        self.assertEqual(entries[0].reason, "Membership approved by approver-2499@example.com")
