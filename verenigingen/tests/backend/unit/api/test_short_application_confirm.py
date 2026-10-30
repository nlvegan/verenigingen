"""Guest confirm endpoint of the short membership application (/word-lid/bevestig)."""

import json
import random
import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request
from frappe.utils import add_days, get_datetime, now_datetime

from verenigingen.api import short_application as sa
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
            token = sa.generate_guest_return_token(sa.CONFIRM_TOKEN_PURPOSE, name)
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

    def _reason(self):
        reason = frappe.get_doc(
            {"doctype": "Membership Join Reason", "reason": f"Test {frappe.generate_hash(length=8)}", "enabled": 1}
        ).insert()
        self.track_doc("Membership Join Reason", reason.name)
        return reason.name

    def test_valid_post_creates_one_pending_member_with_answers(self):
        reason = self._reason()
        name = self._confirm_submit(join_reasons=[reason])
        payload = json.loads(frappe.db.get_value(SUBMISSION, name, "payload"))
        self.assertNotEqual(self.amount, self.template_rate, "control: the amount must differ from the template")

        response, _log = self._confirm(name)

        self.assertEqual(response["success"], True, response)
        self._track_members()
        members = self._members()
        self.assertEqual(len(members), 1)
        member = frappe.get_doc("Member", members[0])
        self.assertEqual(member.application_status, "Pending")
        self.assertEqual(payload["membership_type"], self.membership_type.name)
        self.assertEqual(member.selected_membership_type, self.membership_type.name)
        self.assertEqual(member.application_dues_schedule, self.door.monthly_dues_template)
        self.assertEqual(member.dues_rate, payload["amount"])
        self.assertEqual(member.dues_rate, self.amount)
        self.assertEqual(member.tussenvoegsel, "van")
        self.assertEqual(member.contact_number, "0612345678")
        self.assertEqual(member.payment_method, "SEPA Direct Debit")
        self.assertEqual(member.magazine_delivery, "Digitaal")
        self.assertEqual(member.birth_year, 1990)
        self.assertEqual([row.join_reason for row in member.join_reasons], [reason])
        self.assertEqual(member.application_door, self.door.name)
        self.assertEqual(member.application_consent_version, payload["consent_text_version"])
        self.assertEqual(get_datetime(member.application_consent_at), get_datetime(payload["consent_given_at"]))
        address = frappe.get_doc("Address", member.primary_address)
        self.assertEqual(address.address_line1, "Kerkstraat 12 B")
        row = frappe.db.get_value(SUBMISSION, name, ["status", "member", "confirmed_on"], as_dict=True)
        self.assertEqual((row.status, row.member), ("Pending Review", member.name))
        self.assertTrue(row.confirmed_on)

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
        self._track_members_of(done)
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

    def _track_members_of(self, submission):
        member = frappe.db.get_value(SUBMISSION, submission, "member")
        if member:
            self.track_doc("Member", member)

    def test_second_confirm_creates_nothing(self):
        name = self._confirm_submit()
        first, _log = self._confirm(name)
        self.assertTrue(first["success"], first)
        self._track_members()
        self.assertEqual(len(self._members()), 1)
        addresses = frappe.db.count("Address", {"email_id": self.email})

        second, _log = self._confirm(name)

        self.assertEqual(second, REFUSAL)
        self.assertEqual(len(self._members()), 1)
        self.assertEqual(frappe.db.count("Address", {"email_id": self.email}), addresses)

    def test_second_submission_same_email_does_not_duplicate_member(self):
        first = self._confirm_submit()
        second = self._confirm_submit()
        self.assertNotEqual(first, second)
        self.assertTrue(self._confirm(first)[0]["success"])
        self._track_members()
        self.assertEqual(len(self._members()), 1, "control: the first confirm created the Member")

        response, _log = self._confirm(second)

        self.assertTrue(response["success"], response)
        self.assertEqual(len(self._members()), 1)
        self.assertEqual(frappe.db.get_value(SUBMISSION, second, "member"), self._members()[0])

    def test_door_disabled_after_submit_still_confirms(self):
        name = self._confirm_submit()
        frappe.db.set_value("Membership Application Door", self.door.name, "enabled", 0)
        response, _log = self._confirm(name)
        self.assertTrue(response["success"], response)
        self._track_members()
        self.assertEqual(len(self._members()), 1)

    def _stale_template(self):
        """Another Annual template of the same type, to seed a stale application_dues_schedule."""
        stale = frappe.copy_doc(frappe.get_doc("Membership Dues Schedule", self.template))
        stale.schedule_name = f"Stale {frappe.generate_hash(length=6)}"
        stale.billing_frequency = "Annual"
        stale.insert()
        self.track_doc("Membership Dues Schedule", stale.name)
        return stale.name

    def _rejected_member(self, door):
        existing = self.create_test_member(email=self.email)
        frappe.db.set_value(
            "Member",
            existing.name,
            {
                "status": "Pending",
                "application_status": "Rejected",
                "application_door": door.name,
                "application_dues_schedule": self._stale_template(),
                "dues_rate": 99,
                "application_custom_fee": 99,
                "fee_override_reason": "stale override",
                "fee_override_date": "2020-01-01",
            },
        )
        return existing

    def test_reapplication_updates_existing_member(self):
        old_door = self._door(monthly_dues_template=self.template)
        existing = self._rejected_member(old_door)
        name = self._confirm_submit()

        response, _log = self._confirm(name)

        self.assertTrue(response["success"], response)
        self.assertEqual(self._members(), [existing.name])
        member = frappe.get_doc("Member", existing.name)
        self.assertEqual(member.application_status, "Pending")
        self.assertEqual(member.application_door, self.door.name)
        self.assertEqual(member.application_dues_schedule, self.door.monthly_dues_template)
        self.assertEqual(member.dues_rate, self.amount)
        self.assertEqual(member.application_custom_fee, self.amount)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "member"), existing.name)

    def test_reapplication_keeps_member_fields_the_short_form_does_not_ask(self):
        # Both directions, so neither "always opt out" nor "always opt in" passes.
        for label, kept in (
            (
                "opted out, volunteering",
                {"accepts_optional_communications": 0, "interested_in_volunteering": 1, "pronouns": "zij/haar"},
            ),
            (
                "opted in, not volunteering",
                {"accepts_optional_communications": 1, "interested_in_volunteering": 0, "pronouns": "hij/hem"},
            ),
        ):
            with self.subTest(label):
                self.email = self._new_email()
                existing = self._rejected_member(self.door)
                kept = dict(kept, birth_date="1985-04-12", middle_name="Maria")
                frappe.db.set_value("Member", existing.name, dict(kept))  # set_value adds modified to its dict
                name = self._confirm_submit()

                response, _log = self._confirm(name)

                self.assertTrue(response["success"], response)
                member = frappe.db.get_value("Member", existing.name, list(kept), as_dict=True)
                member.birth_date = str(member.birth_date)
                self.assertEqual(dict(member), kept)

    def test_new_member_from_short_form_is_opted_out_of_optional_email(self):
        name = self._confirm_submit()

        response, _log = self._confirm(name)

        self.assertTrue(response["success"], response)
        self._track_members()
        self.assertEqual(
            frappe.db.get_value("Member", self._members()[0], "accepts_optional_communications"), 0
        )

    def test_housemate_reapplication_clears_the_old_fee(self):
        door = self._door(form_shape="Housemate", monthly_dues_template=None)
        existing = self._rejected_member(door)
        name = self._confirm_submit(door=door, housemate_of_name="Piet Berg", housemate_confirmed="1", amount="", iban="")

        response, _log = self._confirm(name)

        self.assertTrue(response["success"], response)
        member = frappe.get_doc("Member", existing.name)
        self.assertFalse(member.application_dues_schedule)
        self.assertFalse(member.application_custom_fee)
        self.assertFalse(member.dues_rate)
        self.assertFalse(member.fee_override_reason)
        self.assertFalse(member.fee_override_date)

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

    def test_creation_failure_rolls_back_and_keeps_submission_unconfirmed(self):
        name = self._confirm_submit()
        payload = json.loads(frappe.db.get_value(SUBMISSION, name, "payload"))
        # Fails at the final Member save, after the Address and Member rows were written.
        payload["referral_source"] = "No such referral source"
        frappe.db.set_value(SUBMISSION, name, "payload", json.dumps(payload))
        errors = frappe.db.count("Error Log")

        response, _log = self._confirm(name)

        self.assertEqual(response, REFUSAL)
        # Helper errors (frappe.throw queues its text before raising) must not reach the guest.
        self.assertEqual(_log, self._confirm(name, token="0" * 64)[1])
        self.assertEqual(_log, [])
        self.assertEqual(self._members(), [])
        self.assertEqual(frappe.db.count("Address", {"email_id": self.email}), 0, "address must roll back too")
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Unconfirmed")
        self.assertEqual(frappe.db.count("Error Log"), errors + 1)

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
        self._track_members()
        member = frappe.get_doc("Member", self._members()[0])
        self.assertNotEqual(other_type.name, self.membership_type.name)
        self.assertEqual(member.selected_membership_type, self.membership_type.name)
        self.assertEqual(member.application_dues_schedule, self.template)

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

    def test_a_template_a_pending_applicant_chose_cannot_change_frequency(self):
        """Approval reads the template's frequency when it runs, days after confirm: the template
        must not change period under an application still waiting for it."""
        name = self._confirm_submit()
        response, _log = self._confirm(name)
        self.assertTrue(response["success"], response)
        self._track_members()
        member = frappe.db.get_value(
            "Member", self._members()[0], ["application_status", "application_dues_schedule"], as_dict=True
        )
        self.assertEqual((member.application_status, member.application_dues_schedule), ("Pending", self.template))
        self._repoint_door_to_another_type()  # so only the applicant still uses the template
        template = frappe.get_doc("Membership Dues Schedule", self.template)
        template.billing_frequency = "Annual"
        with self.assertRaisesRegex(frappe.ValidationError, "pending application"):
            template.save()

    def test_lost_savepoint_through_the_endpoint_leaves_no_half_written_rows(self):
        """@handle_api_error turns the re-raise into a returned error, so the request still ends in a
        commit: the half-written rows must already be gone by then."""
        from unittest.mock import patch

        from verenigingen.services.member.application import short_application_confirm as sac

        name = self._confirm_submit()
        savepoints = []
        real_savepoint = frappe.db.savepoint

        def record_savepoint(save_point):
            savepoints.append(save_point)
            return real_savepoint(save_point)

        def write_address_then_lose_savepoint(*_args):
            # A raw row stands in for whatever the helpers had written when the savepoint went.
            address = frappe.get_doc(
                {
                    "doctype": "Address",
                    "address_title": "Half written",
                    "address_line1": "Kerkstraat 12",
                    "city": "Utrecht",
                    "country": "Netherlands",
                    "email_id": self.email,
                }
            )
            address.name = f"Half written {frappe.generate_hash(length=8)}"
            address.db_insert()
            frappe.db.sql(f"RELEASE SAVEPOINT {savepoints[-1]}")
            raise ValueError("write failed after the savepoint was lost")

        self.expectErrorLog("Savepoint rollback skipped")
        with patch.object(frappe.db, "savepoint", side_effect=record_savepoint), patch.object(
            sac, "_write_member", side_effect=write_address_then_lose_savepoint
        ):
            response, _log = self._confirm(name)
        self.assertFalse(response.get("success"), response)
        self.assertEqual(len(savepoints), 1, "control: the code under test took exactly one savepoint")
        self.assertEqual(frappe.db.count("Address", {"email_id": self.email}), 0)
        self.assertEqual(self._members(), [])

    def test_reapplication_with_a_blank_mobile_keeps_the_members_number(self):
        existing = self._rejected_member(self.door)
        frappe.db.set_value("Member", existing.name, "contact_number", "0699999999")
        name = self._confirm_submit(mobile_no="")

        response, _log = self._confirm(name)

        self.assertTrue(response["success"], response)
        self.assertEqual(frappe.db.get_value("Member", existing.name, "contact_number"), "0699999999")

    def test_reapplication_with_a_new_mobile_replaces_the_members_number(self):
        existing = self._rejected_member(self.door)
        frappe.db.set_value("Member", existing.name, "contact_number", "0699999999")
        name = self._confirm_submit(mobile_no="0611111111")

        response, _log = self._confirm(name)

        self.assertTrue(response["success"], response)
        self.assertEqual(frappe.db.get_value("Member", existing.name, "contact_number"), "0611111111")

    def test_lost_savepoint_reraises_instead_of_refusing(self):
        """If the savepoint is gone (a nested commit or a deadlock), nothing was rolled back, so a
        refusal would claim a clean failure over half-written rows. The real error must surface."""
        from unittest.mock import patch

        from verenigingen.services.member.application import short_application_confirm as sac

        name = self._confirm_submit()
        submission = frappe.get_doc(SUBMISSION, name)
        savepoints = []
        real_savepoint = frappe.db.savepoint

        def record_savepoint(save_point):
            savepoints.append(save_point)
            return real_savepoint(save_point)

        def write_then_lose_savepoint(*_args):
            frappe.db.sql(f"RELEASE SAVEPOINT {savepoints[-1]}")
            raise ValueError("write failed after the savepoint was lost")

        self.expectErrorLog("Savepoint rollback skipped")
        with patch.object(frappe.db, "savepoint", side_effect=record_savepoint), patch.object(
            sac, "_write_member", side_effect=write_then_lose_savepoint
        ):
            with self.assertRaisesRegex(ValueError, "savepoint was lost"):
                sac._create_member_with_savepoint(submission, self.door, json.loads(submission.payload), None)
        self.assertEqual(len(savepoints), 1, "control: the code under test took exactly one savepoint")

    def test_approval_creates_monthly_schedule_at_chosen_amount(self):
        from verenigingen.api.membership_application_review import approve_membership_application

        name = self._confirm_submit()
        self.assertTrue(self._confirm(name)[0]["success"])
        self._track_members()
        member_name = self._members()[0]
        self.assertNotEqual(self.amount, self.template_rate, "control: the amount must differ from the template")

        self.assertEqual(frappe.session.user, "Administrator", "the harness runs tests as Administrator")
        result = approve_membership_application(member_name=member_name)

        self.assertTrue(result.get("success"), result)
        schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "is_template": 0},
            ["billing_frequency", "dues_rate", "template_reference"],
            as_dict=True,
        )
        self.assertNotEqual(self.template, self.type_template, "control: the door's template is not the default")
        self.assertEqual(schedule.template_reference, self.door.monthly_dues_template)
        self.assertEqual(schedule.billing_frequency, "Monthly")
        self.assertEqual(schedule.dues_rate, self.amount)

    def test_housemate_confirms_without_amount_or_consent(self):
        door = self._door(form_shape="Housemate", monthly_dues_template=None)
        name = self._confirm_submit(door=door, housemate_of_name="Piet Berg", housemate_confirmed="1", amount="", iban="")

        response, _log = self._confirm(name)

        self.assertTrue(response["success"], response)
        self._track_members()
        member = frappe.get_doc("Member", self._members()[0])
        self.assertEqual(member.housemate_of_name, "Piet Berg")
        self.assertEqual(member.application_door, door.name)
        self.assertFalse(member.application_dues_schedule)
        self.assertFalse(member.application_custom_fee)
        self.assertFalse(member.application_consent_at)

    def test_pending_chapter_membership_is_created_for_a_guest_without_noise(self):
        self.create_test_chapter(postal_codes="1200-1299", published=1)
        name = self._confirm_submit()
        chapter_errors = frappe.db.count("Error Log", {"method": ["like", "Chapter%"]})

        response, log = self._confirm(name)

        self.assertTrue(response["success"], response)
        self._track_members()
        self.assertEqual(frappe.db.count("Error Log", {"method": ["like", "Chapter%"]}), chapter_errors)
        rows = frappe.get_all("Chapter Member", {"member": self._members()[0]}, ["status", "parent"])
        self.assertEqual([row.status for row in rows], ["Pending"])
        self.assertEqual(log, [])
