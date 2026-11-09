"""Member-typed text in the four sibling Member Contact Request mails is HTML-escaped (#2214).

#2174 escaped the new-request staff mail (``notify_staff``). The other mails built from the same
member-typed ``subject`` / ``member_name`` interpolated them raw:

* assignee mail            ``MemberContactRequest.handle_assignment_change``
* follow-up reminder       ``contact_request_automation.send_follow_up_reminders``
* escalation               ``contact_request_automation.escalate_contact_request``
* auto-close (to member)   ``contact_request_automation.auto_close_resolved_requests``

Each test drives the REAL sender and reads the Email Queue row it produced. ``subject`` is hostile in
every test AND ``member_name`` is hostile in every test, so escaping only one of the two fields fails.
(A <script> tag would prove nothing: frappe.sendmail's sanitiser strips it itself, benign markup is kept.)

Probe shortcut: the follow-up/escalation/auto-close tests make the request due with ``db.set_value`` on
``follow_up_date`` / ``request_date`` / ``status`` / ``response_date`` instead of waiting days; the senders
themselves are unmodified. ``member_name`` is set hostile directly on the request row: Member's own name validator
refuses markup in first/last name, so the field cannot be filled through the real flow today; it is
escaped anyway because the mail must not depend on that validator staying in front of it.

Run:
    bench --site test_site_5 run-tests --app verenigingen --module verenigingen.tests.test_contact_request_mail_escaping_2214
"""

import email

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.payment.test_sepa_literal_recipients import (
    _put_key_row,
    _restore_rows,
    _snapshot_rows,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.reminder_mail_state import clear_email_cooldowns, ensure_outgoing_email_account
from verenigingen.utils.constants import Roles
from verenigingen.verenigingen.doctype.member_contact_request import contact_request_automation as auto
from verenigingen.verenigingen.doctype.member_contact_request.member_contact_request import (
    _create_member_contact_request,
)

CONFIG = "Verenigingen Email Configuration"
SUBJECT_HTML = '<b>subj2214</b><a href="http://evil2214">'
NAME_HTML = "<i>nm2214</i>"
ESCAPED_SUBJECT = "&lt;b&gt;subj2214&lt;/b&gt;&lt;a href="
ESCAPED_NAME = "&lt;i&gt;nm2214&lt;/i&gt;"
ESCALATION_TO = "escalation-2214@example.org"


class TestContactRequestMailEscaping2214(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.prior_user = frappe.session.user
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        ensure_outgoing_email_account(self)
        clear_email_cooldowns()
        frappe.db.set_single_value(CONFIG, "master_email_enabled", 1)
        for key in ("contact_request_new", "contact_request_urgent"):
            _put_key_row(key, "Fixed", fixed_recipients="staff-2214@example.org", cooldown_minutes=0)
        _put_key_row("contact_request_escalated", "Fixed", fixed_recipients=ESCALATION_TO, cooldown_minutes=0)
        for key in ("contact_request_assigned", "contact_request_response_sent"):
            _put_key_row(key, "Document-Field", cooldown_minutes=0)

        suffix = frappe.generate_hash(length=6)
        self.member = self.create_test_member(
            first_name="Esc",
            last_name=f"Esc{suffix}",
            email=f"member-2214-{suffix}@example.org",
            contact_number="+31611111111",
        )
        frappe.db.set_value("Member", self.member.name, "membership_status", "Active")
        self.member_email = f"member-2214-{suffix}@example.org"
        self.user = f"portal-2214-{suffix}@example.org"
        self.create_test_user(self.user, roles=[Roles.VERENIGINGEN_MEMBER])
        frappe.db.set_value("Member", self.member.name, "user", self.user, update_modified=False)
        self.assignee = f"assignee-2214-{suffix}@example.org"
        self.create_test_user(self.assignee, roles=[Roles.VERENIGINGEN_ADMIN])
        self.addCleanup(frappe.set_user, self.prior_user)
        self.name = self._submit()
        frappe.db.set_value("Member Contact Request", self.name, "member_name", NAME_HTML)

    def _submit(self):
        frappe.set_user(self.user)
        try:
            result = _create_member_contact_request(member=self.member.name, subject=SUBJECT_HTML, message="m")
        finally:
            frappe.set_user(self.prior_user)
        self.track_doc("Member Contact Request", result["contact_request"])
        return result["contact_request"]

    def _html_to(self, recipient):
        """The HTML body of the (single) queued mail to ``recipient`` about this request."""
        queues = frappe.get_all(
            "Email Queue Recipient", filters={"recipient": recipient}, pluck="parent"
        )
        raws = frappe.get_all(
            "Email Queue",
            filters={
                "name": ["in", queues or [""]],
                "reference_doctype": "Member Contact Request",
                "reference_name": self.name,
            },
            pluck="message",
        )
        self.assertEqual(len(raws), 1, f"expected exactly one mail to {recipient}, got {len(raws)}")
        return "".join(
            part.get_payload(decode=True).decode()
            for part in email.message_from_string(raws[0]).walk()
            if part.get_content_type() == "text/html"
        )

    def _assert_escaped(self, html):
        # The <title> repeats the (already escaped by the template) mail subject; assert on the body only.
        html = html.split("<body", 1)[1]
        self.assertIn(ESCAPED_SUBJECT, html, "subject not escaped")
        self.assertIn(ESCAPED_NAME, html, "member_name not escaped")
        self.assertNotIn("<b>subj2214", html)
        self.assertNotIn('<a href="http://evil2214', html)
        self.assertNotIn("<i>nm2214", html)

    def test_control_the_stored_values_really_are_hostile(self):
        """Control: the stored subject and member_name are really hostile, so the escaped asserts can fail."""
        # Frappe's own Data sanitiser keeps <b> and the link (it only adds rel=), so markup survives storage.
        self.assertIn("<b>subj2214</b><a href=", frappe.db.get_value("Member Contact Request", self.name, "subject"))
        self.assertIn(NAME_HTML, frappe.db.get_value("Member Contact Request", self.name, "member_name"))

    def test_assignee_mail_escapes_member_text(self):
        """Calls the real ``handle_assignment_change`` with a hostile in-memory ``member_name``.

        Probe shortcut: a save re-fetches member_name from the Member (whose own validator refuses markup),
        so the field is hand-assigned on the in-memory doc to prove the mail does not rely on that.
        """
        doc = frappe.get_doc("Member Contact Request", self.name)
        doc.member_name = NAME_HTML
        doc.assigned_to = self.assignee
        doc.handle_assignment_change()
        self._assert_escaped(self._html_to(self.assignee))

    def test_assignee_mail_from_a_real_save_escapes_the_subject(self):
        """The on_update path (assigned_to changed on save) -- the real flow; subject only (see above)."""
        doc = frappe.get_doc("Member Contact Request", self.name)
        doc.assigned_to = self.assignee
        frappe.set_user(self.assignee)
        try:
            doc.save()
        finally:
            frappe.set_user(self.prior_user)
        body = self._html_to(self.assignee).split("<body", 1)[1]
        self.assertIn(ESCAPED_SUBJECT, body)
        self.assertNotIn("<b>subj2214", body)

    def test_follow_up_reminder_escapes_member_text(self):
        frappe.db.set_value(
            "Member Contact Request",
            self.name,
            {"assigned_to": self.assignee, "status": "Open", "follow_up_date": add_days(today(), -1)},
        )
        auto.send_follow_up_reminders()
        self._assert_escaped(self._html_to(self.assignee))

    def test_escalation_escapes_member_text(self):
        frappe.db.set_value(
            "Member Contact Request",
            self.name,
            {"status": "Open", "urgency": "Urgent", "request_date": add_days(today(), -5)},
        )
        auto.escalate_overdue_requests()
        self._assert_escaped(self._html_to(ESCALATION_TO))

    def test_auto_close_mail_escapes_member_text(self):
        frappe.db.set_value(
            "Member Contact Request",
            self.name,
            {"status": "Resolved", "response_date": add_days(today(), -30), "closed_date": None},
        )
        auto.auto_close_resolved_requests()
        self._assert_escaped(self._html_to(self.member_email))
