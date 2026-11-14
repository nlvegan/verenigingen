"""#1842: the member's "joined" welcome mail goes only to a member whose row is enabled.

`MemberManager.add_member` writes a non-Active member's row disabled (`_derive_membership_status`),
and a disabled row is hidden from the roster, so "welcome to the chapter" is false for them. Two
senders reach the member with the `chapter_member_joined` key and both are covered here, each
through the real add_member flow:

* the direct `notify_member_added` call in `add_member` (events switched off), and
* the `chapter_membership_changed` "joined" subscriber (`run_events_synchronously`, notify=False).

Mail is asserted on the Email Queue rows addressed to THIS member, never on global counts.

Writers of the row state that gates the send (grep, develop 562342625):
  add_member new row ........ derived enabled/status (disabled+Inactive for non-Active): GATED here
  add_member re-enable ...... sends nothing (no notify call in that branch)
  request_to_join (new) ..... raw INSERT, Pending, no chapter save so no "joined" event
  request_to_join (rejoin) .. reactivates the existing row; no new row so no "joined" event
  approval of Pending row ... updates the existing row; no "joined" event
  member_subscribers ........ appends enabled=1/Active for an approved member: sends (correct)
"""

import frappe

from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.notification_state import own_notification_keys, queued_mail_count
from verenigingen.tests.utils.reminder_mail_state import ensure_outgoing_email_account


class TestChapterMemberWelcomeMail(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        own_notification_keys(self, "chapter_member_joined")
        ensure_outgoing_email_account(self)  # else a send is refused and a "no mail" assertion is vacuous
        self._ensure_welcome_template("member_added_to_chapter")
        self._ensure_welcome_template("chapter_member_notification")
        self.chapter = self.create_test_chapter(
            chapter_name=f"Welcome Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )

    def _ensure_welcome_template(self, name):
        if frappe.db.exists("Email Template", name):
            return
        tmpl = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": name,
                "subject": "Welcome",
                "response": "<p>Hi</p>",
                "response_html": "<p>Hi</p>",
                "use_html": 1,
            }
        ).insert()
        self.track_doc("Email Template", tmpl.name)

    def _welcome_member(self, status):
        return self.create_test_member(
            first_name="Welcome",
            last_name=status,
            email=f"welcome.{status.lower()}.{frappe.generate_hash(length=8)}@test.invalid",
            status=status,
        )

    def _assign_and_count_mail(self, member, notify, events_sync):
        before = queued_mail_count(member.email)
        saved = getattr(frappe.flags, "run_events_synchronously", None)
        frappe.flags.run_events_synchronously = events_sync
        try:
            result = ChapterMembershipManager.assign_member_to_chapter(
                member.name, self.chapter.name, notify=notify
            )
        finally:
            frappe.flags.run_events_synchronously = saved
        row = frappe.db.get_value(
            "Chapter Member",
            {"parent": self.chapter.name, "member": member.name},
            ["enabled", "status"],
            as_dict=True,
        )
        return queued_mail_count(member.email) - before, row, result

    def test_direct_welcome_not_sent_for_disabled_row(self):
        member = self._welcome_member("Suspended")
        sent, row, _result = self._assign_and_count_mail(member, notify=True, events_sync=False)
        self.assertIsNotNone(row, "fixture setup: the disabled row must exist")
        self.assertEqual((row.enabled, row.status), (0, "Inactive"), "fixture setup: derived disabled row")
        self.assertEqual(sent, 0)

    def test_direct_welcome_still_sent_for_active_row(self):
        member = self._welcome_member("Active")
        sent, row, _result = self._assign_and_count_mail(member, notify=True, events_sync=False)
        self.assertEqual((row.enabled, row.status), (1, "Active"))
        self.assertEqual(sent, 1)

    def test_event_welcome_not_sent_for_disabled_row(self):
        member = self._welcome_member("Suspended")
        sent, row, _result = self._assign_and_count_mail(member, notify=False, events_sync=True)
        self.assertIsNotNone(row, "fixture setup: the disabled row must exist")
        self.assertEqual((row.enabled, row.status), (0, "Inactive"), "fixture setup: derived disabled row")
        self.assertEqual(sent, 0)

    def test_event_welcome_still_sent_for_active_row(self):
        member = self._welcome_member("Active")
        sent, row, _result = self._assign_and_count_mail(member, notify=False, events_sync=True)
        self.assertEqual((row.enabled, row.status), (1, "Active"))
        self.assertEqual(sent, 1)
