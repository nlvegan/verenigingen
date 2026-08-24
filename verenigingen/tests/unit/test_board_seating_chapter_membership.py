"""Seating a board member auto-adds them as a chapter member -- and that must be
recorded in ``Member.chapter_membership_history``.

``seat_board_members_as_chapter_members`` calls ``_add_to_chapter_members``, which
appends a row to ``chapter_doc.members``. The history for that row is not written there:
it is written by ``handle_member_additions``, which diffs ``chapter_doc.members`` against
``old_doc.members`` *when it runs*. So the two are coupled by ordering alone -- the
append has to happen before the diff, or the auto-added member gets a ``members`` row
with no history behind it. (Until #459 the append lived inside
``handle_board_member_additions``; it was split out precisely so that this coupling stops
depending on where the board group sits relative to the member group.)

Nothing asserted that coupling before this file. #459 proposed swapping the two handler
groups for lock-ordering reasons and 202 tests stayed green while this row went missing;
a green suite there was equally consistent with "the swap is neutral" and with "the
regression is uncovered". This is the test that tells those apart.

Independent of the lock ordering itself: the invariant is a behavioural one and holds
whatever order the acquisitions end up in.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestBoardSeatingWritesChapterMembershipHistory(VereningingenTestCase):
    def _history_for(self, member_name, chapter_name):
        member = frappe.get_doc("Member", member_name)
        return [h for h in (member.chapter_membership_history or []) if h.chapter_name == chapter_name]

    def test_seating_a_board_member_writes_chapter_membership_history(self):
        """The auto-added ``members`` row and its history row are one fact, not two."""
        chapter = self.create_test_chapter()
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member=member.name)
        role = self.create_test_chapter_role()

        # Precondition: the member is not in the chapter yet, and has no history for it.
        # Without this the assertions below could be satisfied by a row that predates
        # the save under test.
        doc = frappe.get_doc("Chapter", chapter.name)
        self.assertNotIn(
            member.name,
            [m.member for m in (doc.members or [])],
            "fixture is not a clean starting point: the member is already in the chapter",
        )
        self.assertEqual(
            self._history_for(member.name, chapter.name),
            [],
            "fixture is not a clean starting point: chapter_membership_history already has a row",
        )

        doc.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        doc.save()

        doc.reload()
        self.assertIn(
            member.name,
            [m.member for m in (doc.members or [])],
            "seating a board member should auto-add them to the chapter's members "
            "(_add_to_chapter_members)",
        )

        history = self._history_for(member.name, chapter.name)
        self.assertEqual(
            len(history),
            1,
            "the auto-added chapter member has no Chapter Membership History row: "
            f"got {[h.as_dict() for h in history]}. handle_member_additions diffs "
            "chapter_doc.members when it runs, so the board handler's append must "
            "happen before that diff, not after it (#459).",
        )
        self.assertEqual(history[0].assignment_type, "Member")
        self.assertEqual(history[0].status, "Active")
