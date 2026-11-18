"""Seating a board member must not stamp ``enabled=1, status='Active'`` on a new
Chapter Member row for a Member who is not Active (#1559).

Real flow: a real Chapter save with a new active ``board_members`` row runs
``BoardManager._add_to_chapter_members``. The Member status is set through
``create_test_member(status=...)`` (no direct row writes). The expected pair is
what ``MemberManager.add_member`` writes for the same member: ``(0, 'Inactive')``
for every non-Active status.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestBoardSeatNewMemberRowStatus1559(VereningingenTestCase):
    def _seat_and_read_row_1559(self, member_status):
        member = self.create_test_member(status=member_status)
        chapter = self.create_test_chapter()
        volunteer = self.create_test_volunteer(member=member.name)
        role = self.create_test_chapter_role()

        doc = frappe.get_doc("Chapter", chapter.name)
        self.assertNotIn(member.name, [m.member for m in doc.members or []], "fixture not clean")
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
        rows = [m for m in doc.members or [] if m.member == member.name]
        self.assertEqual(len(rows), 1, "seating should add exactly one Chapter Member row")
        return doc, member, rows[0]

    def test_seating_non_active_member_derives_row_like_add_member_1559(self):
        for status in ("Pending", "Suspended", "Quit", "Deceased"):
            with self.subTest(status=status):
                _doc, _member, row = self._seat_and_read_row_1559(status)
                self.assertEqual(row.status, "Inactive")
                self.assertFalse(row.enabled)

    def test_seating_active_member_still_gets_enabled_active_row_1559(self):
        # Control: the fix must not disable a legitimate Active member.
        _doc, _member, row = self._seat_and_read_row_1559("Active")
        self.assertEqual(row.status, "Active")
        self.assertTrue(row.enabled)

    def test_suspended_member_keeps_board_seat_when_row_is_inactive_1559(self):
        # Opposite harm: the board seat itself must survive the Inactive row.
        doc, _member, _row = self._seat_and_read_row_1559("Suspended")
        self.assertEqual(len([b for b in doc.board_members if b.is_active]), 1)
