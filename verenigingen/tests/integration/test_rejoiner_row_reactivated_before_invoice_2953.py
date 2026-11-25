"""#2953: a rejoining applicant's earlier disabled/Inactive row in the assigned chapter is reactivated BEFORE the
first invoice, so that invoice carries the chapter.

Maintainer ruling (2026-11-25, option a). #2943 left an existing row of any status alone, so
assign_member_to_chapter re-enabled it only after the core and the first invoice had
custom_member_chapter=None (get_member_primary_chapter counts Active rows only).

Real flow: MemberManager.add_member seats the earlier row, the real termination service (or the real
remove_member) disables it, then submit_application -> confirm -> approve_application(create_invoice=True).
PROBE SHORTCUTS, stated: the order pin wraps the core and calls through; the failure test injects a fault at
the reactivation writer's boundary.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.integration.test_application_record_approval import ApprovalCase
from verenigingen.tests.support.termination_request import execute_real_termination


class TestRejoinerRowReactivatedBeforeInvoice2953(ApprovalCase):
    def _manager_2953(self, chapter):
        from verenigingen.verenigingen.doctype.chapter.managers.member_manager import MemberManager

        return MemberManager(frappe.get_doc("Chapter", chapter))

    def _rows_2953(self, member, chapter):
        return [
            (r.status, r.enabled)
            for r in frappe.get_all("Chapter Member", {"parent": chapter, "member": member}, ["status", "enabled"])
        ]

    def _invoice_chapters_2953(self, member):
        return frappe.get_all(
            "Sales Invoice",
            {"customer": frappe.db.get_value("Member", member, "customer")},
            pluck="custom_member_chapter",
        )

    def _comments_2953(self, member, text):
        full_name = frappe.db.get_value("Member", member, "full_name")
        return frappe.db.count(
            "Comment",
            {
                "reference_doctype": "Chapter",
                "reference_name": self.chapter.name,
                "content": f"{text} {full_name}",
            },
        )

    def _terminated_member_2953(self, chapter):
        member = self.create_test_member(email=self.email)
        added = self._manager_2953(chapter).add_member(member.name, notify=False)
        self.assertTrue(added["success"], added)
        execute_real_termination(self, member.name, frappe.utils.today())
        self.assertEqual(self._rows_2953(member.name, chapter), [("Inactive", 0)], "premise: ended row")
        return member

    def _approve_2953(self, application, chapter):
        return self._approve_as(
            application, membership_type=self.membership_type.name, chapter=chapter, create_invoice=True
        )

    def test_first_invoice_carries_the_chapter_of_a_terminated_rejoiners_ended_row(self):
        member = self._terminated_member_2953(self.chapter.name)
        application = self._stage_without_chapter()

        result = self._approve_2953(application, self.chapter.name)

        self.assertTrue(result["success"], result)
        self.assertEqual(self._rows_2953(member.name, self.chapter.name), [("Active", 1)])
        self.assertEqual(self._invoice_chapters_2953(member.name), [self.chapter.name])

    def test_first_invoice_carries_the_chapter_when_the_application_named_it_too(self):
        member = self._terminated_member_2953(self.chapter.name)
        application = self._stage_and_confirm(selected_chapter=self.chapter.name)

        result = self._approve_2953(application, self.chapter.name)

        self.assertTrue(result["success"], result)
        self.assertEqual(self._rows_2953(member.name, self.chapter.name), [("Active", 1)])
        self.assertEqual(self._invoice_chapters_2953(member.name), [self.chapter.name])

    def test_first_invoice_carries_the_chapter_of_a_row_disabled_by_remove_member(self):
        """The other writer: remove_member(permanent=False) disables the row of a then-Active member (the status is
        not touched); the real termination follows, so the applicant is Quit and may reapply."""
        member = self.create_test_member(email=self.email)
        manager = self._manager_2953(self.chapter.name)
        self.assertTrue(manager.add_member(member.name, notify=False)["success"])
        removed = self._manager_2953(self.chapter.name).remove_member(member.name, "left", notify=False)
        self.assertTrue(removed["success"], removed)
        execute_real_termination(self, member.name, frappe.utils.today())
        rows = self._rows_2953(member.name, self.chapter.name)
        self.assertEqual([enabled for _status, enabled in rows], [0], "premise: disabled row")
        application = self._stage_without_chapter()

        result = self._approve_2953(application, self.chapter.name)

        self.assertTrue(result["success"], result)
        self.assertEqual(self._rows_2953(member.name, self.chapter.name), [("Active", 1)])
        self.assertEqual(self._invoice_chapters_2953(member.name), [self.chapter.name])

    def test_the_ended_row_is_already_active_when_the_core_runs(self):
        """Pins the ORDER: the outcome alone is also met by editing the invoice afterwards."""
        from verenigingen.services.member.approval.membership_creation_service import (
            MembershipCreationService,
        )

        member = self._terminated_member_2953(self.chapter.name)
        application = self._stage_without_chapter()
        seen = []
        real = MembershipCreationService.create_membership_on_approval

        def wrapper(service, member_doc, *args, **kwargs):
            seen.append(self._rows_2953(member_doc.name, self.chapter.name))
            return real(service, member_doc, *args, **kwargs)

        # Mock justified: pass-through spy on the core's entry; the real function still runs.
        with patch.object(
            MembershipCreationService, "create_membership_on_approval", autospec=True, side_effect=wrapper
        ):
            result = self._approve_2953(application, self.chapter.name)

        self.assertTrue(result["success"], result)
        self.assertEqual(seen, [[("Active", 1)]])
        self.assertEqual(len(self._rows_2953(member.name, self.chapter.name)), 1, "one row, #2210")
        self.assertEqual(member.name, result["member"])

    def test_an_ended_row_in_a_chapter_the_approval_does_not_name_stays_ended(self):
        """Control: the earlier row in chapter Y is real and Inactive; the approval names chapter X only."""
        other = self.create_test_chapter(published=1)
        member = self._terminated_member_2953(other.name)
        application = self._stage_without_chapter()

        result = self._approve_2953(application, self.chapter.name)

        self.assertTrue(result["success"], result)
        self.assertEqual(self._rows_2953(member.name, other.name), [("Inactive", 0)])
        self.assertEqual(self._rows_2953(member.name, self.chapter.name), [("Active", 1)])
        self.assertEqual(self._invoice_chapters_2953(member.name), [self.chapter.name])

    def test_the_rejoiner_keeps_no_welcome_mail_one_re_enabled_comment_tracking_fields_and_one_active_history_entry(self):
        from verenigingen.verenigingen.doctype.chapter.managers.communication_manager import (
            CommunicationManager,
        )

        setting = "send_chapter_assignment_notifications"
        self.addCleanup(
            frappe.db.set_single_value,
            "Verenigingen Settings",
            setting,
            frappe.db.get_single_value("Verenigingen Settings", setting),
        )
        member = self._terminated_member_2953(self.chapter.name)
        frappe.flags.suppress_chapter_notifications = False
        frappe.db.set_single_value("Verenigingen Settings", setting, 1)
        application = self._stage_without_chapter()
        calls = []
        real = CommunicationManager.notify_member_added

        # Mock justified: pass-through spy; the mail still goes through the real manager.
        with patch.object(
            CommunicationManager,
            "notify_member_added",
            autospec=True,
            side_effect=lambda manager, member_id: (calls.append((manager.chapter_name, member_id)) or real(manager, member_id)),
        ):
            result = self._approve_2953(application, self.chapter.name)

        self.assertTrue(result["success"], result)
        self.assertEqual(calls, [], "unchanged: re-enabling a row never sent the welcome mail")
        self.assertEqual(self._comments_2953(member.name, "Re-enabled member"), 1)
        values = frappe.db.get_value(
            "Member", member.name, ["chapter_change_reason", "chapter_assigned_by"], as_dict=True
        )
        self.assertEqual(values.chapter_change_reason, "Membership application approval")
        self.assertEqual(values.chapter_assigned_by, self.admin_user.email)
        history = frappe.get_all(
            "Chapter Membership History",
            {"parent": member.name, "parenttype": "Member", "chapter_name": self.chapter.name},
            ["status"],
        )
        self.assertEqual(sorted(h.status for h in history).count("Active"), 1, history)
        self.assertNotIn("Pending", [h.status for h in history], history)
