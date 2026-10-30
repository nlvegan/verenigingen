"""#1765 / #1740: submitting or confirming a membership application touches no Member.

Both forms stage an application as a Membership Application Submission. Everything is driven
through the real endpoints as Guest; the confirm step runs as a POST like the emailed link does.
"""

import json
import random
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime, today
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.api import short_application as sa
from verenigingen.api.membership_application import (
    check_application_eligibility_endpoint,
    submit_application,
    validate_email,
)
from verenigingen.services.member.application.short_application_confirm import CONFIRM_TOKEN_PURPOSE
from verenigingen.tests.utils.application_door_fixture import ApplicationDoorMixin
from verenigingen.tests.utils.base import VereningingenUnitTestCase
from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token

IBAN = "NL91ABNA0417164300"
OTHER_IBAN = "NL02ABNA0123456789"
SUBMISSION = "Membership Application Submission"


class ApplicationRecordCase(ApplicationDoorMixin, VereningingenUnitTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type()
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": self.membership_type.name},
            "name",
        )
        frappe.db.set_value(
            "Membership Dues Schedule", template, {"minimum_amount": 2.5, "billing_frequency": "Monthly"}
        )
        self.door = self._door(monthly_dues_template=template)
        self.email = self._unused_email()
        self._previous_user = frappe.session.user
        self._previous_request = getattr(frappe.local, "request", None)
        self._previous_ip = getattr(frappe.local, "request_ip", None)

    def tearDown(self):
        frappe.local.request = self._previous_request
        frappe.local.request_ip = self._previous_ip
        frappe.set_user(self._previous_user)
        super().tearDown()

    def _unused_email(self):
        return f"rec.{frappe.generate_hash(length=8).lower()}@example.org"

    # -- helpers ---------------------------------------------------------------------------------

    def _short_data(self, **overrides):
        data = {
            "first_name": "Anna",
            "tussenvoegsel": "van",
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

    def _full_data(self, **overrides):
        data = {
            "first_name": "Guest",
            "last_name": "Applicant",
            "email": self.email,
            "birth_date": "1990-01-01",
            "address_line1": "123 Test Street",
            "city": "Amsterdam",
            "postal_code": "1234AB",
            "country": "Netherlands",
            "selected_membership_type": self.membership_type.name,
        }
        data.update(overrides)
        return data

    def _as_guest(self, fn, *args, **kwargs):
        """Call as Guest; return (response, new message_log entries, new Error Log rows)."""
        logs = frappe.db.count("Error Log")
        frappe.local.message_log = []
        frappe.set_user("Guest")
        try:
            response = fn(*args, **kwargs)
        finally:
            frappe.set_user(self._previous_user)
        if isinstance(response, dict):
            response = {key: value for key, value in response.items() if key != "timestamp"}  # a clock reading
        return response, list(frappe.local.message_log), frappe.db.count("Error Log") - logs

    def _submit_short(self, **overrides):
        response, _log, _errors = self._as_guest(
            sa.submit_short_application, self.door.name, **self._short_data(**overrides)
        )
        self.assertTrue(response["success"], response)
        return self._latest_submission(overrides.get("email", self.email))

    def _submit_full(self, **overrides):
        response, log, errors = self._as_guest(submit_application, **self._full_data(**overrides))
        self.assertTrue(response["success"], response)
        return response, log, errors

    def _latest_submission(self, email):
        names = frappe.get_all(SUBMISSION, {"email": email.strip().lower()}, pluck="name", order_by="creation desc, name desc")
        self.assertTrue(names, f"no submission for {email}")
        for name in names:
            self.track_doc(SUBMISSION, name)
        return names[0]

    def _confirm_link(self, name):
        token = generate_guest_return_token(CONFIRM_TOKEN_PURPOSE, name)
        frappe.local.request = Request(EnvironBuilder(method="POST").get_environ())
        frappe.local.request_ip = f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
        response, log, _errors = self._as_guest(sa.confirm_short_application, name, token)
        return response, log

    def _footprint(self, email):
        """Everything a Member would leave behind for this email."""
        member = frappe.db.get_value("Member", {"email": email})
        return {
            "members": frappe.db.count("Member", {"email": email}),
            "addresses": frappe.db.count("Address", {"email_id": email}),
            "chapter_members": frappe.db.count("Chapter Member", {"member": member}) if member else 0,
            "volunteers": frappe.db.count("Volunteer", {"email": email}),
            "customers": frappe.db.count("Customer", {"email_id": email}),
        }

    def _voluntarily_quit_member(self, **fields):
        """A voluntarily-Quit member through the real termination flow."""
        from verenigingen.services.termination.termination_execution_service import (
            TerminationExecutionService,
        )

        member = self.create_test_member(email=self.email, iban=IBAN, **fields)
        request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test",
                "termination_date": today(),
                "requested_by": frappe.session.user,
                "request_date": today(),
                "status": "Approved",
                "approved_by": frappe.session.user,
                "approval_date": now_datetime(),
            }
        )
        request.insert()
        request.submit()
        # Mock justified: execute() opens its own transaction; the harness owns this one.
        with patch("frappe.db.begin"), patch("frappe.db.commit"), patch("frappe.db.rollback"):
            self.assertTrue(TerminationExecutionService().execute(request))
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Quit")
        return member


class TestApplicationRecord(ApplicationRecordCase):
    def test_full_form_submit_creates_no_member(self):
        customers = frappe.db.count("Customer")
        response, _log, _errors = self._submit_full()

        self.assertEqual(response["data"], {"status": "confirmation_sent"}, response)
        self.assertEqual(
            self._footprint(self.email),
            {"members": 0, "addresses": 0, "chapter_members": 0, "volunteers": 0, "customers": 0},
        )
        self.assertEqual(frappe.db.count("Customer"), customers)
        rows = frappe.get_all(SUBMISSION, {"email": self.email}, ["name", "status", "source"])
        self.assertEqual([(r.status, r.source) for r in rows], [("Unconfirmed", "Full Form")])
        self.track_doc(SUBMISSION, rows[0].name)

    def test_full_form_response_identical_for_existing_member(self):
        """Compared on every channel a Guest or an operator could read; Active is an existing member."""
        unknown, unknown_log, unknown_errors = self._submit_full()
        self._latest_submission(self.email)
        known_email = self._unused_email()
        member = self.create_test_member(email=known_email)
        frappe.db.set_value("Member", member.name, {"status": "Active", "application_status": "Approved"})
        submissions = frappe.db.count(SUBMISSION)

        known, known_log, known_errors = self._submit_full(email=known_email)

        self.assertEqual(known, unknown)
        self.assertEqual(known_log, unknown_log)
        self.assertEqual(known_errors, unknown_errors)
        self.assertEqual(frappe.db.count(SUBMISSION), submissions, "no row staged for a member")

    def test_full_form_involuntary_and_unclear_terminations_get_the_same_response(self):
        unknown, unknown_log, _ = self._submit_full()
        self._latest_submission(self.email)
        for label, status in (("Quit without a request", "Quit"), ("unknown status", "Suspended")):
            with self.subTest(label):
                email = self._unused_email()
                member = self.create_test_member(email=email)
                frappe.db.set_value("Member", member.name, {"status": status, "application_status": "Approved"})
                known, known_log, _errors = self._submit_full(email=email)
                self.assertEqual((known, known_log), (unknown, unknown_log))
                self.expectErrorLog("Termination Data Integrity")

    def test_email_lookups_do_not_reveal_an_existing_member(self):
        """The eligibility and email-validity endpoints answered 'a member with this email exists'."""
        known_email = self._unused_email()
        self.create_test_member(email=known_email)
        for fn, arg in (
            (validate_email, lambda e: {"email": e}),
            (
                check_application_eligibility_endpoint,
                lambda e: {"data": json.dumps(self._full_data(email=e))},
            ),
        ):
            with self.subTest(fn.__name__):
                unknown = self._as_guest(fn, **arg(self._unused_email()))
                known = self._as_guest(fn, **arg(known_email))
                self.assertEqual(known, unknown)

    def test_an_unknown_membership_type_is_refused_before_anything_is_staged(self):
        """Creating the Member used to fail on it; staging alone would accept any string."""
        for chosen in ("No such type " + frappe.generate_hash(length=6), {"name": "x"}):
            with self.subTest(repr(chosen)[:20]):
                response, _log, _errors = self._as_guest(
                    submit_application, **self._full_data(selected_membership_type=chosen)
                )
                self.assertFalse(response["success"], response)
                self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)

    def test_confirm_creates_no_member(self):
        chapter = self.create_test_chapter(postal_codes="7701-7799", published=1)
        name = self._submit_short(postal_code="7745AB")

        response, log = self._confirm_link(name)

        self.assertTrue(response["success"], response)
        self.assertEqual(log, [])
        row = frappe.db.get_value(
            SUBMISSION, name, ["status", "chapter", "applicant_name", "membership_type", "application_id"], as_dict=True
        )
        self.assertEqual(row.status, "Pending Review")
        self.assertEqual(row.chapter, chapter.name)
        self.assertEqual(row.applicant_name, "Anna van Berg")
        self.assertEqual(row.membership_type, self.membership_type.name)
        self.assertTrue(row.application_id)
        self.assertEqual(
            self._footprint(self.email),
            {"members": 0, "addresses": 0, "chapter_members": 0, "volunteers": 0, "customers": 0},
        )
        self.assertEqual(frappe.db.count("Chapter Member", {"parent": chapter.name, "status": "Pending"}), 0)

    def test_full_form_confirm_creates_no_member_and_resolves_the_chapter(self):
        chapter = self.create_test_chapter(published=1)
        self._submit_full(selected_chapter=chapter.name)
        name = self._latest_submission(self.email)

        response, _log = self._confirm_link(name)

        self.assertTrue(response["success"], response)
        row = frappe.db.get_value(
            SUBMISSION, name, ["status", "chapter", "applicant_name", "membership_type"], as_dict=True
        )
        self.assertEqual(
            (row.status, row.chapter, row.applicant_name, row.membership_type),
            ("Pending Review", chapter.name, "Guest Applicant", self.membership_type.name),
        )
        self.assertEqual(self._footprint(self.email)["members"], 0)
        self.assertEqual(self._footprint(self.email)["chapter_members"], 0)

    def test_an_unselectable_chapter_is_dropped_at_confirm_for_both_forms(self):
        """#1731's published+Active check, which the short path never applied."""
        for label, status, published in (("unpublished", "Active", 0), ("inactive", "Inactive", 1)):
            chapter = self.create_test_chapter(published=published, status=status)
            with self.subTest(label + " full"):
                email = self._unused_email()
                self._submit_full(email=email, selected_chapter=chapter.name)
                name = self._latest_submission(email)
                self.assertTrue(self._confirm_link(name)[0]["success"])
                self.assertEqual(frappe.db.get_value(SUBMISSION, name, "chapter"), None)

    def test_a_short_form_postal_match_on_an_inactive_chapter_is_dropped(self):
        self.create_test_chapter(postal_codes="7801-7899", published=1, status="Inactive")
        name = self._submit_short(postal_code="7845AB", city="Nergenshuizen")
        self.assertTrue(self._confirm_link(name)[0]["success"])
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "chapter"), None)

    def test_reapplication_confirm_leaves_member_untouched(self):
        member = self._voluntarily_quit_member()
        before = frappe.db.get_value(
            "Member", member.name, ["iban", "last_name", "first_name", "status", "modified"], as_dict=True
        )
        self.assertEqual(before.iban.replace(" ", ""), IBAN, "control: the member carries its own IBAN")
        name = self._submit_short(iban=OTHER_IBAN, last_name="Anders", first_name="Nieuwe")

        response, _log = self._confirm_link(name)

        self.assertTrue(response["success"], response)
        after = frappe.db.get_value(
            "Member", member.name, ["iban", "last_name", "first_name", "status", "modified"], as_dict=True
        )
        self.assertEqual(after, before)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")
        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 1)

    def test_reapplication_via_the_full_form_leaves_member_untouched(self):
        member = self._voluntarily_quit_member()
        before = frappe.db.get_value(
            "Member", member.name, ["iban", "last_name", "status", "modified"], as_dict=True
        )
        self._submit_full(last_name="Anders", iban=OTHER_IBAN, bank_account_name="Nieuwe Rekening")
        name = self._latest_submission(self.email)
        self.assertTrue(self._confirm_link(name)[0]["success"])
        after = frappe.db.get_value(
            "Member", member.name, ["iban", "last_name", "status", "modified"], as_dict=True
        )
        self.assertEqual(after, before)

    def test_second_confirm_supersedes_first(self):
        first = self._submit_short()
        second = self._submit_short()
        self.assertNotEqual(first, second)
        self.assertTrue(self._confirm_link(first)[0]["success"])
        self.assertEqual(frappe.db.get_value(SUBMISSION, first, "status"), "Pending Review")

        self.assertTrue(self._confirm_link(second)[0]["success"])

        self.assertEqual(
            frappe.db.get_value(SUBMISSION, first, ["status", "superseded_by"], as_dict=True),
            {"status": "Superseded", "superseded_by": second},
        )
        self.assertEqual(frappe.db.get_value(SUBMISSION, second, "status"), "Pending Review")

    def test_supersede_touches_only_pending_rows_of_the_same_email(self):
        from verenigingen.services.member.application import application_record as ar

        other_email = self._unused_email()
        other = self._submit_short(email=other_email)
        self.assertTrue(self._confirm_link(other)[0]["success"])
        unconfirmed = self._submit_short()
        newer = self._submit_short()

        self.assertEqual(ar.supersede_older(self.email, keep=newer), 0, "an Unconfirmed row is not superseded")
        self.assertEqual(frappe.db.get_value(SUBMISSION, other, "status"), "Pending Review")
        self.assertEqual(frappe.db.get_value(SUBMISSION, unconfirmed, "status"), "Unconfirmed")

    def test_a_member_who_became_active_meanwhile_gets_the_refusal(self):
        name = self._submit_short()
        member = self.create_test_member(email=self.email)
        frappe.db.set_value("Member", member.name, {"status": "Active", "application_status": "Approved"})
        reference = self._confirm_link("does-not-exist")

        self.assertEqual(self._confirm_link(name), reference)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Expired")

    def test_a_stored_payload_keeps_the_shape_the_form_produced(self):
        short = self._submit_short()
        self._submit_full(email=(full_email := self._unused_email()))
        full = self._latest_submission(full_email)
        short_row = frappe.db.get_value(SUBMISSION, short, ["source", "payload"], as_dict=True)
        full_row = frappe.db.get_value(SUBMISSION, full, ["source", "payload"], as_dict=True)
        self.assertEqual(short_row.source, "Short Form")
        self.assertIn("membership_type", json.loads(short_row.payload))
        self.assertEqual(full_row.source, "Full Form")
        self.assertEqual(json.loads(full_row.payload)["selected_membership_type"], self.membership_type.name)
