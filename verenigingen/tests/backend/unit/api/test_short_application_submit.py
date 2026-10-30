"""Guest submit endpoint of the short membership application (/word-lid)."""

import json
import quopri

import frappe

from verenigingen.api import short_application as sa
from verenigingen.tests.utils.base import VereningingenUnitTestCase

IBAN = "NL91ABNA0417164300"
SUBMISSION = "Membership Application Submission"


class TestShortApplicationSubmit(VereningingenUnitTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type()
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": self.membership_type.name},
            "name",
        )
        frappe.db.set_value("Membership Dues Schedule", template, "minimum_amount", 2.5)
        self.door = self._door(monthly_dues_template=template)
        self.email = f"guest.{frappe.generate_hash(length=8).lower()}@example.org"
        self._previous_user = frappe.session.user

    def tearDown(self):
        frappe.set_user(self._previous_user)
        super().tearDown()

    def _door(self, **fields):
        data = {
            "doctype": "Membership Application Door",
            "title": "Testdeur",
            "slug": f"deur-{frappe.generate_hash(length=8).lower()}",
            "membership_type": self.membership_type.name,
            "form_shape": "Regular",
            "enabled": 1,
        }
        data.update(fields)
        door = frappe.get_doc(data).insert()
        self.track_doc("Membership Application Door", door.name)
        return door

    def _data(self, **overrides):
        data = {
            "first_name": "Anna",
            "last_name": "Berg",
            "email": self.email,
            "address_line1": "Kerkstraat",
            "postal_code": "1234AB",
            "house_number": "12",
            "city": "Utrecht",
            "country": "Netherlands",
            "frequency": "Monthly",
            "amount": "7.50",
            "iban": IBAN,
            "bank_account_name": "A. Berg",
            "consent": "1",
            "website": "",
        }
        data.update(overrides)
        return data

    def _submit(self, door=None, **overrides):
        """Call the endpoint as Guest; return (response, message_log)."""
        frappe.local.message_log = []
        frappe.set_user("Guest")
        try:
            response = sa.submit_short_application(door or self.door.name, **self._data(**overrides))
        finally:
            frappe.set_user(self._previous_user)
        return response, list(frappe.local.message_log)

    def _emails(self, address):
        """Queued mails to ``address``; ``message`` is the MIME body, decoded to readable text."""
        rows = frappe.get_all(
            "Email Queue",
            filters={"name": ["in", frappe.get_all("Email Queue Recipient", {"recipient": address}, pluck="parent")]},
            fields=["name", "message"],
        )
        for row in rows:
            row.message = quopri.decodestring(row.message.encode()).decode("utf-8", "replace")
        return rows

    def _counts(self):
        return {dt: frappe.db.count(dt) for dt in ("Member", "Address", "Customer", SUBMISSION)}

    def _member(self, email, **fields):
        member = self.create_test_member(email=email)
        for key, value in fields.items():
            frappe.db.set_value("Member", member.name, key, value)
        return member

    def test_valid_submit_creates_submission_and_one_email_but_no_member(self):
        before = self._counts()
        response, _log = self._submit()
        after = self._counts()
        self.assertTrue(response["success"])
        for dt in ("Member", "Address", "Customer"):
            self.assertEqual(before[dt], after[dt], dt)
        self.assertEqual(after[SUBMISSION], before[SUBMISSION] + 1)
        row = frappe.get_all(SUBMISSION, {"email": self.email}, ["name", "status", "door"])
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0].status, "Unconfirmed")
        self.assertEqual(row[0].door, self.door.name)
        self.track_doc(SUBMISSION, row[0].name)
        mails = self._emails(self.email)
        self.assertEqual(len(mails), 1)
        self.assertIn(frappe.utils.get_url(sa.build_confirm_url(row[0].name)), mails[0].message.replace("&amp;", "&"))

    def test_active_member_email_gets_same_response_and_no_link_email(self):
        new_response, new_log = self._submit()
        for name in frappe.get_all(SUBMISSION, {"email": self.email}, pluck="name"):
            self.track_doc(SUBMISSION, name)
        known = f"known.{frappe.generate_hash(length=8).lower()}@example.org"
        member = self._member(known, status="Active", application_status="Approved")
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Active")
        error_logs = frappe.db.count("Error Log")
        submissions = frappe.db.count(SUBMISSION)
        response, log = self._submit(email=known)
        self.assertEqual(response, new_response)
        self.assertEqual(log, new_log)
        self.assertEqual(frappe.db.count("Error Log"), error_logs)
        self.assertEqual(frappe.db.count(SUBMISSION), submissions)
        mails = self._emails(known)
        self.assertEqual(len(mails), 1)
        self.assertNotIn("/word-lid/bevestig", mails[0].message)

    def test_email_matching_is_normalised(self):
        member = self._member("foo.norm@example.org", status="Active", application_status="Approved")
        before = frappe.db.count(SUBMISSION)
        response, _log = self._submit(email=" Foo.Norm@Example.ORG ")
        self.assertTrue(response["success"])
        self.assertEqual(frappe.db.count(SUBMISSION), before)
        mails = self._emails("foo.norm@example.org")
        self.assertEqual(len(mails), 1)
        self.assertNotIn("/word-lid/bevestig", mails[0].message)

    def test_rejected_applicant_gets_confirm_link(self):
        self._member(self.email, status="Pending", application_status="Rejected")
        response, _log = self._submit()
        self.assertTrue(response["success"])
        rows = frappe.get_all(SUBMISSION, {"email": self.email}, pluck="name")
        self.assertEqual(len(rows), 1)
        self.track_doc(SUBMISSION, rows[0])
        mails = self._emails(self.email)
        self.assertEqual(len(mails), 1)
        self.assertIn("/word-lid/bevestig", mails[0].message)

    def test_honeypot_returns_success_and_stores_nothing(self):
        expected, _ = self._submit()
        for name in frappe.get_all(SUBMISSION, {"email": self.email}, pluck="name"):
            self.track_doc(SUBMISSION, name)
        bot = f"bot.{frappe.generate_hash(length=8).lower()}@example.org"
        before = frappe.db.count(SUBMISSION)
        response, _log = self._submit(email=bot, website="http://spam.example")
        self.assertEqual(response, expected)
        self.assertEqual(frappe.db.count(SUBMISSION), before)
        self.assertEqual(self._emails(bot), [])

    def test_validation_error_is_returned(self):
        response, _log = self._submit(iban="")
        self.assertFalse(response["success"])
        self.assertIn("IBAN", response["message"])
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)

    def test_join_reasons_as_json_string_is_accepted(self):
        reason = frappe.get_doc(
            {"doctype": "Membership Join Reason", "reason": f"Test {frappe.generate_hash(length=8)}", "enabled": 1}
        ).insert()
        self.track_doc("Membership Join Reason", reason.name)
        response, _log = self._submit(join_reasons=json.dumps([reason.name]))
        self.assertTrue(response["success"])
        row = frappe.get_all(SUBMISSION, {"email": self.email}, ["name", "payload"])
        self.assertEqual(len(row), 1)
        self.track_doc(SUBMISSION, row[0].name)
        self.assertEqual(json.loads(row[0].payload)["join_reasons"], [reason.name])

    def test_join_reasons_as_int_is_refused_without_a_500(self):
        logs = frappe.db.count("Error Log")
        response, _log = self._submit(join_reasons=5)
        # The validation message, not handle_api_error's catch-all for an unexpected exception.
        self.assertEqual(response, {"success": False, "message": "Unknown reason for joining."})
        self.assertEqual(frappe.db.count("Error Log"), logs)
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)

    def test_amount_above_cap_is_refused(self):
        response, _log = self._submit(amount="10000.01")
        self.assertFalse(response["success"])
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)
        response, _log = self._submit(amount="10000")
        self.assertTrue(response["success"])
        for name in frappe.get_all(SUBMISSION, {"email": self.email}, pluck="name"):
            self.track_doc(SUBMISSION, name)

    def test_free_text_is_capped_at_140_characters(self):
        response, _log = self._submit(join_reason_other="x" * 500)
        self.assertTrue(response["success"])
        row = frappe.get_all(SUBMISSION, {"email": self.email}, ["name", "payload"])
        self.track_doc(SUBMISSION, row[0].name)
        self.assertEqual(len(json.loads(row[0].payload)["join_reason_other"]), 140)

    def test_unknown_and_disabled_door_look_like_a_validation_failure(self):
        disabled = self._door(enabled=0, monthly_dues_template=self.door.monthly_dues_template)
        for slug in ("bestaat-niet", disabled.name):
            response, log = self._submit(door=slug)
            self.assertFalse(response["success"])
            self.assertNotIn(slug, response["message"])
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)
        unknown, _ = self._submit(door="bestaat-niet")
        off, _ = self._submit(door=disabled.name)
        self.assertEqual(unknown, off)
