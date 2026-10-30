"""Guest submit endpoint of the short membership application (/word-lid)."""

import json
import quopri

import frappe

from verenigingen.api import short_application as sa
from verenigingen.services.member.application.application_record import (
    MAX_MAILS_PER_ADDRESS_PER_DAY,
    build_confirm_url,
)
from verenigingen.tests.utils.application_door_fixture import ApplicationDoorMixin
from verenigingen.tests.utils.base import VereningingenUnitTestCase

IBAN = "NL91ABNA0417164300"
SUBMISSION = "Membership Application Submission"


class TestShortApplicationSubmit(ApplicationDoorMixin, VereningingenUnitTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type()
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": self.membership_type.name},
            "name",
        )
        # The auto-made template is Annual; the door's monthly slot takes only a Monthly one.
        frappe.db.set_value(
            "Membership Dues Schedule", template, {"minimum_amount": 2.5, "billing_frequency": "Monthly"}
        )
        self.door = self._door(monthly_dues_template=template)
        self.email = f"guest.{frappe.generate_hash(length=8).lower()}@example.org"
        self._previous_user = frappe.session.user

    def tearDown(self):
        frappe.set_user(self._previous_user)
        super().tearDown()

    def _submit_data(self, **overrides):
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
            "leave_this_empty": "",
        }
        data.update(overrides)
        return data

    def _submit_form(self, door=None, **overrides):
        """Call the endpoint as Guest; return (response, message_log)."""
        frappe.local.message_log = []
        frappe.set_user("Guest")
        try:
            response = sa.submit_short_application(door or self.door.name, **self._submit_data(**overrides))
        finally:
            frappe.set_user(self._previous_user)
        return response, list(frappe.local.message_log)

    def _sent_emails(self, address):
        """Queued mails to ``address``; ``message`` is the MIME body, decoded to readable text."""
        rows = frappe.get_all(
            "Email Queue",
            filters={"name": ["in", frappe.get_all("Email Queue Recipient", {"recipient": address}, pluck="parent")]},
            fields=["name", "message"],
        )
        for row in rows:
            row.message = quopri.decodestring(row.message.encode()).decode("utf-8", "replace")
        return rows

    def _row_counts(self):
        return {dt: frappe.db.count(dt) for dt in ("Member", "Address", "Customer", SUBMISSION)}

    def _existing_member(self, email, **fields):
        member = self.create_test_member(email=email)
        for key, value in fields.items():
            frappe.db.set_value("Member", member.name, key, value)
        return member

    def test_valid_submit_creates_submission_and_one_email_but_no_member(self):
        before = self._row_counts()
        response, _log = self._submit_form()
        after = self._row_counts()
        self.assertTrue(response["success"])
        for dt in ("Member", "Address", "Customer"):
            self.assertEqual(before[dt], after[dt], dt)
        self.assertEqual(after[SUBMISSION], before[SUBMISSION] + 1)
        row = frappe.get_all(SUBMISSION, {"email": self.email}, ["name", "status", "door"])
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0].status, "Unconfirmed")
        self.assertEqual(row[0].door, self.door.name)
        self.track_doc(SUBMISSION, row[0].name)
        mails = self._sent_emails(self.email)
        self.assertEqual(len(mails), 1)
        self.assertIn(frappe.utils.get_url(build_confirm_url(row[0].name)), mails[0].message.replace("&amp;", "&"))

    def test_active_member_email_gets_same_response_and_no_link_email(self):
        new_response, new_log = self._submit_form()
        for name in frappe.get_all(SUBMISSION, {"email": self.email}, pluck="name"):
            self.track_doc(SUBMISSION, name)
        known = f"known.{frappe.generate_hash(length=8).lower()}@example.org"
        member = self._existing_member(known, status="Active", application_status="Approved")
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Active")
        error_logs = frappe.db.count("Error Log")
        submissions = frappe.db.count(SUBMISSION)
        response, log = self._submit_form(email=known)
        self.assertEqual(response, new_response)
        self.assertEqual(log, new_log)
        self.assertEqual(frappe.db.count("Error Log"), error_logs)
        self.assertEqual(frappe.db.count(SUBMISSION), submissions)
        mails = self._sent_emails(known)
        self.assertEqual(len(mails), 1)
        self.assertNotIn("/word-lid/bevestig", mails[0].message)

    def test_email_matching_is_normalised(self):
        member = self._existing_member("foo.norm@example.org", status="Active", application_status="Approved")
        before = frappe.db.count(SUBMISSION)
        response, _log = self._submit_form(email=" Foo.Norm@Example.ORG ")
        self.assertTrue(response["success"])
        self.assertEqual(frappe.db.count(SUBMISSION), before)
        mails = self._sent_emails("foo.norm@example.org")
        self.assertEqual(len(mails), 1)
        self.assertNotIn("/word-lid/bevestig", mails[0].message)

    def test_rejected_applicant_gets_confirm_link(self):
        self._existing_member(self.email, status="Pending", application_status="Rejected")
        response, _log = self._submit_form()
        self.assertTrue(response["success"])
        rows = frappe.get_all(SUBMISSION, {"email": self.email}, pluck="name")
        self.assertEqual(len(rows), 1)
        self.track_doc(SUBMISSION, rows[0])
        mails = self._sent_emails(self.email)
        self.assertEqual(len(mails), 1)
        self.assertIn("/word-lid/bevestig", mails[0].message)

    def test_honeypot_returns_success_and_stores_nothing(self):
        expected, _ = self._submit_form()
        for name in frappe.get_all(SUBMISSION, {"email": self.email}, pluck="name"):
            self.track_doc(SUBMISSION, name)
        bot = f"bot.{frappe.generate_hash(length=8).lower()}@example.org"
        before = frappe.db.count(SUBMISSION)
        response, _log = self._submit_form(email=bot, leave_this_empty="http://spam.example")
        self.assertEqual(response, expected)
        self.assertEqual(frappe.db.count(SUBMISSION), before)
        self.assertEqual(self._sent_emails(bot), [])

    def test_an_autofilled_website_field_is_not_treated_as_a_bot(self):
        # The honeypot used to be called "website", a name browser autofill fills in.
        response, _log = self._submit_form(website="https://anna.example")
        self.assertTrue(response["success"])
        rows = frappe.get_all(SUBMISSION, {"email": self.email}, pluck="name")
        self.assertEqual(len(rows), 1)
        self.track_doc(SUBMISSION, rows[0])
        self.assertEqual(len(self._sent_emails(self.email)), 1)

    def _submit_times(self, count, **overrides):
        responses = [self._submit_form(**overrides)[0] for _ in range(count)]
        email = overrides.get("email", self.email)
        for name in frappe.get_all(SUBMISSION, {"email": email}, pluck="name"):
            self.track_doc(SUBMISSION, name)
        return responses

    def test_one_address_gets_at_most_the_daily_cap_of_confirmation_mails(self):
        cap = MAX_MAILS_PER_ADDRESS_PER_DAY
        responses = self._submit_times(cap + 1)
        self.assertEqual(len(set(map(json.dumps, responses))), 1)  # the capped call looks the same
        self.assertEqual(len(self._sent_emails(self.email)), cap)
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), cap)

    def test_the_daily_cap_also_limits_already_a_member_mails(self):
        known = f"capped.{frappe.generate_hash(length=8).lower()}@example.org"
        self._existing_member(known, status="Active", application_status="Approved")
        cap = MAX_MAILS_PER_ADDRESS_PER_DAY
        self._submit_times(cap + 1, email=known)
        self.assertEqual(len(self._sent_emails(known)), cap)

    def test_a_cap_counter_left_without_an_expiry_gets_one(self):
        """A request that died between incrby and expire must not block the address for good."""
        import hashlib

        key = frappe.cache.make_key(f"short_application_mails:{hashlib.sha256(self.email.encode()).hexdigest()}")
        frappe.cache.incrby(key, 1)  # what the dead request left behind: a count, no TTL
        self.assertEqual(frappe.cache.ttl(key), -1, "control: the seeded counter has no expiry")
        self._submit_times(1)
        self.assertGreater(frappe.cache.ttl(key), 0)

    def test_the_daily_cap_is_per_address(self):
        self._submit_times(MAX_MAILS_PER_ADDRESS_PER_DAY + 1)
        other = f"other.{frappe.generate_hash(length=8).lower()}@example.org"
        self._submit_times(1, email=other)
        self.assertEqual(len(self._sent_emails(other)), 1)

    def test_validation_error_is_returned(self):
        response, _log = self._submit_form(iban="")
        self.assertFalse(response["success"])
        self.assertIn("IBAN", response["message"])
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)

    def test_join_reasons_as_json_string_is_accepted(self):
        reason = frappe.get_doc(
            {"doctype": "Membership Join Reason", "reason": f"Test {frappe.generate_hash(length=8)}", "enabled": 1}
        ).insert()
        self.track_doc("Membership Join Reason", reason.name)
        response, _log = self._submit_form(join_reasons=json.dumps([reason.name]))
        self.assertTrue(response["success"])
        row = frappe.get_all(SUBMISSION, {"email": self.email}, ["name", "payload"])
        self.assertEqual(len(row), 1)
        self.track_doc(SUBMISSION, row[0].name)
        self.assertEqual(json.loads(row[0].payload)["join_reasons"], [reason.name])

    def test_join_reasons_as_int_is_refused_without_a_500(self):
        logs = frappe.db.count("Error Log")
        response, _log = self._submit_form(join_reasons=5)
        # The validation message, not handle_api_error's catch-all for an unexpected exception.
        self.assertEqual(response, {"success": False, "message": "Unknown reason for joining."})
        self.assertEqual(frappe.db.count("Error Log"), logs)
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)

    def test_amount_above_cap_is_refused(self):
        response, _log = self._submit_form(amount="10000.01")
        self.assertFalse(response["success"])
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)
        response, _log = self._submit_form(amount="10000")
        self.assertTrue(response["success"])
        for name in frappe.get_all(SUBMISSION, {"email": self.email}, pluck="name"):
            self.track_doc(SUBMISSION, name)

    def test_free_text_is_capped_at_140_characters(self):
        response, _log = self._submit_form(join_reason_other="x" * 500)
        self.assertTrue(response["success"])
        row = frappe.get_all(SUBMISSION, {"email": self.email}, ["name", "payload"])
        self.track_doc(SUBMISSION, row[0].name)
        self.assertEqual(len(json.loads(row[0].payload)["join_reason_other"]), 140)

    def test_unknown_and_disabled_door_look_like_a_validation_failure(self):
        disabled = self._door(enabled=0, monthly_dues_template=self.door.monthly_dues_template)
        for slug in ("bestaat-niet", disabled.name):
            response, log = self._submit_form(door=slug)
            self.assertFalse(response["success"])
            self.assertNotIn(slug, response["message"])
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)
        unknown, _ = self._submit_form(door="bestaat-niet")
        off, _ = self._submit_form(door=disabled.name)
        self.assertEqual(unknown, off)


class TestShortApplicationRateLimitIsPerVisitor(VereningingenUnitTestCase):
    """The security framework's limiter (skipped under test unless forced) must not put every
    anonymous visitor into one bucket: a per_user rule keys a Guest on the literal "Guest"."""

    def setUp(self):
        super().setUp()
        self._previous_user = frappe.session.user
        self._previous_request = getattr(frappe.local, "request", None)
        self._clear_buckets()

    def tearDown(self):
        frappe.local.request = self._previous_request
        frappe.set_user(self._previous_user)
        self._clear_buckets()
        super().tearDown()

    def _clear_buckets(self):
        # The engine writes raw redis keys (incrby), so frappe.cache.delete_keys, which adds the
        # site prefix, would not match them.
        for op in ("submit_short_application", "confirm_short_application"):
            for key in frappe.cache.keys(f"cor_rate_limit:{frappe.local.site}:*:{op}:*"):
                frappe.cache.delete(key)

    def _allowed_from(self, ip, operation):
        from werkzeug.test import EnvironBuilder

        from verenigingen.utils.security.rate_limit_engine import get_rate_limit_engine

        frappe.local.request = EnvironBuilder(environ_base={"REMOTE_ADDR": ip}).get_request()
        key = f"verenigingen.api.short_application.{operation}"
        return get_rate_limit_engine().check_rate_limit(key, force_check=True).allowed

    def _assert_second_visitor_still_served(self, operation):
        from verenigingen.utils.security.rate_limit_engine import get_rate_limit_engine

        frappe.set_user("Guest")
        limit = get_rate_limit_engine()._get_cor_config(operation)["rate_limit_calls"]
        for _ in range(limit):
            self.assertTrue(self._allowed_from("198.51.100.1", operation))
        self.assertFalse(self._allowed_from("198.51.100.1", operation))  # the limiter is live
        self.assertTrue(self._allowed_from("198.51.100.2", operation))

    def test_submit_limit_is_per_visitor(self):
        self._assert_second_visitor_still_served("submit_short_application")

    def test_confirm_limit_is_per_visitor(self):
        self._assert_second_visitor_still_served("confirm_short_application")
