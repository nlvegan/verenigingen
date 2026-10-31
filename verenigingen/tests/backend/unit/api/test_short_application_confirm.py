"""Guest confirm endpoint of the short membership application (/word-lid/bevestig)."""

import json
import random
import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request
from frappe.utils import add_days, get_datetime, now_datetime

from verenigingen.api import short_application as sa
from verenigingen.services.member.application.short_application_confirm import CONFIRM_TOKEN_PURPOSE
from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token
from verenigingen.tests.utils.application_door_fixture import ApplicationDoorMixin
from verenigingen.tests.utils.base import VereningingenUnitTestCase

IBAN = "NL91ABNA0417164300"
SUBMISSION = "Membership Application Submission"
REFUSAL = {"success": False, "message": "This confirmation link is invalid or has expired."}


class TestShortApplicationConfirm(ApplicationDoorMixin, VereningingenUnitTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type()
        # The type's default template stays Annual, so approval falling back to it is visible;
        # the door gets its own Monthly template.
        self.type_template = frappe.db.get_value(
            "Membership Type", self.membership_type.name, "dues_schedule_template"
        )
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", self.type_template, "billing_frequency"), "Annual"
        )
        self.template = self._door_template(self.type_template)
        self.template_rate = frappe.db.get_value("Membership Dues Schedule", self.template, "dues_rate")
        self.door = self._door(monthly_dues_template=self.template)
        self.email = self._new_email()
        self.amount = 7.5
        self._previous_user = frappe.session.user
        self._previous_request = getattr(frappe.local, "request", None)
        self._previous_ip = getattr(frappe.local, "request_ip", None)

    def tearDown(self):
        frappe.local.request = self._previous_request
        frappe.local.request_ip = self._previous_ip
        frappe.set_user(self._previous_user)
        super().tearDown()

    def _door_template(self, type_template):
        template = frappe.copy_doc(frappe.get_doc("Membership Dues Schedule", type_template))
        template.schedule_name = f"Door Monthly {frappe.generate_hash(length=6)}"
        template.update({"billing_frequency": "Monthly", "minimum_amount": 2.5, "dues_rate": 12})
        template.insert()
        self.track_doc("Membership Dues Schedule", template.name)
        return template.name

    def _new_email(self):
        return f"confirm.{frappe.generate_hash(length=8).lower()}@example.org"

    def _confirm_data(self, **overrides):
        data = {
            "first_name": "Anna",
            "tussenvoegsel": "van",
            "last_name": "Berg",
            "email": self.email,
            "mobile_no": "0612345678",
            "address_line1": "Kerkstraat",
            "postal_code": "1234AB",
            "house_number": "12",
            "house_number_addition": "B",
            "city": "Utrecht",
            "country": "Netherlands",
            "frequency": "Monthly",
            "amount": str(self.amount),
            "iban": IBAN,
            "bank_account_name": "A. Berg",
            "magazine_delivery": "Digitaal",
            "birth_year": "1990",
            "consent": "1",
            "website": "",
        }
        data.update(overrides)
        return data

    def _confirm_submit(self, door=None, **overrides):
        """Submit as Guest through the real endpoint; return the submission name."""
        data = self._confirm_data(**overrides)
        frappe.set_user("Guest")
        try:
            response = sa.submit_short_application((door or self.door).name, **data)
        finally:
            frappe.set_user(self._previous_user)
        self.assertTrue(response["success"], response)
        name = frappe.get_all(SUBMISSION, {"email": data["email"].strip().lower()}, pluck="name", order_by="creation desc")[0]
        self.track_doc(SUBMISSION, name)
        return name

    def _confirm(self, name, token=None, method="POST"):
        """Call the endpoint as Guest; return (response, message_log)."""
        if token is None:
            token = generate_guest_return_token(CONFIRM_TOKEN_PURPOSE, name)
        frappe.local.request = Request(EnvironBuilder(method=method).get_environ())
        # rate_limit buckets by IP once a request exists; a fresh one per call keeps reruns from tripping it.
        frappe.local.request_ip = f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
        frappe.local.message_log = []
        frappe.set_user("Guest")
        try:
            response = sa.confirm_short_application(name, token)
        finally:
            frappe.set_user(self._previous_user)
        return response, list(frappe.local.message_log)

    def _members(self, email=None):
        return frappe.get_all("Member", {"email": email or self.email}, pluck="name")

    def _track_members(self):
        for name in self._members():
            self.track_doc("Member", name)

    def _assert_confirmed_without_a_member(self, name):
        row = frappe.db.get_value(SUBMISSION, name, ["status", "confirmed_on", "application_id"], as_dict=True)
        self.assertEqual(row.status, "Pending Review")
        self.assertTrue(row.confirmed_on)
        self.assertTrue(row.application_id)
        self.assertEqual(self._members(), [])

    def test_get_request_confirms_nothing(self):
        name = self._confirm_submit()
        response, _log = self._confirm(name, method="GET")
        self.assertEqual(response, REFUSAL)
        self.assertEqual(self._members(), [])
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Unconfirmed")

    def test_refusals_are_identical(self):
        wrong_token = self._confirm_submit()
        expired = self._confirm_submit(email=self._new_email())
        done = self._confirm_submit(email=self._new_email())
        self._confirm(done)
        frappe.db.set_value(SUBMISSION, expired, "creation", add_days(now_datetime(), -8), update_modified=False)
        members_before = frappe.db.count("Member")

        cases = {
            "wrong token": self._confirm(wrong_token, token="0" * 64),
            "unknown id": self._confirm("does-not-exist"),
            "expired": self._confirm(expired),
            "already confirmed": self._confirm(done),
        }

        reference = cases["wrong token"]
        self.assertEqual(reference[0], REFUSAL)
        for label, outcome in cases.items():
            self.assertEqual(outcome, reference, label)
        self.assertEqual(frappe.db.count("Member"), members_before)
        self.assertEqual(frappe.db.get_value(SUBMISSION, wrong_token, "status"), "Unconfirmed")
        self.assertEqual(frappe.db.get_value(SUBMISSION, expired, "status"), "Expired")

    def test_second_confirm_changes_nothing(self):
        name = self._confirm_submit()
        first, _log = self._confirm(name)
        self.assertTrue(first["success"], first)
        self._assert_confirmed_without_a_member(name)
        before = frappe.db.get_value(SUBMISSION, name, ["application_id", "confirmed_on", "chapter"], as_dict=True)

        second, _log = self._confirm(name)

        self.assertEqual(second, REFUSAL)
        self.assertEqual(
            frappe.db.get_value(SUBMISSION, name, ["application_id", "confirmed_on", "chapter"], as_dict=True),
            before,
        )
        self._assert_confirmed_without_a_member(name)

    def test_door_disabled_after_submit_still_confirms(self):
        name = self._confirm_submit()
        frappe.db.set_value("Membership Application Door", self.door.name, "enabled", 0)
        response, _log = self._confirm(name)
        self.assertTrue(response["success"], response)
        self._assert_confirmed_without_a_member(name)

    def test_member_became_active_meanwhile_gets_identical_refusal_and_expires(self):
        name = self._confirm_submit()
        existing = self.create_test_member(email=self.email)
        frappe.db.set_value("Member", existing.name, {"status": "Active", "application_status": "Approved"})
        emails = frappe.db.count("Email Queue")
        reference, reference_log = self._confirm("does-not-exist")

        response, log = self._confirm(name)

        self.assertEqual((response, log), (reference, reference_log))
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Expired")
        self.assertEqual(self._members(), [existing.name])
        self.assertEqual(frappe.db.get_value("Member", existing.name, "application_door"), None)
        self.assertEqual(frappe.db.count("Email Queue"), emails)

    def _repoint_door_to_another_type(self):
        """What an admin can do between submit and confirm: give the door another type and template."""
        other_type = self.create_test_membership_type()
        other_template = frappe.db.get_value("Membership Type", other_type.name, "dues_schedule_template")
        frappe.db.set_value("Membership Dues Schedule", other_template, "billing_frequency", "Monthly")
        frappe.db.set_value(
            "Membership Application Door",
            self.door.name,
            {"membership_type": other_type.name, "monthly_dues_template": other_template},
        )
        return other_type

    def test_door_repointed_after_submit_keeps_the_submitted_type_and_template(self):
        name = self._confirm_submit()
        other_type = self._repoint_door_to_another_type()

        response, _log = self._confirm(name)

        self.assertTrue(response["success"], response)
        self.assertNotEqual(other_type.name, self.membership_type.name)
        row = frappe.db.get_value(SUBMISSION, name, ["membership_type", "payload"], as_dict=True)
        self.assertEqual(row.membership_type, self.membership_type.name)
        self.assertEqual(json.loads(row.payload)["selected_dues_schedule"], self.template)

    def _assert_stale_template_refused(self, make_stale):
        name = self._confirm_submit(email=self._new_email())
        email = frappe.db.get_value(SUBMISSION, name, "email")
        make_stale(name)
        reference = self._confirm("does-not-exist")
        addresses = frappe.db.count("Address", {"email_id": email})

        outcome = self._confirm(name)

        self.assertEqual(outcome, reference)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Expired")
        self.assertEqual(self._members(email), [])
        self.assertEqual(frappe.db.count("Address", {"email_id": email}), addresses)

    def test_template_no_longer_valid_gets_identical_refusal_and_expires(self):
        def untemplate(_name):
            frappe.db.set_value("Membership Dues Schedule", self.template, "is_template", 0)

        def move_to_other_type(_name):
            other_type = self.create_test_membership_type()
            frappe.db.set_value("Membership Dues Schedule", self.template, "membership_type", other_type.name)

        def change_frequency(_name):
            frappe.db.set_value("Membership Dues Schedule", self.template, "billing_frequency", "Annual")

        def delete_template(name):
            # The template is linked from the door and its type; deletion is simulated on the payload.
            payload = json.loads(frappe.db.get_value(SUBMISSION, name, "payload"))
            payload["selected_dues_schedule"] = f"Deleted {frappe.generate_hash(length=8)}"
            frappe.db.set_value(SUBMISSION, name, "payload", json.dumps(payload))

        for label, make_stale in (
            ("deleted", delete_template),
            ("untemplated", untemplate),
            ("moved to another type", move_to_other_type),
            ("frequency changed", change_frequency),
        ):
            with self.subTest(label):
                saved = frappe.db.get_value(
                    "Membership Dues Schedule",
                    self.template,
                    ["is_template", "membership_type", "billing_frequency"],
                    as_dict=True,
                )
                try:
                    self._assert_stale_template_refused(make_stale)
                finally:
                    frappe.db.set_value("Membership Dues Schedule", self.template, saved)

    def test_template_edited_to_another_frequency_after_the_door_was_saved_is_refused_at_submit(self):
        """The door checks slot frequency only when it is saved; the template can still be edited.
        A Monthly choice must never reach an Annual template (it would bill the amount yearly)."""
        # Straight to the column, as an import would: saving the template is refused while a door
        # uses it, so the submit check is what stops this route.
        frappe.db.set_value("Membership Dues Schedule", self.template, "billing_frequency", "Annual")
        data = self._confirm_data()
        frappe.set_user("Guest")
        try:
            response = sa.submit_short_application(self.door.name, **data)
        finally:
            frappe.set_user(self._previous_user)
        self.assertEqual(response, {"success": False, "message": "This payment frequency is not available."})
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)

    def _try_to_make_the_template_annual(self):
        self._repoint_door_to_another_type()  # so only the applicant still uses the template
        template = frappe.get_doc("Membership Dues Schedule", self.template)
        template.billing_frequency = "Annual"
        template.save()

    def test_a_template_a_pending_applicant_chose_cannot_change_frequency(self):
        """Approval reads the template's frequency when it runs, days after confirm: the template
        must not change period under an application still waiting for it. The application is a
        submission now (it was the Member's application_dues_schedule before #1765)."""
        name = self._confirm_submit()
        self.assertTrue(self._confirm(name)[0]["success"])
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")
        with self.assertRaisesRegex(frappe.ValidationError, "pending application"):
            self._try_to_make_the_template_annual()

    def test_an_unconfirmed_or_replaced_application_does_not_pin_the_template(self):
        """Control: anyone can submit anonymously, so only a confirmed, still-waiting application may block
        an administrator."""
        unconfirmed = self._confirm_submit()
        replaced = self._confirm_submit()
        self.assertTrue(self._confirm(replaced)[0]["success"])
        self.assertTrue(self._confirm(self._confirm_submit())[0]["success"])
        self.assertEqual(frappe.db.get_value(SUBMISSION, replaced, "status"), "Superseded")
        self.assertEqual(frappe.db.get_value(SUBMISSION, unconfirmed, "status"), "Unconfirmed")
        frappe.db.set_value(SUBMISSION, frappe.db.get_value(SUBMISSION, replaced, "superseded_by"), "status", "Approved")
        self._try_to_make_the_template_annual()  # nothing Pending Review uses it: no refusal

    def _pending_application_on_the_template(self):
        name = self._confirm_submit()
        self.assertTrue(self._confirm(name)[0]["success"])
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")
        return name

    def test_template_frequency_change_refused_while_application_pending(self):
        """The guard reads the application, not a Member: a Pending Review row naming the template
        blocks the change, and the same row stops blocking once it is decided."""
        name = self._pending_application_on_the_template()
        with self.assertRaisesRegex(frappe.ValidationError, f"pending application \\({name}\\)"):
            self._try_to_make_the_template_annual()

    def _assert_a_decided_application_does_not_pin_the_template(self, decision):
        """Control with a real row: the SAME application that blocks while Pending Review, moved through the
        real status transition, no longer blocks."""
        name = self._pending_application_on_the_template()
        with self.assertRaises(frappe.ValidationError):
            self._try_to_make_the_template_annual()
        frappe.get_doc(SUBMISSION, name).set_status(decision)
        self._try_to_make_the_template_annual()  # no refusal
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", self.template, "billing_frequency"), "Annual"
        )

    def test_an_approved_application_does_not_pin_the_template(self):
        self._assert_a_decided_application_does_not_pin_the_template("Approved")

    def test_a_rejected_application_does_not_pin_the_template(self):
        self._assert_a_decided_application_does_not_pin_the_template("Rejected")

    def test_confirming_hands_out_a_status_link_that_opens_the_status_page(self):
        from verenigingen.templates.pages.application_status import _application_for

        name = self._confirm_submit()
        response = self._confirm(name)[0]

        self.assertTrue(response["success"], response)
        path, query = response["status_url"].split("?", 1)
        self.assertEqual(path, "/application_status")
        params = dict(pair.split("=", 1) for pair in query.split("&"))
        self.assertEqual(params["id"], name)
        application = _application_for(params["id"], params["token"])
        self.assertEqual(application.status, "Pending Review")
        self.assertEqual(application.application_id, frappe.db.get_value(SUBMISSION, name, "application_id"))
        self.assertIsNone(_application_for(params["id"], "0" * 64))

    def test_a_refused_confirmation_hands_out_no_status_link(self):
        response, _log = self._confirm(self._confirm_submit(), token="0" * 64)
        self.assertEqual(response, REFUSAL)

    def test_housemate_confirms_without_amount_or_consent(self):
        door = self._door(form_shape="Housemate", monthly_dues_template=None)
        name = self._confirm_submit(door=door, housemate_of_name="Piet Berg", housemate_confirmed="1", amount="", iban="")

        response, _log = self._confirm(name)

        self.assertTrue(response["success"], response)
        self._assert_confirmed_without_a_member(name)
        payload = json.loads(frappe.db.get_value(SUBMISSION, name, "payload"))
        self.assertEqual(payload["housemate_of_name"], "Piet Berg")
