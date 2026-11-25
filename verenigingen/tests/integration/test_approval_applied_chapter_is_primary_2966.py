"""#2966: when the reviewer's chapter differs from the applied chapter, the APPLIED chapter is primary.

Approval activates both Chapter Member rows on the same chapter_join_date (today), so every reader that
orders on that date alone left the tie to the database, and the first invoice and Member.current_chapter
could name different chapters. Maintainer ruling (2026-11-25, option b): the applied chapter wins.

Real flow: submit_application -> confirm -> approve_application(chapter=<reviewer pick>, create_invoice=True).
Both orientations run (applied = the first-created chapter and the second-created one), so neither a
pick-first nor an order-by-name resolution can pass both. No probe shortcuts; the control rows are real.
"""

import frappe

from verenigingen.services.chapter.chapter_utils import get_member_primary_chapter
from verenigingen.tests.integration.test_application_record_approval import ApprovalCase


class TestAppliedChapterIsPrimary2966(ApprovalCase):
    def _approve_applied_and_reviewer_2966(self, applied, reviewer):
        application = self._stage_and_confirm(selected_chapter=applied)
        result = self._approve_as(
            application,
            membership_type=self.membership_type.name,
            chapter=reviewer,
            create_invoice=True,
        )
        self.assertTrue(result["success"], result)
        return result["member"]

    def _assert_applied_is_primary_2966(self, applied, reviewer):
        member = self._approve_applied_and_reviewer_2966(applied, reviewer)
        rows = frappe.get_all(
            "Chapter Member",
            {"member": member, "parent": ["in", [applied, reviewer]]},
            ["parent", "status", "enabled", "chapter_join_date"],
        )
        # Premise: both rows Active on ONE date, the tie the issue describes.
        self.assertEqual(sorted(r.parent for r in rows), sorted([applied, reviewer]), rows)
        self.assertEqual({(r.status, r.enabled) for r in rows}, {("Active", 1)}, rows)
        self.assertEqual(len({r.chapter_join_date for r in rows}), 1, rows)

        customer = frappe.db.get_value("Member", member, "customer")
        invoice_chapters = frappe.get_all("Sales Invoice", {"customer": customer}, pluck="custom_member_chapter")
        self.assertEqual(invoice_chapters, [applied])
        self.assertEqual(frappe.db.get_value("Member", member, "current_chapter"), applied)
        self.assertEqual(get_member_primary_chapter(member), applied)
        from verenigingen.services.member.chapter.chapter_management_service import (
            get_chapter_management_service,
        )

        service = get_chapter_management_service()
        for chapters in (service.get_member_chapters_optimized(member), service.get_member_chapters(member)):
            self.assertEqual([c["chapter"] for c in chapters if c["is_primary"]], [applied], chapters)

    def test_applied_chapter_is_primary_when_created_first(self):
        first = self.chapter.name
        second = self.create_test_chapter(published=1).name
        self._assert_applied_is_primary_2966(applied=first, reviewer=second)

    def test_applied_chapter_is_primary_when_created_second(self):
        first = self.chapter.name
        second = self.create_test_chapter(published=1).name
        self._assert_applied_is_primary_2966(applied=second, reviewer=first)

    def test_a_later_join_date_still_beats_the_applied_chapter(self):
        """Control: the tiebreak only decides a TIE. A row that joined later stays primary, so the fix is not
        'always the applied chapter'. The later row is a real second chapter joined by the member afterwards."""
        other = self.create_test_chapter(published=1).name
        member = self._approve_applied_and_reviewer_2966(self.chapter.name, self.chapter.name)
        later = frappe.get_doc("Chapter", other)
        later.append(
            "members",
            {"member": member, "chapter_join_date": frappe.utils.add_days(frappe.utils.today(), 1),
             "enabled": 1, "status": "Active"},
        )
        later.save()

        from verenigingen.services.chapter.chapter_utils import get_applied_chapter

        self.assertEqual(get_applied_chapter(member), self.chapter.name)
        self.assertEqual(get_member_primary_chapter(member), other)
