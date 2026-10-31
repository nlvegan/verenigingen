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
from verenigingen.api.membership_application_review import (
    approve_application,
    get_application_changes,
    reject_application,
    request_more_info,
)
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

    def _reject_as(self, name, user=None, send_mail=False, **kwargs):
        kwargs.setdefault("reason", "Does not fit our association")
        if send_mail:  # let the mail reach the Email Queue so a test can read it
            with self.as_user(user or self.admin_user.email):
                return reject_application(name, **kwargs)
        with self.as_user(user or self.admin_user.email):
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch("frappe.sendmail"):
                return reject_application(name, **kwargs)

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


class TestRejectApplication(ApprovalCase):
    """Rejection writes the application and nothing else (#1765 task 5). Driven through the real flow:
    submit_application as Guest -> confirm link -> reject_application as staff. No probe shortcuts except
    the Approved state in test_approved_application_cannot_be_rejected, which is reached by the real approve."""

    def test_reject_new_applicant_creates_nothing(self):
        name = self._stage_and_confirm()
        doctypes = ("Member", "Address", "Customer", "Contact", "Volunteer", "Chapter Member", "Chapter Membership History")
        before = {dt: frappe.db.count(dt) for dt in doctypes}

        result = self._reject_as(name, rejection_category="Other", internal_notes="staff only")

        self.assertTrue(result["success"], result)
        self.assertEqual(before, {dt: frappe.db.count(dt) for dt in before})
        self.assertEqual(frappe.db.count("Volunteer", {"email": self.email}), 0)
        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 0)
        row = frappe.db.get_value(
            SUBMISSION, name, ["status", "reviewed_by", "review_date", "review_notes", "rejection_category"], as_dict=True
        )
        self.assertEqual(row.status, "Rejected")
        self.assertEqual(row.reviewed_by, self.admin_user.email)
        self.assertTrue(row.review_date)
        self.assertEqual(row.rejection_category, "Other")
        self.assertIn("Does not fit our association", row.review_notes)
        self.assertIn("staff only", row.review_notes)

    def test_reject_reapplication_leaves_member_untouched(self):
        member = self._voluntarily_quit_member_with_iban()
        name = self._stage_and_confirm(last_name=f"Renamed{frappe.generate_hash(length=5)}", iban=OTHER_IBAN, bank_account_name="Other Holder", payment_method="SEPA Direct Debit")
        fields = ["modified", "iban", "status", "application_status", "last_name", "user", "customer"]
        before = frappe.db.get_value("Member", member.name, fields, as_dict=True)
        self.assertEqual(before.status, "Quit", "control: the Member this application would update exists and is Quit")

        self._reject_as(name)

        self.assertEqual(frappe.db.get_value("Member", member.name, fields, as_dict=True), before)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, ["status", "member"], as_dict=True), {"status": "Rejected", "member": None})

    def test_rejected_application_can_reapply(self):
        first = self._stage_and_confirm()
        self._reject_as(first)

        second = self._stage_and_confirm()

        self.assertNotEqual(first, second)
        self.assertEqual(frappe.db.get_value(SUBMISSION, first, "status"), "Rejected")
        self.assertEqual(frappe.db.get_value(SUBMISSION, second, "status"), "Pending Review")

    def test_non_pending_review_application_refused_and_unchanged(self):
        approved = self._stage_and_confirm()
        self._approve_as(approved)
        self.email = self._fresh_applicant_email()
        older = self._stage_and_confirm()
        self._stage_and_confirm()
        self.assertEqual(frappe.db.get_value(SUBMISSION, older, "status"), "Superseded", "precondition")
        self.assertEqual(frappe.db.get_value(SUBMISSION, approved, "status"), "Approved", "precondition")
        fields = ["status", "member", "reviewed_by", "review_date", "review_notes", "rejection_category"]

        for name in (approved, older):
            before = frappe.db.get_value(SUBMISSION, name, fields, as_dict=True)
            with self.assertRaisesRegex(frappe.ValidationError, "cannot be rejected in its current state"):
                self._reject_as(name)
            self.assertEqual(frappe.db.get_value(SUBMISSION, name, fields, as_dict=True), before)
        self.assertEqual(frappe.db.get_value("Member", {"email": self.email}), None)

    def test_rejection_mail_goes_to_the_applicant_and_references_the_application(self):
        """Spied, not stubbed (the real service still runs): this bare environment has no active email account,
        so a mail never reaches the Email Queue here and the queue cannot be read."""
        from verenigingen.services.communication.email_service import EmailService

        name = self._stage_and_confirm()
        real_send = EmailService.send_templated_email
        calls = []

        def spy(service, *args, **kwargs):
            calls.append(kwargs)
            return real_send(service, *args, **kwargs)

        # Mock justified: spy on the mail boundary; the real service still runs
        with patch.object(EmailService, "send_templated_email", spy):
            self._reject_as(name, rejection_category="Other")

        self.assertEqual(len(calls), 1, "exactly one rejection mail")
        self.assertEqual(calls[0]["recipients"], [self.email])
        self.assertEqual((calls[0]["reference_doctype"], calls[0]["reference_name"]), (SUBMISSION, name))
        self.assertEqual(calls[0]["context"]["rejection_category"], "Other")
        self.assertEqual(calls[0]["context"]["member"].first_name, "Appr")

    def _reject_with_mail_service(self, name, **service):
        from verenigingen.services.communication.email_service import EmailService

        # Mock justified: External Service - the mail service's outcome is the input under test
        with patch.object(EmailService, "send_templated_email", **service):
            return self._reject_as(name)

    def test_mail_failure_is_reported_logged_and_keeps_the_rejection(self):
        from verenigingen.utils.operation_result import OperationResult

        name = self._stage_and_confirm()
        self.expectErrorLog("Rejection mail failed")
        errors = frappe.db.count("Error Log", {"method": ["like", "Rejection mail failed%"]})
        frappe.clear_messages()
        before = len(frappe.local.message_log)

        result = self._reject_with_mail_service(name, return_value=OperationResult.fail("smtp boom"))

        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Rejected")
        self.assertTrue(result["success"])
        self.assertFalse(result["mail_sent"])
        self.assertIn("could not be sent", result["message"])
        self.assertTrue(
            any("could not be sent" in str(entry) for entry in list(frappe.local.message_log)[before:]),
            "the reviewer is told through msgprint as well",
        )
        self.assertEqual(frappe.db.count("Error Log", {"method": ["like", "Rejection mail failed%"]}), errors + 1)
        self.assertIn("smtp boom", frappe.get_all("Error Log", {"method": ["like", "Rejection mail failed%"]}, "error", order_by="creation desc", limit=1)[0].error)

    def test_mail_service_raising_is_reported_logged_and_keeps_the_rejection(self):
        name = self._stage_and_confirm()
        self.expectErrorLog("Rejection mail raised")
        errors = frappe.db.count("Error Log", {"method": ["like", "Rejection mail raised%"]})

        result = self._reject_with_mail_service(name, side_effect=RuntimeError("service down"))

        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Rejected")
        self.assertFalse(result["mail_sent"])
        self.assertEqual(frappe.db.count("Error Log", {"method": ["like", "Rejection mail raised%"]}), errors + 1)

    def test_invalid_email_template_refused_before_anything_is_written(self):
        name = self._stage_and_confirm()

        with self.assertRaisesRegex(frappe.ValidationError, "Invalid email template"):
            self._reject_as(name, email_template="No Such Template")

        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")


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

    def _reject_as_board_probe(self, name):
        """(type, message, message_log delta, Error Log delta, query count) of reject_application as the board user."""
        from verenigingen.tests.utils.query_counter import count_queries

        errors = frappe.db.count("Error Log")
        frappe.clear_messages()
        before = len(frappe.local.message_log)
        kind = message = None
        with self.as_user(self.board.user):
            with count_queries() as counter:
                try:
                    reject_application(name, reason="No")
                except Exception as error:
                    kind, message = type(error), str(error)
        log = _message_log_without_exc_id(list(frappe.local.message_log)[before:])
        queries = len([q for q in counter.queries if "Error Log" not in q])
        return kind, message, log, frappe.db.count("Error Log") - errors, queries

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

    def test_foreign_and_unknown_application_reject_refused_identically(self):
        foreign = self._foreign_application()
        unknown = f"nonexistent-{frappe.generate_hash(length=8)}"

        self._reject_as_board_probe(unknown)  # warm the caches: the first call of a process reads cold
        foreign_result = self._reject_as_board_probe(foreign)
        unknown_result = self._reject_as_board_probe(unknown)

        self.assertEqual(foreign_result[0], frappe.PermissionError, foreign_result)
        self.assertEqual(foreign_result, unknown_result)
        self.assertEqual(frappe.db.get_value(SUBMISSION, foreign, "status"), "Pending Review")

    def test_board_member_rejects_own_chapter_application(self):
        name = self._stage_and_confirm()

        result = self._reject_as(name, user=self.board.user)

        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Rejected")


class TestApplicationChanges(ApprovalCase):
    """#1765 task 6: the change preview a reviewer sees before approving.

    Driven through the real flow (submit -> confirm -> preview / approve). Fixture shortcuts, stated: the
    Member's address and (for the answers test) application_custom_fee are db writes standing in for "the
    state an earlier approval left", so those tests prove the preview, not that the state is reachable so."""

    def setUp(self):
        super().setUp()
        self.board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")

    def _quit_member_matching_form(self, **fields):
        """A voluntarily-Quit Member whose every application-writable field already equals what
        _full_form_data supplies, except the ones passed in `fields`."""
        values = {
            "first_name": "Appr",
            "iban": IBAN,
            "contact_number": "+31612345678",
            "birth_date": add_days(today(), -365 * 30),
            "selected_membership_type": self.membership_type.name,
        }
        values.update(fields)
        member = self._voluntarily_quit_member_with_iban_values(values)
        with self.as_user(self.admin_user.email):
            address = frappe.get_doc(
                {
                    "doctype": "Address",
                    "address_title": "Appr Applicant",
                    "address_type": "Personal",
                    "address_line1": "123 Test Street",
                    "city": "Amsterdam",
                    "country": "Netherlands",
                    "pincode": "1234AB",
                    "email_id": self.email,
                    "is_primary_address": 1,
                }
            ).insert()
        self.track_doc("Address", address.name)
        frappe.db.set_value("Member", member.name, "primary_address", address.name)  # fixture shortcut
        return member

    def _voluntarily_quit_member_with_iban_values(self, values):
        member = self.create_test_member(email=self.email, **values)
        execute_real_termination(self, member.name, today())
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Quit")
        return member

    def _changes_as(self, name, user=None):
        with self.as_user(user or self.admin_user.email):
            return get_application_changes(name)

    def _rows(self, name, user=None):
        return {row["field"]: row for row in self._changes_as(name, user)}

    def test_changes_list_only_differing_supplied_fields(self):
        member = self._quit_member_matching_form()
        name = self._stage_and_confirm(iban=OTHER_IBAN, last_name="Renamed")  # phone not changed: same as the Member's
        control = frappe.db.get_value("Member", member.name, "contact_number")
        self.assertEqual(control, "+31612345678", "control: the Member has a phone the application also supplies")

        rows = self._rows(name)

        self.assertEqual(set(rows), {"iban", "last_name"}, rows)
        self.assertEqual(rows["last_name"]["proposed"], "Renamed")
        self.assertNotEqual(rows["last_name"]["current"], "Renamed")
        self.assertEqual(rows["iban"]["proposed"], OTHER_IBAN)
        self.assertEqual(rows["iban"]["current"].replace(" ", ""), IBAN)
        self.assertTrue(rows["iban"]["label"] and rows["last_name"]["label"])

    def test_new_applicant_has_no_changes(self):
        name = self._stage_and_confirm()
        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 0, "precondition: no Member exists")

        self.assertEqual(self._changes_as(name), [])

    def test_preview_matches_write(self):
        """Snapshot every Member field before and after the real approval. Every previewed field must have
        changed to exactly the previewed value, and every other change must be one the approval itself
        makes (lifecycle and the approval core's own writes), named below."""
        member = self._quit_member_matching_form(last_name="Before")
        name = self._stage_and_confirm(
            iban=OTHER_IBAN,
            last_name="Renamed",
            bank_account_name="New Holder",
            payment_method="SEPA Direct Debit",
            city="Utrecht",
            address_line2="2 hoog",
        )
        preview = self._rows(name)
        self.assertTrue(preview, "control: the preview has rows to match")
        self.assertIn("address", preview, "control: this application changes the address")
        before = frappe.get_doc("Member", member.name).as_dict(no_default_fields=False)

        self._approve_as(name)

        after = frappe.get_doc("Member", member.name).as_dict(no_default_fields=False)
        changed = {
            field
            for field in set(before) | set(after)
            if not isinstance(before.get(field), list) and _norm(before.get(field)) != _norm(after.get(field))
        }
        for field, row in preview.items():
            if field == "address":  # not a Member field: asserted against the new Address below
                continue
            self.assertIn(field, changed, f"{field} previewed but approval did not change it")
            self.assertEqual(_norm(after[field]), _norm(row["proposed"]), field)
        self.assertNotEqual(after.primary_address, before.primary_address, "approval re-points the address")
        written = frappe.db.get_value("Address", after.primary_address, ["address_line1", "address_line2", "city", "pincode"], as_dict=True)
        self.assertEqual((written.city, written.address_line2), ("Utrecht", "2 hoog"))
        for part in (written.address_line1, written.address_line2, written.pincode, written.city):
            self.assertIn(part, preview["address"]["proposed"], "the previewed address is the one written")
        self.assertIn("Amsterdam", preview["address"]["current"])
        unexplained = changed - set(preview) - _APPROVAL_OWN_WRITES
        self.assertEqual(unexplained, set(), "approval changed fields the preview did not show")

    def test_preview_includes_answers_and_dues_choice(self):
        """A short-form reapplication also replaces the answers and the dues choice: both are in the preview."""
        member = self._voluntarily_quit_member_with_iban_values({"iban": IBAN})
        frappe.db.set_value("Member", member.name, "application_custom_fee", 5)  # fixture shortcut: an earlier application's fee
        name = self._stage_short_and_confirm()

        rows = self._rows(name)

        self.assertIn("application_door", rows, "an answer the short form replaces")
        self.assertEqual(rows["application_door"]["proposed"], frappe.db.get_value(SUBMISSION, name, "door"))
        self.assertIn("application_custom_fee", rows, "the dues choice the short form sets (7.50)")
        self.assertEqual((rows["application_custom_fee"]["current"], rows["application_custom_fee"]["proposed"]), (5, 7.5))

    def test_blank_supplied_field_is_not_listed(self):
        """The short form sends no birth date and no mobile number; the Member keeps its own (approval
        writes nothing there), so they are not rows."""
        member = self._voluntarily_quit_member_with_iban_values(
            {"iban": IBAN, "contact_number": "+31699999999", "birth_date": add_days(today(), -365 * 41)}
        )
        self.assertTrue(frappe.db.get_value("Member", member.name, "contact_number"), "control: the Member has a phone")
        name = self._stage_short_and_confirm()

        rows = self._rows(name)

        self.assertIn("application_door", rows, "control: the preview ran and has rows")
        self.assertNotIn("contact_number", rows)
        self.assertNotIn("birth_date", rows)

    def test_address_is_one_row_only_when_it_differs(self):
        self._quit_member_matching_form()
        same = self._stage_and_confirm()
        self.assertNotIn("address", self._rows(same), "the application supplies the address the Member has")

        moved = self._stage_and_confirm(address_line1="9 Other Road", city="Utrecht")
        rows = self._rows(moved)

        self.assertIn("address", rows)
        self.assertIn("123 Test Street", rows["address"]["current"])
        self.assertIn("9 Other Road", rows["address"]["proposed"])
        self.assertIn("Utrecht", rows["address"]["proposed"])

    def _address_rows(self, **form):
        member = self._quit_member_matching_form()
        last_name = frappe.db.get_value("Member", member.name, "last_name")  # the factory decorates the name
        return self._rows(self._stage_and_confirm(last_name=last_name, **form))

    def test_address_line2_alone_is_a_change(self):
        rows = self._address_rows(address_line2="2 hoog")

        self.assertEqual(set(rows), {"address"}, rows)
        self.assertIn("2 hoog", rows["address"]["proposed"])
        self.assertNotIn("2 hoog", rows["address"]["current"])

    def test_state_alone_is_a_change(self):
        rows = self._address_rows(state="Utrecht")

        self.assertEqual(set(rows), {"address"}, rows)
        self.assertIn("Utrecht", rows["address"]["proposed"])

    def test_postcode_spacing_and_case_are_not_a_change(self):
        rows = self._address_rows(postal_code="1234 ab")

        self.assertEqual(rows, {}, "1234AB and '1234 ab' are the same postcode")

    def _stage_with_fee(self, fee):
        """Fixture shortcut, stated: the payload is edited after staging to carry a custom fee (the form
        validates the amount, and a malformed one cannot be submitted through it)."""
        self._quit_member_matching_form()
        name = self._stage_and_confirm()
        payload = json.loads(frappe.db.get_value(SUBMISSION, name, "payload"))
        payload.update({"custom_contribution_fee": fee, "uses_custom_amount": 1})
        frappe.db.set_value(SUBMISSION, name, "payload", json.dumps(payload))
        return name

    def test_preview_does_not_name_the_previewer_as_fee_approver(self):
        name = self._stage_with_fee("12.5")

        rows = self._rows(name)

        self.assertEqual(rows["dues_rate"]["proposed"], 12.5, "control: the custom fee is previewed")
        self.assertIn("fee_override_reason", rows)
        self.assertNotIn("fee_override_by", rows)
        self.assertNotIn("fee_override_date", rows)
        self.assertNotIn(self.admin_user.email, json.dumps(rows, default=str))

    def test_approval_still_stamps_the_approver_on_a_custom_fee(self):
        name = self._stage_with_fee("12.5")
        member = frappe.db.get_value("Member", {"email": self.email})

        self._approve_as(name)

        stamped = frappe.db.get_value("Member", member, ["fee_override_by", "fee_override_date", "application_custom_fee"], as_dict=True)
        self.assertEqual(stamped.application_custom_fee, 12.5, "control: the fee was applied")
        self.assertEqual(stamped.fee_override_by, self.admin_user.email)
        self.assertEqual(str(stamped.fee_override_date), today())

    def test_preview_of_a_malformed_fee_writes_no_error_log(self):
        from verenigingen.services.member.approval.application_helpers import _apply_custom_contribution_fee

        name = self._stage_with_fee("not-a-number")
        # Control: the helper does log this input when it is not a preview, so a zero delta below is the
        # preview's doing, not an input that never reaches the log.
        # (the helper passes message and title swapped, so the text is in `method`)
        logged = {"method": ["like", "Error converting custom_contribution_fee%"]}
        self.expectErrorLog("Error converting custom_contribution_fee")
        errors = frappe.db.count("Error Log", logged)
        _apply_custom_contribution_fee(frappe._dict(), {"custom_contribution_fee": "not-a-number"})
        self.assertEqual(frappe.db.count("Error Log", logged), errors + 1)
        before = frappe.db.count("Error Log")

        self._rows(name)

        self.assertEqual(frappe.db.count("Error Log"), before)

    def test_iban_is_masked_for_a_board_member_and_full_for_an_administrator(self):
        self._quit_member_matching_form()
        name = self._stage_and_confirm(iban=OTHER_IBAN)

        board_row = self._rows(name, self.board.user)["iban"]
        admin_row = self._rows(name)["iban"]

        self.assertEqual(admin_row["proposed"], OTHER_IBAN)
        self.assertEqual(admin_row["current"].replace(" ", ""), IBAN)
        for side, full in (("current", IBAN), ("proposed", OTHER_IBAN)):
            shown = board_row[side]
            self.assertNotEqual(shown.replace(" ", ""), full, side)
            self.assertTrue(shown.endswith(full[-4:]), f"{side}: the last 4 characters stay visible")
            self.assertNotIn(full[4:-4], shown.replace(" ", ""), side)
        self.assertNotIn(OTHER_IBAN[2:-4], json.dumps(self._changes_as(name, self.board.user)))

    def test_system_manager_alone_sees_the_full_iban(self):
        """Ruling: Verenigingen Administrator AND System Manager. A System Manager without the other role."""
        self._quit_member_matching_form()
        name = self._stage_and_confirm(iban=OTHER_IBAN)
        sysman = self.create_test_user_with_roles(
            email=f"appr.sysman.{frappe.generate_hash(length=6)}@example.com", roles=["System Manager"]
        )

        self.assertEqual(self._rows(name, sysman.email)["iban"]["proposed"], OTHER_IBAN)

    def test_a_basic_seat_may_read(self):
        """Ruling N: any active seat in the application's chapter reads (the IBAN is masked)."""
        basic = self.create_test_board_member(self.chapter.name, permissions_level="Basic")
        self._quit_member_matching_form()
        name = self._stage_and_confirm(iban=OTHER_IBAN)

        rows = self._rows(name, basic.user)

        self.assertIn("iban", rows)
        self.assertNotEqual(rows["iban"]["proposed"], OTHER_IBAN)

    def _preview_probe(self, name, user):
        """(type, message, message_log delta, Error Log delta, query count) of get_application_changes."""
        from verenigingen.tests.utils.query_counter import count_queries

        errors = frappe.db.count("Error Log")
        frappe.clear_messages()
        before = len(frappe.local.message_log)
        kind = message = None
        with self.as_user(user):
            with count_queries() as counter:
                try:
                    get_application_changes(name)
                except Exception as error:
                    kind, message = type(error), str(error)
        log = _message_log_without_exc_id(list(frappe.local.message_log)[before:])
        queries = len([q for q in counter.queries if "Error Log" not in q])
        return kind, message, log, frappe.db.count("Error Log") - errors, queries

    def test_foreign_and_unknown_application_refused_identically(self):
        other_chapter = self.factory.ensure_test_chapter(
            f"Test Other {frappe.generate_hash(length=6)}", {"short_name": "OTH", "country": "Netherlands"}
        )
        self._quit_member_matching_form()
        foreign = self._stage_and_confirm(selected_chapter=other_chapter.name)
        unknown = f"nonexistent-{frappe.generate_hash(length=8)}"

        user = self.board.user  # clears the API's security tier, so the application check is what refuses
        self._preview_probe(unknown, user)  # warm the caches: the first call of a process reads cold
        foreign_result = self._preview_probe(foreign, user)
        unknown_result = self._preview_probe(unknown, user)

        self.assertEqual(foreign_result[0], frappe.PermissionError, foreign_result)
        self.assertEqual(foreign_result, unknown_result)


class TestRequestMoreInfo(ApprovalCase):
    """#1765 task 7b / #1874: a reviewer asks an applicant for more information. Driven through the real flow
    (submit -> confirm -> request_more_info -> approve). SMTP delivery is the only stub: the Communication
    is inserted by the real `_make`, so the rows these tests read are the ones production writes."""

    def setUp(self):
        super().setUp()
        self.other_chapter = self.factory.ensure_test_chapter(
            f"Test Other {frappe.generate_hash(length=6)}", {"short_name": "OTH", "country": "Netherlands"}
        )
        self.board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")

    def _ask_as(self, name, user=None, info="Please send a copy of your ID", **service):
        from frappe.core.doctype.communication.communication import Communication

        with self.as_user(user or self.admin_user.email):
            # Mock justified: External Service - SMTP delivery (and the site's outgoing account) are not the logic under test
            with patch.object(Communication, "get_outgoing_email_account", return_value=True):
                with patch.object(Communication, "send_email", **service):
                    return request_more_info(name, info)

    def _threads(self, doctype, name):
        return frappe.get_all(
            "Communication",
            {"reference_doctype": doctype, "reference_name": name},
            ["name", "recipients", "subject", "content", "sent_or_received"],
        )

    def _notes(self, name):
        return frappe.get_all(
            "Comment",
            {"reference_doctype": SUBMISSION, "reference_name": name, "comment_type": "Info"},
            ["content", "owner", "comment_email"],
        )

    def test_request_mails_the_applicant_through_the_application_and_records_the_asker(self):
        name = self._stage_and_confirm()
        before = frappe.db.get_value(SUBMISSION, name, ["status", "reviewed_by", "review_date"], as_dict=True)

        result = self._ask_as(name, info="Please send a copy of your ID")

        self.assertTrue(result["success"])
        self.assertTrue(result["mail_sent"])
        threads = self._threads(SUBMISSION, name)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0].recipients, self.email)
        self.assertEqual(threads[0].sent_or_received, "Sent")
        self.assertIn("Please send a copy of your ID", threads[0].content)
        notes = self._notes(name)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].owner, self.admin_user.email)
        self.assertIn(self.admin_user.email, notes[0].content)
        self.assertEqual(
            frappe.db.get_value(SUBMISSION, name, ["status", "reviewed_by", "review_date"], as_dict=True), before
        )

    def test_the_application_can_still_be_approved_afterwards(self):
        name = self._stage_and_confirm()
        self._ask_as(name)

        approved = self._approve_as(name)

        self.assertTrue(approved["success"], approved)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Approved")
        self.assertEqual(frappe.db.get_value("Member", {"email": self.email}, "status"), "Active")

    def test_the_applicant_name_and_the_request_are_escaped_in_the_mail(self):
        name = self._stage_and_confirm()
        # Probe shortcut: the form refuses markup in a name, so the stored name is set directly. This proves the
        # mail escapes whatever the record holds, not that a name with markup is reachable through the form.
        frappe.db.set_value(SUBMISSION, name, "applicant_name", "<b>Bold</b>")

        self._ask_as(name, info="<script>alert(1)</script> & more\nsecond line")

        content = self._threads(SUBMISSION, name)[0].content
        self.assertNotIn("<script>", content)
        self.assertNotIn("<b>Bold</b>", content)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; more<br>second line", content)
        self.assertIn("&lt;b&gt;Bold&lt;/b&gt;", content)

    def test_an_empty_request_is_refused_and_writes_nothing(self):
        name = self._stage_and_confirm()

        with self.assertRaisesRegex(frappe.ValidationError, "Describe the information"):
            self._ask_as(name, info="   ")

        self.assertEqual(self._threads(SUBMISSION, name), [])
        self.assertEqual(self._notes(name), [])

    def test_non_pending_review_application_refused_and_unchanged(self):
        approved = self._stage_and_confirm()
        self._approve_as(approved)
        self.email = self._fresh_applicant_email()
        older = self._stage_and_confirm()
        self._stage_and_confirm()
        self.email = self._fresh_applicant_email()
        rejected = self._stage_and_confirm()
        self._reject_as(rejected)
        self.assertEqual(frappe.db.get_value(SUBMISSION, older, "status"), "Superseded", "precondition")
        fields = ["status", "member", "reviewed_by", "review_date", "review_notes", "modified"]

        for name in (approved, older, rejected):
            before = frappe.db.get_value(SUBMISSION, name, fields, as_dict=True)
            threads = len(self._threads(SUBMISSION, name))
            with self.assertRaisesRegex(frappe.ValidationError, "cannot be asked for more information"):
                self._ask_as(name)
            self.assertEqual(frappe.db.get_value(SUBMISSION, name, fields, as_dict=True), before)
            self.assertEqual(len(self._threads(SUBMISSION, name)), threads, "no mail for a closed application")
            self.assertEqual(self._notes(name), [])

    def test_a_member_is_never_written_or_mailed(self):
        member = self._voluntarily_quit_member_with_iban()
        name = self._stage_and_confirm()
        snapshot = frappe.db.get_value("Member", member.name, ["modified", "status", "application_status"])
        threads = len(self._threads("Member", member.name))

        self._ask_as(name)

        self.assertEqual(
            frappe.db.get_value("Member", member.name, ["modified", "status", "application_status"]), snapshot
        )
        self.assertEqual(len(self._threads("Member", member.name)), threads)
        self.assertEqual(len(self._threads(SUBMISSION, name)), 1)

    def test_mail_failure_is_reported_logged_and_keeps_the_request(self):
        name = self._stage_and_confirm()
        self.expectErrorLog("Information request mail failed")
        errors = frappe.db.count("Error Log", {"method": ["like", "Information request mail failed%"]})
        frappe.clear_messages()
        before = len(frappe.local.message_log)

        result = self._ask_as(name, side_effect=frappe.OutgoingEmailError("smtp boom"))

        self.assertTrue(result["success"])
        self.assertFalse(result["mail_sent"])
        self.assertIn("could not be sent", result["message"])
        self.assertTrue(
            any("could not be sent" in str(entry) for entry in list(frappe.local.message_log)[before:]),
            "the reviewer is told through msgprint as well",
        )
        self.assertEqual(
            frappe.db.count("Error Log", {"method": ["like", "Information request mail failed%"]}), errors + 1
        )
        self.assertEqual(len(self._notes(name)), 1, "the request is still recorded")
        self.assertEqual(self._threads(SUBMISSION, name), [], "no phantom Sent communication")
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")

    def _ask_as_board_probe(self, name):
        """(type, message, message_log delta, Error Log delta, query count) of request_more_info as the board user."""
        from verenigingen.tests.utils.query_counter import count_queries

        errors = frappe.db.count("Error Log")
        frappe.clear_messages()
        before = len(frappe.local.message_log)
        kind = message = None
        with self.as_user(self.board.user):
            with count_queries() as counter:
                try:
                    request_more_info(name, "Anything")
                except Exception as error:
                    kind, message = type(error), str(error)
        log = _message_log_without_exc_id(list(frappe.local.message_log)[before:])
        queries = len([q for q in counter.queries if "Error Log" not in q])
        return kind, message, log, frappe.db.count("Error Log") - errors, queries

    def test_foreign_and_unknown_application_refused_identically(self):
        self.email = self._fresh_applicant_email()
        foreign = self._stage_and_confirm(selected_chapter=self.other_chapter.name)
        unknown = f"nonexistent-{frappe.generate_hash(length=8)}"

        self._ask_as_board_probe(unknown)  # warm the caches: the first call of a process reads cold
        foreign_result = self._ask_as_board_probe(foreign)
        unknown_result = self._ask_as_board_probe(unknown)

        self.assertEqual(foreign_result[0], frappe.PermissionError, foreign_result)
        self.assertEqual(foreign_result, unknown_result)
        self.assertEqual(self._threads(SUBMISSION, foreign), [])
        self.assertEqual(self._notes(foreign), [])

    def test_board_member_asks_about_own_chapter_application(self):
        name = self._stage_and_confirm()

        result = self._ask_as(name, user=self.board.user)

        self.assertTrue(result["mail_sent"], result)
        self.assertEqual(self._notes(name)[0].owner, self.board.user)


def _norm(value):
    """Compare Member values across the formats a save rewrites (IBAN groups, dates as str)."""
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value.replace(" ", "")
    return str(value) if not isinstance(value, (int, float)) else value


# Fields the approval changes on its own, whatever the application carries. Measured from a real run; a
# new unexplained change fails test_preview_matches_write. Grouped by why they are not preview rows.
_APPROVAL_OWN_WRITES = {
    # audit columns
    "modified",
    "modified_by",
    # lifecycle: Quit -> Active and the application stamp
    "status",
    "application_status",
    "application_date",
    "application_id",
    "membership_status",
    "member_since",
    "member_end_date",
    # derived from a previewed name, or the Address the approval re-creates (same text unless "address" is a row)
    "full_name",
    "primary_address",
    "address_fingerprint",
    "normalized_address_line",
    "normalized_city",
    "address_last_updated",
    # the chapter note the approval appends
    "notes",
    # the approval core: membership, schedule, billing, review stamp
    "current_membership_type",
    "current_membership_plan",
    "current_dues_schedule",
    "dues_rate",
    "next_invoice_date",
    "reviewed_by",
    "review_date",
    # stamped with the approver and the day (the preview omits them: it would only name the previewer)
    "fee_override_by",
    "fee_override_date",
}
