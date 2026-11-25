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
        application = self._stage_and_confirm(
            selected_chapter=applied, email=self._fresh_applicant_email()
        )
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

    # ---- round 2: the other primary-chapter readers, the applied-chapter lookup, the no-tie path ----

    def _tied_member_2966(self, orientation_second):
        """A member whose applied and reviewer chapters tie on join date, through the real approval flow."""
        # Two chapters of its own per member: statistics are per chapter, so a shared one would accumulate.
        first = self.create_test_chapter(published=1).name
        second = self.create_test_chapter(published=1).name
        applied, reviewer = (second, first) if orientation_second else (first, second)
        return self._approve_applied_and_reviewer_2966(applied, reviewer), applied

    def _expulsion_request_2966(self, member):
        request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member,
                "termination_type": "Expulsion",
                "termination_reason": "Test expulsion",
                "termination_date": frappe.utils.today(),
                "requested_by": frappe.session.user,
                "request_date": frappe.utils.today(),
                "disciplinary_documentation": "Test documentation",
            }
        )
        request.insert()
        self.track_doc("Membership Termination Request", request.name)
        return request

    def _expulsion_chapter_from_service_2966(self, member):
        """The chapter the termination service writes on the expulsion entry. Mock justified: the insert is
        captured, not performed (the test system user lacks Expulsion Report:create, which refuses it before
        any row exists); everything that decides chapter_involved runs for real."""
        from unittest.mock import patch

        from verenigingen.services.approval.termination_approval_service import TerminationApprovalService

        captured = []

        def capture(operation, doc, **kwargs):
            captured.append(doc.chapter_involved)
            return frappe._dict(success=True, errors=[])

        with patch("verenigingen.utils.secure_operations.secure_document_operation", side_effect=capture):
            TerminationApprovalService(self._expulsion_request_2966(member))._add_to_expulsion_report()
        return captured

    def _force_physical_order_2966(self, member, applied, applied_first):
        """PROBE SHORTCUT, stated: rewrite the tied rows' name, idx and creation so that the applied chapter's
        row comes first (or last) under EVERY physical order a reader could fall back on. The tie itself (same
        join date, both Active) is what the real approval flow produced; only the arbitrary tail is pinned,
        in both directions, because on a fresh run the database happened to favour the applied row."""
        rows = frappe.get_all(
            "Chapter Member", {"member": member, "status": "Active"}, ["name", "parent"], order_by="parent"
        )
        ranked = sorted(rows, key=lambda row: (row.parent != applied) == (not applied_first))
        for rank, row in enumerate(ranked):
            frappe.db.sql(
                "UPDATE `tabChapter Member` SET name = %s, idx = %s, creation = %s WHERE name = %s",
                (
                    f"zz2966{'a' if applied_first else 'b'}{rank}{frappe.generate_hash(length=6)}",
                    rank + 1,
                    frappe.utils.add_days(frappe.utils.now(), -rank),
                    row.name,
                ),
            )
        frappe.clear_cache(doctype="Chapter")

    def _for_both_physical_orders_2966(self, check):
        member, applied = self._tied_member_2966(False)
        for applied_first in (True, False):
            with self.subTest(applied_first=applied_first):
                self._force_physical_order_2966(member, applied, applied_first)
                check(member, applied)

    def _check_expulsion_service_2966(self, member, applied):
        self.assertEqual(self._expulsion_chapter_from_service_2966(member), [applied])

    def _check_expulsion_doctype_2966(self, member, applied):
        entry = frappe.new_doc("Expulsion Report Entry")
        entry.member_id = member
        entry.set_chapter_from_member()
        self.assertEqual(entry.chapter_involved, applied)

    def _check_account_report_2966(self, member, applied):
        from verenigingen.verenigingen.report.account_creation_status.account_creation_status import get_data

        rows = [r for r in get_data({}) if r.get("member_name") == member]
        self.assertEqual([r["active_chapter"] for r in rows], [applied], rows)

    def _check_chapter_statistics_2966(self, member, applied):
        other = next(
            r.parent
            for r in frappe.get_all("Chapter Member", {"member": member}, ["parent"])
            if r.parent != applied
        )
        applied_stats = frappe.get_doc("Chapter", applied).member_manager.get_member_statistics()
        other_stats = frappe.get_doc("Chapter", other).member_manager.get_member_statistics()
        self.assertEqual(applied_stats["primary_members"], 1, applied_stats)
        self.assertEqual(other_stats["primary_members"], 0, other_stats)

    def _check_primary_readers_2966(self, member, applied):
        from verenigingen.services.member.chapter.chapter_management_service import (
            get_chapter_management_service,
        )

        self.assertEqual(get_member_primary_chapter(member), applied)
        service = get_chapter_management_service()
        for chapters in (service.get_member_chapters_optimized(member), service.get_member_chapters(member)):
            self.assertEqual([c["chapter"] for c in chapters if c["is_primary"]], [applied], chapters)

    def test_expulsion_service(self):
        self._for_both_physical_orders_2966(self._check_expulsion_service_2966)

    def test_expulsion_doctype(self):
        self._for_both_physical_orders_2966(self._check_expulsion_doctype_2966)

    def test_account_creation_report(self):
        self._for_both_physical_orders_2966(self._check_account_report_2966)

    def test_chapter_statistics(self):
        self._for_both_physical_orders_2966(self._check_chapter_statistics_2966)

    def test_primary_readers_in_both_physical_orders(self):
        self._for_both_physical_orders_2966(self._check_primary_readers_2966)

    def _submission_for_2966(self, member, chapter, status, review_date):
        """PROBE SHORTCUT, stated: a copy of the member's real Approved submission with the status, chapter and
        review date set directly. A second Approved submission for one member (a re-application after a
        quit) is the reachable shape; a Rejected one carries `member` the same way (set at submit for an
        existing member), but I did not drive those flows."""
        source = frappe.get_all("Membership Application Submission", {"member": member}, pluck="name")[0]
        copy = frappe.copy_doc(frappe.get_doc("Membership Application Submission", source))
        copy.application_id = f"APP-T2966-{frappe.generate_hash(length=8)}"
        copy.insert()
        self.track_doc("Membership Application Submission", copy.name)
        frappe.db.set_value(
            "Membership Application Submission",
            copy.name,
            {"member": member, "chapter": chapter, "status": status, "review_date": review_date},
            update_modified=False,
        )
        return copy.name

    def test_the_newest_approved_submission_names_the_applied_chapter(self):
        from verenigingen.services.chapter.chapter_utils import get_applied_chapter

        member, applied = self._tied_member_2966(False)
        older, newer, rejected = (self.create_test_chapter(published=1).name for _ in range(3))
        base = frappe.utils.get_datetime(frappe.utils.now())
        self._submission_for_2966(member, older, "Approved", frappe.utils.add_days(base, -30))
        self._submission_for_2966(member, newer, "Approved", frappe.utils.add_days(base, 30))
        # The control for the status filter: the NEWEST of all, but not Approved.
        self._submission_for_2966(member, rejected, "Rejected", frappe.utils.add_days(base, 60))

        self.assertEqual(get_applied_chapter(member), newer)

    def test_the_tie_path_looks_up_the_applied_chapter_and_the_no_tie_path_does_not(self):
        from unittest.mock import patch

        from verenigingen.services.chapter import chapter_utils

        today = frappe.utils.today()
        tie = [{"parent": "B", "chapter_join_date": today}, {"parent": "A", "chapter_join_date": today}]
        no_tie = [
            {"parent": "B", "chapter_join_date": frappe.utils.add_days(today, -1)},
            {"parent": "A", "chapter_join_date": today},
        ]
        # Mock justified: pass-through spy counting lookups; the real function still answers.
        with patch.object(
            chapter_utils, "get_applied_chapter", side_effect=chapter_utils.get_applied_chapter
        ) as spy:
            ordered = chapter_utils.order_chapters_primary_first("x", no_tie)
            self.assertEqual([r["parent"] for r in ordered], ["A", "B"])
            self.assertEqual(spy.call_count, 0)
            chapter_utils.order_chapters_primary_first("x", tie)
            self.assertEqual(spy.call_count, 1)
