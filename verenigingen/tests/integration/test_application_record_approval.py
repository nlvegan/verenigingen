"""#1765 task 4: approving an application creates (or updates) the Member.

Everything is driven through the real flow: submit_application as Guest -> the emailed confirm link
(POST) -> approve_application as a staff user. Probe shortcuts, stated: test_member_became_active_meanwhile
sets the Member Active with a db write to stand in for "became Active by some other path", so that test
proves the refusal, not that the state is reachable that way; the oracle test seeds a board seat through
the harness's create_test_board_member.
"""

import json
import secrets
from unittest.mock import patch

import frappe
from frappe.utils import add_days, today
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.api import short_application as sa
from verenigingen.api.membership_application import submit_application
from verenigingen.api.membership_application_review import approve_application
from verenigingen.services.member.application.application_record import confirm_application
from verenigingen.services.member.application.short_application_confirm import CONFIRM_TOKEN_PURPOSE
from verenigingen.services.member.lifecycle.member_status_notification_service import (
    MemberStatusNotificationService,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.termination_request import execute_real_termination
from verenigingen.tests.utils.application_door_fixture import ApplicationDoorMixin
from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token

SUBMISSION = "Membership Application Submission"
EMISSION = (
    "verenigingen.services.member.lifecycle.member_event_emission_service.MemberEventEmissionService"
)
IBAN = "NL91ABNA0417164300"
OTHER_IBAN = "NL02ABNA0123456789"


class ApprovalCase(ApplicationDoorMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        run = frappe.generate_hash(length=6)
        self.chapter = self.factory.ensure_test_chapter(
            f"Test Chapter {run}", {"short_name": "TST", "country": "Netherlands"}
        )
        self.membership_type = self.factory.ensure_membership_type(
            f"Approval Type {run}", {"amount": 25.00, "billing_period": "Monthly"}
        )
        self._prepare_approval_environment()
        self.email = self._fresh_applicant_email()
        self._previous_request = getattr(frappe.local, "request", None)
        self._previous_ip = getattr(frappe.local, "request_ip", None)

    def tearDown(self):
        frappe.local.request = self._previous_request
        frappe.local.request_ip = self._previous_ip
        super().tearDown()

    def _prepare_approval_environment(self):
        if not frappe.db.exists("Item Group", "Memberships"):
            frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Memberships",
                    "parent_item_group": "All Item Groups",
                    "is_group": 0,
                }
            ).insert()
        self.membership_type.get_or_create_membership_item()
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        self.admin_user = self.create_test_user_with_roles(
            email=f"appr.admin.{frappe.generate_hash(length=6)}@example.com",
            roles=["System Manager", "Verenigingen Administrator"],
        )
        grant_matching_role_profiles(self.admin_user.email, "Verenigingen Administrator")

    def _fresh_applicant_email(self):
        return f"appr.{frappe.generate_hash(length=8).lower()}@example.org"

    def _full_form_data(self, **overrides):
        data = {
            "first_name": "Appr",
            "last_name": f"Applicant{frappe.generate_hash(length=6)}",
            "email": self.email,
            "birth_date": add_days(today(), -365 * 30),
            "contact_number": "+31612345678",
            "address_line1": "123 Test Street",
            "city": "Amsterdam",
            "postal_code": "1234AB",
            "country": "Netherlands",
            "selected_membership_type": self.membership_type.name,
            "selected_chapter": self.chapter.name,
        }
        data.update(overrides)
        return data

    def _request_from_fresh_ip(self, method="POST"):
        """A request from a fresh address: the guest endpoints' limiters key on the client IP, and their
        counters outlive a test run (an hour), so a fixed address would be refused after a few runs."""
        ip = f"10.{secrets.randbelow(256)}.{secrets.randbelow(256)}.{1 + secrets.randbelow(254)}"  # not `random`: the runner seeds it
        frappe.local.request_ip = ip
        frappe.local.request = Request(EnvironBuilder(method=method, environ_overrides={"REMOTE_ADDR": ip}).get_environ())

    def _stage_and_confirm(self, **overrides) -> str:
        """Submit the full form as Guest, then follow the emailed link as a POST."""
        data = self._full_form_data(**overrides)
        email = data["email"].strip().lower()
        previous = frappe.session.user
        self._request_from_fresh_ip()
        frappe.set_user("Guest")
        try:
            response = submit_application(**data)
        finally:
            frappe.set_user(previous)
        self.assertTrue(response["success"], response)
        name = frappe.get_all(SUBMISSION, {"email": email, "status": "Unconfirmed"}, pluck="name")[0]
        self.track_doc(SUBMISSION, name)
        token = generate_guest_return_token(CONFIRM_TOKEN_PURPOSE, name)
        self._request_from_fresh_ip()
        frappe.set_user("Guest")
        try:
            confirmed = confirm_application(name, token)
        finally:
            frappe.set_user(previous)
        self.assertTrue(confirmed["success"], confirmed)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")
        return name

    def _stage_short_and_confirm(self, **overrides) -> str:
        """The short form: it never asks birth date or (optionally) a mobile number."""
        template = frappe.db.get_value(
            "Membership Dues Schedule", {"is_template": 1, "membership_type": self.membership_type.name}, "name"
        )
        frappe.db.set_value("Membership Dues Schedule", template, {"minimum_amount": 2.5, "billing_frequency": "Monthly"})
        door = self._door(monthly_dues_template=template)
        data = {
            "first_name": "Anna", "last_name": "Berg", "email": self.email, "address_line1": "Kerkstraat",
            "postal_code": "1234AB", "house_number": "12", "city": "Utrecht", "country": "Netherlands",
            "frequency": "Monthly", "amount": "7.50", "iban": IBAN, "bank_account_name": "A. Berg",
            "consent": "1", "leave_this_empty": "",
        }
        data.update(overrides)
        previous = frappe.session.user
        self._request_from_fresh_ip()
        frappe.set_user("Guest")
        try:
            response = sa.submit_short_application(door.name, **data)
        finally:
            frappe.set_user(previous)
        self.assertTrue(response["success"], response)
        name = frappe.get_all(SUBMISSION, {"email": self.email, "status": "Unconfirmed"}, pluck="name")[0]
        self.track_doc(SUBMISSION, name)
        token = generate_guest_return_token(CONFIRM_TOKEN_PURPOSE, name)
        self._request_from_fresh_ip()
        frappe.set_user("Guest")
        try:
            confirmed = sa.confirm_short_application(name, token)
        finally:
            frappe.set_user(previous)
        self.assertTrue(confirmed["success"], confirmed)
        return name

    def _approve_as(self, name, user=None, send_mail=False, **kwargs):
        kwargs.setdefault("create_invoice", False)
        if send_mail:  # let the mail reach the Email Queue so a test can read it
            with self.as_user(user or self.admin_user.email):
                return approve_application(name, **kwargs)
        with self.as_user(user or self.admin_user.email):
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch("frappe.sendmail"):
                return approve_application(name, **kwargs)

    def _voluntarily_quit_member_with_iban(self, **fields):
        """A voluntarily-Quit member through the real termination service."""
        member = self.create_test_member(email=self.email, iban=IBAN, **fields)
        execute_real_termination(self, member.name, today())
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Quit")
        return member


class TestApproveApplication(ApprovalCase):
    def test_approve_new_applicant_creates_active_member(self):
        name = self._stage_and_confirm()
        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 0)

        result = self._approve_as(name, create_invoice=True)

        self.assertTrue(result["success"], result)
        members = frappe.get_all(
            "Member", {"email": self.email}, ["name", "status", "application_status", "application_id"]
        )
        self.assertEqual(len(members), 1)
        member = members[0]
        self.assertEqual((member.status, member.application_status), ("Active", "Approved"))
        application = frappe.db.get_value(
            SUBMISSION, name, ["application_id", "status", "member"], as_dict=True
        )
        self.assertTrue(application.application_id)
        self.assertEqual(member.application_id, application.application_id)
        self.assertEqual((application.status, application.member), ("Approved", member.name))
        self.assertEqual(
            frappe.db.count("Membership", {"member": member.name, "docstatus": 1}), 1, "one submitted Membership"
        )
        self.assertEqual(
            frappe.db.get_value(
                "Chapter Member", {"parent": self.chapter.name, "member": member.name}, "status"
            ),
            "Active",
        )

    def test_approve_reapplication_applies_supplied_fields(self):
        member = self.create_test_member(email=self.email, iban=IBAN)
        member.reload()
        # What the member's own first approval left behind: an active history row for IBAN A.
        member.append("iban_history", {"iban": member.iban, "bank_account_name": "Old Holder", "from_date": today(), "is_active": 1})
        member.save()
        member.reload()
        execute_real_termination(self, member.name, today())
        member.reload()
        new_last_name = f"Renamed{frappe.generate_hash(length=5)}"
        name = self._stage_and_confirm(last_name=new_last_name, iban=OTHER_IBAN, bank_account_name="Renamed Holder", payment_method="SEPA Direct Debit")

        self._approve_as(name)

        member.reload()
        self.assertEqual(member.iban.replace(" ", ""), OTHER_IBAN)  # Member formats it in groups
        self.assertEqual(member.last_name, new_last_name)
        rows = {row.iban.replace(" ", ""): row for row in member.iban_history}
        self.assertEqual(rows[IBAN].is_active, 0)
        self.assertTrue(rows[IBAN].to_date)
        self.assertEqual(rows[OTHER_IBAN].is_active, 1)
        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 1)

    def test_blank_field_keeps_member_value(self):
        birth_date = add_days(today(), -365 * 41)
        member = self._voluntarily_quit_member_with_iban(contact_number="+31699999999", birth_date=birth_date)
        name = self._stage_short_and_confirm()  # sends no birth_date, no mobile_no

        self._approve_as(name)

        member.reload()
        self.assertEqual(member.contact_number, "+31699999999")
        self.assertEqual(str(member.birth_date), str(birth_date))

    def test_protected_fields_not_written(self):
        """Every protected key is IN the stored payload (fixture: the payload is edited after staging, as a
        tampered guest request would carry them), and every assertion is on a value the write could change."""
        member = self.create_test_member(email=self.email, iban=IBAN)
        member.reload()
        execute_real_termination(self, member.name, today())
        name = self._stage_and_confirm()
        hostile = {
            "email": "other@example.org",
            "status": "Banned",
            "application_status": "Rejected",
            "user": "Administrator",
            "customer": "Somebody Else",
            "member_id": "FORGED-ID",
            "payment_reference": "FORGED-REF",
            "dues_rate": 9999,
            "fee_override_reason": "forged",
        }
        payload = json.loads(frappe.db.get_value(SUBMISSION, name, "payload"))
        payload.update(hostile)
        frappe.db.set_value(SUBMISSION, name, "payload", json.dumps(payload))  # fixture: payload as staged
        before = frappe.db.get_value("Member", member.name, ["user", "customer", "member_id", "payment_reference"], as_dict=True)

        self._approve_as(name)

        after = frappe.db.get_value(
            "Member",
            member.name,
            ["email", "status", "application_status", "user", "customer", "member_id", "payment_reference", "dues_rate"],
            as_dict=True,
        )
        self.assertEqual(after.email, self.email)
        self.assertEqual((after.status, after.application_status), ("Active", "Approved"))
        for field in ("user", "customer", "member_id", "payment_reference"):
            self.assertEqual(after[field], before[field], field)
            self.assertNotEqual(after[field], hostile[field], field)
        self.assertNotEqual(after.dues_rate, 9999)

    def test_member_became_active_meanwhile_refused(self):
        member = self._voluntarily_quit_member_with_iban()
        name = self._stage_and_confirm()
        # Probe shortcut: a db write stands in for "some other path made the Member Active".
        frappe.db.set_value("Member", member.name, {"status": "Active", "application_status": "Approved"})

        with self.assertRaises(frappe.ValidationError):
            self._approve_as(name)

        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")

    def test_failure_leaves_nothing(self):
        """_create_membership_invoice raises frappe.ValidationError. Read of the call path: it is called from
        MembershipCreationService.create_membership_on_approval (step 5), whose `except Exception` re-throws
        as ValidationError; _approve_membership_application_locked calls it with no try, and nothing between
        there and approve_application's savepoint swallows. No nested commit sits on that path (the
        savepoint rollback would otherwise return False and fall back to a full rollback)."""
        name = self._stage_and_confirm()
        before = {dt: frappe.db.count(dt) for dt in ("Member", "Address", "Customer", "Contact")}
        target = "verenigingen.services.member.approval.membership_creation_service.MembershipCreationService._create_membership_invoice"

        # Mock justified: injected failure at the invoice step, below the code under test
        with patch(target, side_effect=frappe.ValidationError("invoice boom")):
            with self.assertRaises(frappe.ValidationError):
                self._approve_as(name, create_invoice=True)

        self.assertEqual(before, {dt: frappe.db.count(dt) for dt in before})
        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 0)
        self.assertEqual(frappe.db.count("Address", {"email_id": self.email}), 0)
        self.assertEqual(frappe.db.count("Customer", {"email_id": self.email}), 0)
        self.assertEqual(frappe.db.count("Contact", {"email_id": self.email}), 0)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")

    def test_failed_approval_of_a_reapplicant_restores_the_member(self):
        """Same injection point as test_failure_leaves_nothing (below _approve_membership_application_locked,
        nothing between it and the savepoint swallows). The Quit member must come back as it was."""
        member = self._voluntarily_quit_member_with_iban()
        old_last_name = frappe.db.get_value("Member", member.name, "last_name")
        name = self._stage_and_confirm(last_name=f"Renamed{frappe.generate_hash(length=5)}", iban=OTHER_IBAN, bank_account_name="Other Holder", payment_method="SEPA Direct Debit")
        target = "verenigingen.services.member.approval.membership_creation_service.MembershipCreationService._create_membership_invoice"

        # Mock justified: injected failure at the invoice step, below the code under test
        with patch(target, side_effect=frappe.ValidationError("invoice boom")):
            with self.assertRaises(frappe.ValidationError):
                self._approve_as(name, create_invoice=True)

        after = frappe.db.get_value("Member", member.name, ["status", "iban", "last_name", "application_status"], as_dict=True)
        self.assertEqual(after.status, "Quit")
        self.assertEqual(after.iban.replace(" ", ""), IBAN)
        self.assertEqual(after.last_name, old_last_name)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, ["status", "member"], as_dict=True), {"status": "Pending Review", "member": None})

    def test_banned_member_with_rejected_application_refused_at_approval(self):
        """Fixture shortcut, stated: the Banned+Rejected state is a db write (which real path produces it is
        not established). The application is confirmed while the Member is only Rejected, which is allowed."""
        member = self.create_test_member(email=self.email)
        frappe.db.set_value("Member", member.name, {"status": "Rejected", "application_status": "Rejected"})
        name = self._stage_and_confirm()
        frappe.db.set_value("Member", member.name, "status", "Banned")

        with self.assertRaisesRegex(frappe.ValidationError, "cannot be approved in its current state"):
            self._approve_as(name)

        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Banned")
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")

    def test_expulsion_between_confirm_and_approval_refused(self):
        """A Pending applicant may reapply; an expulsion (real termination service) executed after the
        application was confirmed makes the Member Banned, and approval must not reactivate it."""
        member = self.create_test_member(email=self.email)
        self.assertEqual(frappe.db.get_value("Member", member.name, "application_status"), "Pending", "precondition")
        name = self._stage_and_confirm()  # control: staged, so this Member could reapply before the expulsion
        execute_real_termination(self, member.name, today(), termination_type="Expulsion")
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Banned")

        with self.assertRaisesRegex(frappe.ValidationError, "cannot be approved in its current state"):
            self._approve_as(name)

        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Banned")
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")

    def test_banned_member_with_rejected_application_refused_at_submit(self):
        member = self.create_test_member(email=self.email)
        frappe.db.set_value("Member", member.name, {"status": "Banned", "application_status": "Rejected"})
        rows = frappe.db.count(SUBMISSION, {"email": self.email})
        self._request_from_fresh_ip()
        previous = frappe.session.user
        frappe.set_user("Guest")
        try:
            response = submit_application(**self._full_form_data())
        finally:
            frappe.set_user(previous)

        self.assertTrue(response["success"], response)  # the same answer a Guest gets for any email
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), rows, "nothing staged for a Banned member")

    def test_superseded_application_refused(self):
        older = self._stage_and_confirm()
        newer = self._stage_and_confirm()
        self.assertEqual(frappe.db.get_value(SUBMISSION, older, "status"), "Superseded")

        with self.assertRaisesRegex(frappe.ValidationError, "cannot be approved in its current state"):
            self._approve_as(older)

        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 0)
        self.assertEqual(frappe.db.get_value(SUBMISSION, newer, "status"), "Pending Review")

    def _approve_watching_status_mail(self, reapplication):
        """The Member's status-change notification skips itself under frappe.flags.in_test, so that skip rule
        is replaced by the same rule minus in_test; otherwise a Pending mail could never be observed here.
        The notification service is spied (wraps: it still runs), not stubbed: this bare environment cannot
        create an invoice, so the approval mail itself never goes out, and the Email Queue stays empty."""
        if reapplication:  # the Quit -> Pending save is what emits a Pending mail (an insert emits none: measured)
            self._voluntarily_quit_member_with_iban()
        name = self._stage_and_confirm()
        seen = []
        real_send = MemberStatusNotificationService.send_status_change_notification

        def spy(service, member_doc, old_status, new_status):
            seen.append((member_doc.email, new_status))
            return real_send(service, member_doc, old_status, new_status)

        def skip_unless_bulk(_service):
            return bool(frappe.flags.get("bulk_member_operations") or frappe.flags.get("in_bulk_import"))

        # Mock justified: Environment flag - frappe.flags.in_test is the only part of the rule replaced
        with patch(f"{EMISSION}.should_skip_event_emission", skip_unless_bulk):
            with patch.object(MemberStatusNotificationService, "send_status_change_notification", spy):
                self._approve_as(name)

        mine = [status for email, status in seen if email == self.email]
        self.assertIn("Active", mine, "control: the notification path ran, so a Pending one could have")
        self.assertNotIn("Pending", mine)

    def test_single_applicant_email_on_approval(self):
        self._approve_watching_status_mail(reapplication=False)

    def test_reapplicant_gets_no_pending_status_mail(self):
        self._approve_watching_status_mail(reapplication=True)

    def test_unknown_volunteer_email_is_relinked_not_doubled(self):
        """An email that already has an unlinked Volunteer gets that Volunteer, not a second one (T2 concern)."""
        with self.as_user(self.admin_user.email):
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": "Earlier Volunteer",
                    "email": self.email,
                    "status": "New",
                    "start_date": today(),
                }
            ).insert()
        self.track_doc("Volunteer", volunteer.name)
        name = self._stage_and_confirm(interested_in_volunteering=1)

        result = self._approve_as(name)

        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.count("Volunteer", {"email": self.email}), 1)
        self.assertEqual(
            frappe.db.get_value("Volunteer", volunteer.name, "member"),
            frappe.db.get_value("Member", {"email": self.email}),
        )


def _message_log_without_exc_id(log):
    out = []
    for entry in log:
        entry = json.loads(entry) if isinstance(entry, str) else dict(entry)
        entry.pop("__frappe_exc_id", None)
        out.append(entry)
    return out


class TestApproveApplicationBoard(ApprovalCase):
    def setUp(self):
        super().setUp()
        self.other_chapter = self.factory.ensure_test_chapter(
            f"Test Other {frappe.generate_hash(length=6)}", {"short_name": "OTH", "country": "Netherlands"}
        )
        self.board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")

    def _foreign_application(self):
        """A confirmed application whose chapter this board member holds no seat in."""
        self.email = self._fresh_applicant_email()
        return self._stage_and_confirm(selected_chapter=self.other_chapter.name)

    def _approve_as_board_probe(self, name):
        """(type, message, message_log delta, Error Log delta, query count) of approve_application as the board user."""
        from verenigingen.tests.utils.query_counter import count_queries

        errors = frappe.db.count("Error Log")
        frappe.clear_messages()
        before = len(frappe.local.message_log)
        kind = message = None
        with self.as_user(self.board.user):
            with count_queries() as counter:
                try:
                    approve_application(name, create_invoice=False)
                except Exception as error:
                    kind, message = type(error), str(error)
        log = _message_log_without_exc_id(list(frappe.local.message_log)[before:])
        queries = len([q for q in counter.queries if "Error Log" not in q])
        return kind, message, log, frappe.db.count("Error Log") - errors, queries

    def test_foreign_and_unknown_application_refused_identically(self):
        foreign = self._foreign_application()
        unknown = f"nonexistent-{frappe.generate_hash(length=8)}"

        self._approve_as_board_probe(unknown)  # warm the role/permission caches: the first call of a process reads cold
        foreign_result = self._approve_as_board_probe(foreign)
        unknown_result = self._approve_as_board_probe(unknown)

        self.assertEqual(foreign_result[0], frappe.PermissionError, foreign_result)
        self.assertEqual(foreign_result, unknown_result)
        self.assertEqual(frappe.db.get_value(SUBMISSION, foreign, "status"), "Pending Review")
        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 0)

    def test_board_member_approves_own_chapter_application(self):
        name = self._stage_and_confirm()  # chapter: the one this board member holds an Admin seat in

        result = self._approve_as(name, user=self.board.user)

        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.get_value("Member", {"email": self.email}, "status"), "Active")

    def test_board_member_cannot_place_member_in_another_chapter(self):
        name = self._stage_and_confirm()

        with self.assertRaises(frappe.PermissionError):
            self._approve_as(name, user=self.board.user, chapter=self.other_chapter.name)

        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")
        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 0)
