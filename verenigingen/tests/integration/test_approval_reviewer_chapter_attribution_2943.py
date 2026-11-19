"""#2943: the reviewer-assigned chapter's row exists, Active, BEFORE the approval invoice is created.

#2916 moved the activation of the applicant's Pending row ahead of the first invoice. An applicant who named
NO chapter and whose reviewer picks one at approval still got the row from `assign_member_to_chapter`, which
runs after the core (#1797 needs the Member Active for add_member), so that first invoice carried
`custom_member_chapter=None`. Maintainer ruling (2026-11-19): write the Pending row directly before the
invoice, activate it through the same step, never edit the invoice afterwards, never widen
`get_member_primary_chapter`.

Real flow: submit_application -> confirm -> approve_application(chapter=<reviewer pick>, create_invoice=True).
The expected chapter is the fixture's. PROBE SHORTCUTS, stated: the rejoin test seats the earlier row with the
real MemberManager.add_member and ends it with the real termination service; the order pin wraps the core
and calls through.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.integration.test_application_record_approval import ApprovalCase
from verenigingen.tests.support.termination_request import execute_real_termination


class TestReviewerChapterBeforeInvoice2943(ApprovalCase):
    def _rows_2943(self, member, chapter):
        return frappe.get_all(
            "Chapter Member",
            {"parent": chapter, "member": member},
            ["status", "enabled"],
        )

    def _invoice_chapters_2943(self, member):
        return frappe.get_all(
            "Sales Invoice",
            {"customer": frappe.db.get_value("Member", member, "customer")},
            pluck="custom_member_chapter",
        )

    def _approve_into_2943(self, application, chapter, user=None, create_invoice=True):
        return self._approve_as(
            application,
            user=user,
            membership_type=self.membership_type.name,
            chapter=chapter,
            create_invoice=create_invoice,
        )

    def test_first_invoice_carries_the_reviewer_chapter_as_administrator(self):
        application = self._stage_without_chapter()

        result = self._approve_into_2943(application, self.chapter.name)

        self.assertTrue(result["success"], result)
        self.assertEqual(self._invoice_chapters_2943(result["member"]), [self.chapter.name])

    def test_first_invoice_carries_the_reviewer_chapter_as_a_scoped_board_approver(self):
        """A scoped approver can only reach an application that names a chapter it manages (a chapterless one
        is refused at the permission check), so the shape here is applied=A, reviewer=B with Admin seats on
        both. Probe shortcut, stated: the second seat is appended the way test_approval_refuses_unknown_chapter
        builds it. The invoice must carry a chapter either way; which one is derived (see the two-chapter test)."""
        other = self.create_test_chapter(published=1)
        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        other_doc = frappe.get_doc("Chapter", other.name)
        other_doc.append(
            "board_members",
            {
                "volunteer": board.volunteer,
                "chapter_role": board.chapter_role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        other_doc.save()
        application = self._stage_and_confirm(selected_chapter=self.chapter.name)

        result = self._approve_into_2943(application, other.name, user=board.user)

        self.assertTrue(result["success"], result)
        member = result["member"]
        self.assertEqual([(r.status, r.enabled) for r in self._rows_2943(member, other.name)], [("Active", 1)])
        self.assertEqual(len(self._invoice_chapters_2943(member)), 1)
        self.assertTrue(self._invoice_chapters_2943(member)[0], "the first invoice carries a chapter")

    def test_the_reviewer_chapter_row_is_already_active_when_the_core_runs(self):
        """Pins the ORDER (ruling): the outcome alone is also met by setting the invoice chapter after the
        core or by widening get_member_primary_chapter; the row's state at the core's entry is not."""
        from verenigingen.services.member.approval.membership_creation_service import MembershipCreationService

        seen = []
        real = MembershipCreationService.create_membership_on_approval

        def wrapper(service, member_doc, *args, **kwargs):
            seen.append(self._rows_2943(member_doc.name, self.chapter.name))
            return real(service, member_doc, *args, **kwargs)

        application = self._stage_without_chapter()
        # Mock justified: pass-through spy on the core's entry; the real function still runs.
        with patch.object(
            MembershipCreationService, "create_membership_on_approval", autospec=True, side_effect=wrapper
        ):
            result = self._approve_into_2943(application, self.chapter.name)

        self.assertTrue(result["success"], result)
        self.assertEqual(len(seen), 1)
        self.assertEqual([(r.status, r.enabled) for r in seen[0]], [("Active", 1)], "one Active row before")
        self.assertEqual(len(self._rows_2943(result["member"], self.chapter.name)), 1, "no second row after")

    def test_the_row_carries_the_tracking_fields_and_a_single_history_entry(self):
        """What assign_member_to_chapter wrote for a new row (tracking fields, one history entry) survives."""
        application = self._stage_without_chapter()

        result = self._approve_into_2943(application, self.chapter.name)

        member = result["member"]
        values = frappe.db.get_value(
            "Member", member, ["chapter_change_reason", "chapter_assigned_by"], as_dict=True
        )
        self.assertEqual(values.chapter_change_reason, "Membership application approval")
        self.assertEqual(values.chapter_assigned_by, self.admin_user.email)
        history = frappe.get_all(
            "Chapter Membership History",
            {"parent": member, "parenttype": "Member", "chapter_name": self.chapter.name},
            ["status"],
        )
        self.assertEqual([h.status for h in history], ["Active"], history)

    def test_the_applied_chapter_equal_to_the_reviewer_chapter_keeps_one_active_row(self):
        application = self._stage_and_confirm(selected_chapter=self.chapter.name)

        result = self._approve_into_2943(application, self.chapter.name)

        self.assertTrue(result["success"], result)
        self.assertEqual([(r.status, r.enabled) for r in self._rows_2943(result["member"], self.chapter.name)], [("Active", 1)])
        self.assertEqual(self._invoice_chapters_2943(result["member"]), [self.chapter.name])

    def test_a_different_applied_and_reviewer_chapter_activates_both_and_the_invoice_takes_one_of_them(self):
        other = self.create_test_chapter(published=1)
        application = self._stage_and_confirm(selected_chapter=self.chapter.name)

        result = self._approve_into_2943(application, other.name)

        member = result["member"]
        for chapter in (self.chapter.name, other.name):
            self.assertEqual([(r.status, r.enabled) for r in self._rows_2943(member, chapter)], [("Active", 1)])
        # DERIVED, not a policy: get_member_primary_chapter picks it; either chapter is attributed.
        self.assertIn(self._invoice_chapters_2943(member), ([self.chapter.name], [other.name]))

    def test_approval_without_an_invoice_still_leaves_one_active_reviewer_row(self):
        application = self._stage_without_chapter()

        result = self._approve_into_2943(application, self.chapter.name, create_invoice=False)

        self.assertTrue(result["success"], result)
        self.assertEqual([(r.status, r.enabled) for r in self._rows_2943(result["member"], self.chapter.name)], [("Active", 1)])

    def test_a_failed_core_leaves_no_row_in_the_reviewer_chapter(self):
        from verenigingen.services.member.approval.membership_creation_service import MembershipCreationService

        application = self._stage_without_chapter()
        # Mock justified: failure injection at the core boundary; everything before it is real.
        with patch.object(
            MembershipCreationService, "create_membership_on_approval", side_effect=frappe.ValidationError("boom")
        ):
            with self.assertRaises(frappe.ValidationError):
                self._approve_into_2943(application, self.chapter.name)

        member = frappe.db.get_value("Member", {"email": self.email}, "name")
        self.assertFalse(member and self._rows_2943(member, self.chapter.name))

    def test_a_rejoining_applicant_keeps_one_row_in_the_reviewer_chapter(self):
        """(#2210) The earlier row, disabled by the termination, is reused: never a second row. The first
        invoice of this shape is NOT asserted attributed: reactivating that row before the core needs a writer
        that works for a not-yet-Active Member (request_to_join refuses one, #2021); see the PR notes."""
        member = self.create_test_member(email=self.email)
        added = self._chapter_manager_2943().add_member(member.name, notify=False)
        self.assertTrue(added["success"], added)
        execute_real_termination(self, member.name, frappe.utils.today())
        before = self._rows_2943(member.name, self.chapter.name)
        self.assertEqual(len(before), 1, "premise: the earlier row exists")
        application = self._stage_without_chapter()

        result = self._approve_into_2943(application, self.chapter.name)

        self.assertTrue(result["success"], result)
        after = self._rows_2943(member.name, self.chapter.name)
        self.assertEqual([(r.status, r.enabled) for r in after], [("Active", 1)], (before, after))

    def test_the_new_row_sends_the_welcome_mail_exactly_when_assign_member_to_chapter_did(self):
        """The setting-gated welcome mail add_member sent for a new row is not lost to the early row."""
        from verenigingen.verenigingen.doctype.chapter.managers.communication_manager import CommunicationManager

        setting = "send_chapter_assignment_notifications"
        original = frappe.db.get_single_value("Verenigingen Settings", setting)
        self.addCleanup(frappe.db.set_single_value, "Verenigingen Settings", setting, original)
        frappe.flags.suppress_chapter_notifications = False
        sent = {}
        for wanted in (1, 0):
            frappe.db.set_single_value("Verenigingen Settings", setting, wanted)
            self.email = self._fresh_applicant_email()
            application = self._stage_without_chapter()
            calls = []
            # Mock justified: pass-through spy; the mail still goes through the real manager.
            with patch.object(
                CommunicationManager, "notify_member_added", autospec=True,
                side_effect=lambda manager, member_id, real=CommunicationManager.notify_member_added: (
                    calls.append((manager.chapter_name, member_id)) or real(manager, member_id)
                ),
            ):
                result = self._approve_into_2943(application, self.chapter.name)
            sent[wanted] = [c for c in calls if c == (self.chapter.name, result["member"])]
        self.assertEqual([len(sent[1]), len(sent[0])], [1, 0], sent)

    def _chapter_manager_2943(self):
        from verenigingen.verenigingen.doctype.chapter.managers.member_manager import MemberManager

        return MemberManager(frappe.get_doc("Chapter", self.chapter.name))
