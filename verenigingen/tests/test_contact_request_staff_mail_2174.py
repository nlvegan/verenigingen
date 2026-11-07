"""A new Member Contact Request mails staff on its registered key (#2174).

``MemberContactRequest`` did its new-request work in ``on_insert``, which Frappe never dispatches, so
the staff mail on ``contact_request_new`` / ``contact_request_urgent`` could not fire. It is now sent
from ``after_insert``. Maintainer ruling: the staff mail is revived, the CRM Lead creation is dropped.

The caller is the real one: a portal member (role Verenigingen Member only) going through
``_create_member_contact_request``, the helper ``submit_contact_request`` calls. Each key's row holds a
DIFFERENT fixed recipient, so the Email Queue recipient says which key sent the mail. The mail itself is
not stubbed: an outgoing Email Account exists and the assertions read the Email Queue rows.

Run:
    bench --site test_site_11 run-tests --app verenigingen --module verenigingen.tests.test_contact_request_staff_mail_2174
"""

import email

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.payment.test_sepa_literal_recipients import (
    _put_key_row,
    _restore_rows,
    _snapshot_rows,
)
from verenigingen.tests.utils.reminder_mail_state import clear_email_cooldowns, ensure_outgoing_email_account
from verenigingen.utils.constants import Roles
from verenigingen.verenigingen.doctype.member_contact_request.member_contact_request import (
    _create_member_contact_request,
)

CONFIG = "Verenigingen Email Configuration"
NEW_TO = "new-2174@example.org"
URGENT_TO = "urgent-2174@example.org"


class TestContactRequestStaffMail2174(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.prior_user = frappe.session.user
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        ensure_outgoing_email_account(self)
        clear_email_cooldowns()
        frappe.db.set_single_value(CONFIG, "master_email_enabled", 1)
        _put_key_row("contact_request_new", "Fixed", fixed_recipients=NEW_TO, cooldown_minutes=0)
        _put_key_row("contact_request_urgent", "Fixed", fixed_recipients=URGENT_TO, cooldown_minutes=0)

        suffix = frappe.generate_hash(length=6)
        self.member = self.create_test_member(
            first_name="Mail",
            last_name=f"Two{suffix}",
            email=f"member-2174-{suffix}@example.org",
            contact_number="+31611111111",
        )
        frappe.db.set_value("Member", self.member.name, "membership_status", "Active")
        # Probe shortcut: membership_status is computed, so it is set directly to pass the active-member gate.
        self.user = f"portal-2174-{suffix}@example.org"
        self.create_test_user(self.user, roles=[Roles.VERENIGINGEN_MEMBER])
        frappe.db.set_value("Member", self.member.name, "user", self.user, update_modified=False)
        self.addCleanup(frappe.set_user, self.prior_user)

    def _submit(self, urgency="Normal"):
        frappe.set_user(self.user)
        try:
            result = _create_member_contact_request(
                member=self.member.name, subject="Help 2174", message="Please call", urgency=urgency
            )
        finally:
            frappe.set_user(self.prior_user)
        self.track_doc("Member Contact Request", result["contact_request"])
        return result["contact_request"]

    def _mailed_to(self, request_name):
        queues = frappe.get_all(
            "Email Queue",
            filters={"reference_doctype": "Member Contact Request", "reference_name": request_name},
            pluck="name",
        )
        if not queues:
            return []
        return sorted(
            frappe.get_all("Email Queue Recipient", filters={"parent": ["in", queues]}, pluck="recipient")
        )

    def test_normal_request_mails_staff_once_on_contact_request_new(self):
        self.assertEqual(self._mailed_to(self._submit("Normal")), [NEW_TO])

    def test_urgent_request_mails_staff_once_on_contact_request_urgent(self):
        self.assertEqual(self._mailed_to(self._submit("Urgent")), [URGENT_TO])

    def test_other_urgency_levels_use_the_normal_key(self):
        for urgency in ("Low", "High"):
            self.assertEqual(self._mailed_to(self._submit(urgency)), [NEW_TO], urgency)

    def test_a_disabled_key_sends_nothing(self):
        _put_key_row("contact_request_new", "Fixed", fixed_recipients=NEW_TO, enabled=0)
        self.assertEqual(self._mailed_to(self._submit("Normal")), [])
        # Control: the urgent key is still enabled and still mails.
        self.assertEqual(self._mailed_to(self._submit("Urgent")), [URGENT_TO])

    def test_a_rolled_back_insert_mails_nobody(self):
        frappe.db.savepoint("contact_request_2174")
        name = self._submit("Normal")
        self.assertEqual(self._mailed_to(name), [NEW_TO], "control: the mail is queued before the rollback")
        frappe.db.rollback(save_point="contact_request_2174")
        self.assertEqual(self._mailed_to(name), [])

    def test_no_crm_lead_is_created(self):
        """Lead creation is attempted nowhere. On a site without the Lead link fields the attempt FAILS
        (an Error Log whose error is "CRM Integration Error", MyISAM so it survives rollback) instead of making a Lead, so
        the failed attempt is counted as well as the absence of a Lead."""
        attempts = {"error": "CRM Integration Error"}
        before = frappe.db.count("Error Log", attempts)
        name = self._submit("Normal")
        self.assertEqual(frappe.db.count("Error Log", attempts), before, "a CRM Lead was attempted")
        self.assertFalse(frappe.db.get_value("Member Contact Request", name, "crm_lead"))
        if frappe.db.exists("DocType", "Lead"):
            self.assertFalse(
                frappe.db.exists("Lead", {"title": ["like", "Member Contact Request:%"]}),
                "a CRM Lead was created for the request",
            )

    def test_member_text_is_escaped_in_the_staff_mail(self):
        """The mail is now live, so member-typed HTML must not reach staff as markup.

        (A <script> tag would prove nothing: frappe.sendmail's sanitiser strips it itself.)
        """
        frappe.set_user(self.user)
        try:
            result = _create_member_contact_request(
                member=self.member.name, subject="s", message="<b>bold2174</b>"
            )
        finally:
            frappe.set_user(self.prior_user)
        self.track_doc("Member Contact Request", result["contact_request"])
        raw = frappe.db.get_value(
            "Email Queue",
            {"reference_doctype": "Member Contact Request", "reference_name": result["contact_request"]},
            "message",
        )
        html = "".join(
            part.get_payload(decode=True).decode()
            for part in email.message_from_string(raw).walk()
            if part.get_content_type() == "text/html"
        )
        self.assertIn("&lt;b&gt;bold2174&lt;/b&gt;", html)
        self.assertNotIn("<b>bold2174", html)
