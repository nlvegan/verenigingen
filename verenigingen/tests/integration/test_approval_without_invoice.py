# -*- coding: utf-8 -*-
"""
#1900: an approval WITHOUT an invoice sends the approval email WITHOUT a payment link (maintainer
ruling 2026-11-03). It must never crash on ``invoice.name``, and the response must never claim an
invoice was sent.

Driven through the real application-keyed flow (submit_application as Guest -> confirm link ->
approve_application) as Administrator-class staff AND as a real board member (create_test_board_member).
The mail boundary is spied, not stubbed: ``EmailService._send_email_internal`` still runs, so the template
is really rendered and we read the subject and body it was handed. No probe shortcuts, except that the
invoice failure is produced by breaking the company setting the way test_approval_invoice_period does.
"""

from unittest.mock import patch

import json

import frappe
from frappe.utils import add_days, add_months, getdate, now_datetime, today

from verenigingen.services.communication.email_service import EmailService
from verenigingen.tests.integration.test_application_record_approval import SUBMISSION, ApprovalCase

NOTIFICATION_KEY = "member_application_approved"
APPROVAL_ERRORS = ["Approval Email Exception", "Approval Email Failed", "Approval Notification Failed"]


class TestApprovalWithoutInvoice(ApprovalCase):
    def setUp(self):
        super().setUp()
        self._require_approval_notification_enabled()

    def _require_approval_notification_enabled(self):
        """Precondition, stated rather than seeded: with no `notification_types` row the key counts as
        DISABLED and every mail assertion below fails opaquely. CI seeds the row on install (#1998)."""
        from verenigingen.services.communication.email_configuration_service import (
            get_email_configuration_service,
        )

        if not get_email_configuration_service().is_notification_enabled(NOTIFICATION_KEY):
            self.fail(
                f"Verenigingen Email Configuration has no enabled '{NOTIFICATION_KEY}' row, so the approval "
                "mail is skipped. Seed the missing notification_types rows (migrate/install does, #1998); "
                "this test deliberately does not modify the singleton."
            )

    def _approve_capturing_mail(self, application, user=None, **kwargs):
        """(response, mails the applicant was sent, outcome of each send, approval Error Log rows written)."""
        kwargs.setdefault("membership_type", self.membership_type.name)
        kwargs.setdefault("chapter", self.chapter.name)
        mails, outcomes = [], []
        real = EmailService._send_email_internal

        def spy(service, *args, **kw):
            result = real(service, *args, **kw)
            mails.append(kw)
            outcomes.append(result)
            return result

        errors_before = self._approval_error_rows()
        # Mock justified: spy on the mail boundary; the real service (and template render) still runs
        with patch.object(EmailService, "_send_email_internal", spy):
            response = self._approve_as(application, user=user, send_mail=True, **kwargs)
        mine = [m for m in mails if self.email in (m.get("recipients") or [])]
        new_errors = [row for row in self._approval_error_rows() if row not in errors_before]
        return response, mine, outcomes, new_errors

    def _approval_error_rows(self):
        return frappe.get_all("Error Log", {"method": ["in", APPROVAL_ERRORS]}, pluck="name")

    def _assert_mail_without_payment_link(self, mails, outcomes):
        self.assertEqual(len(mails), 1, "exactly one approval mail goes to the applicant")
        self.assertTrue(outcomes[0].success, outcomes[0])
        self.assertFalse((outcomes[0].data or {}).get("skipped"), "the mail was queued, not skipped")
        text = f"{mails[0]['subject']}\n{mails[0]['content']}"
        self.assertIn("Congratulations", text, "control: the approval body rendered")
        for absent in ("/payment/membership/", "Pay Membership Fee", "Payment Required", "href=\"\""):
            self.assertNotIn(absent, text)
        self.assertNotIn("invoice", text.lower(), "no invoice wording when there is no invoice")

    def _assert_no_invoice_claim(self, response):
        self.assertTrue(response["success"], response)
        self.assertIsNone(response["invoice"])
        self.assertNotIn("Invoice sent", response["message"])

    def test_no_invoice_requested_sends_approval_mail_without_payment_link_as_admin(self):
        application = self._stage_and_confirm()
        response, mails, outcomes, errors = self._approve_capturing_mail(application, create_invoice=False)

        self._assert_no_invoice_claim(response)
        self.assertFalse(response["invoice_failed"], "not a failed invoice: none was requested")
        self.assertNotIn("NOT be created", response["message"])
        self._assert_mail_without_payment_link(mails, outcomes)
        self.assertEqual(errors, [], "no Error Log row for a plain invoice-less approval")

    def test_no_invoice_requested_as_least_privileged_board_member(self):
        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        application = self._stage_and_confirm()
        response, mails, outcomes, errors = self._approve_capturing_mail(
            application, user=board.user, create_invoice=False
        )

        self._assert_no_invoice_claim(response)
        self.assertFalse(response["invoice_failed"])
        self._assert_mail_without_payment_link(mails, outcomes)
        self.assertEqual(errors, [])

    def test_failed_invoice_sends_no_approval_mail_and_is_not_a_clean_approval(self):
        """invoice_failed (#1774) is not "no invoice requested": the approval mail WAITS for the invoice
        (maintainer ruling 2026-11-03, round 2), staff are told, and the response claims no email went out."""
        application = self._stage_and_confirm()
        original = frappe.db.get_single_value("Verenigingen Settings", "company")
        frappe.db.set_single_value("Verenigingen Settings", "company", "No Such Company 1900")
        self.addCleanup(frappe.db.set_single_value, "Verenigingen Settings", "company", original)
        self.expectErrorLog(
            "Membership Invoice Creation Failed",
            "Membership Invoice Security",
            "BTW Tax Exemption Error",
            "Secure Operation Failed",
        )
        response, mails, outcomes, errors = self._approve_capturing_mail(application, create_invoice=True)

        self._assert_no_invoice_claim(response)
        self.assertTrue(response["invoice_failed"], response)
        self.assertIn("NOT be created", response["message"])
        self.assertIn("no approval email", response["message"])
        self.assertNotIn("emailed", response["message"].lower())
        self.assertEqual(mails, [], "no approval mail to the applicant until an invoice exists")
        self.assertEqual(errors, [], "the invoice failure is logged where it happens, not as a mail error")

    def test_invoiced_approval_keeps_the_payment_link_and_the_invoice_message(self):
        """Control: with an invoice the mail carries the link and the response says so. Without it the
        no-invoice assertions above would pass on a mail that never has a link."""
        application = self._stage_and_confirm()
        response, mails, outcomes, errors = self._approve_capturing_mail(application, create_invoice=True)

        self.assertTrue(response["invoice"], response)
        self.assertFalse(response["invoice_failed"])
        self.assertIn("Invoice sent to applicant", response["message"])
        self.assertEqual(len(mails), 1)
        text = f"{mails[0]['subject']}\n{mails[0]['content']}"
        self.assertIn(f"/payment/membership/{response['member']}/{response['invoice']}", text)
        self.assertIn("Pay Membership Fee", text)
        self.assertIn("Payment Required", text)
        self.assertEqual(errors, [])


class TestRetryApplicationInvoice(TestApprovalWithoutInvoice):
    """#1900 round 3: staff retry of the invoice of an application approved while invoicing was broken.

    The retry creates the invoice through the approval's own helper and only then sends the held approval
    mail, with the payment link. Driven through the real flow; the one stand-in is how invoicing is broken
    (Verenigingen Settings names a company that does not exist, as test_approval_invoice_period does)."""

    # The parent's tests are not repeated here.
    test_no_invoice_requested_sends_approval_mail_without_payment_link_as_admin = None
    test_no_invoice_requested_as_least_privileged_board_member = None
    test_failed_invoice_sends_no_approval_mail_and_is_not_a_clean_approval = None
    test_invoiced_approval_keeps_the_payment_link_and_the_invoice_message = None

    def _make_invoicing_fail(self):
        self._company = frappe.db.get_single_value("Verenigingen Settings", "company")
        frappe.db.set_single_value("Verenigingen Settings", "company", "No Such Company 1900")
        self.addCleanup(frappe.db.set_single_value, "Verenigingen Settings", "company", self._company)
        self.expectErrorLog(
            "Membership Invoice Creation Failed",
            "Membership Invoice Security",
            "BTW Tax Exemption Error",
            "Secure Operation Failed",
        )

    def _fix_invoicing(self):
        frappe.db.set_single_value("Verenigingen Settings", "company", self._company)

    def _approved_with_failed_invoice(self, **stage):
        """(application, member) after an approval whose invoice could not be created."""
        application = self._stage_and_confirm(**stage)
        self._make_invoicing_fail()
        response, mails, _outcomes, _errors = self._approve_capturing_mail(application, create_invoice=True)
        self.assertTrue(response["invoice_failed"], response)
        self.assertEqual(mails, [], "control: the failed approval sent no mail")
        return application, response["member"]

    def _retry(self, application, user=None):
        """(response, mails the applicant was sent) of retry_application_invoice."""
        from verenigingen.api.membership_application_review import retry_application_invoice

        mails = []
        real = EmailService._send_email_internal

        def spy(service, *args, **kw):
            result = real(service, *args, **kw)
            mails.append(kw)
            return result

        # Mock justified: spy on the mail boundary; the real service (and template render) still runs
        with patch.object(EmailService, "_send_email_internal", spy):
            with self.as_user(user or self.admin_user.email):
                response = retry_application_invoice(application)
        return response, [m for m in mails if self.email in (m.get("recipients") or [])]

    def _invoices_of(self, member):
        customer = frappe.db.get_value("Member", member, "customer")
        return frappe.get_all("Sales Invoice", {"customer": customer, "docstatus": ["<", 2]}, pluck="name")

    def test_retry_creates_the_invoice_and_sends_the_held_mail_with_the_link(self):
        application, member = self._approved_with_failed_invoice()
        self.assertEqual(self._invoices_of(member), [])
        self._fix_invoicing()

        response, mails = self._retry(application)

        self.assertTrue(response["success"], response)
        self.assertFalse(response["invoice_failed"])
        invoice = response["invoice"]
        self.assertEqual(self._invoices_of(member), [invoice], "exactly one invoice")
        self.assertTrue(response["mail_sent"])
        self.assertEqual(len(mails), 1, "exactly one held approval mail")
        text = f"{mails[0]['subject']}\n{mails[0]['content']}"
        self.assertIn(f"/payment/membership/{member}/{invoice}", text)
        self.assertIn("Pay Membership Fee", text)

    def test_retry_that_fails_again_is_loud_and_sends_no_mail(self):
        application, member = self._approved_with_failed_invoice()  # invoicing stays broken

        response, mails = self._retry(application)

        self.assertTrue(response["invoice_failed"], response)
        self.assertFalse(response["mail_sent"])
        self.assertIn("NOT be created", response["message"])
        self.assertEqual(mails, [])
        self.assertEqual(self._invoices_of(member), [])

    def test_second_retry_is_refused_and_creates_nothing_more(self):
        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        _first, first_mails = self._retry(application)
        self.assertEqual(len(first_mails), 1)

        with self.assertRaises(frappe.ValidationError) as refused:
            self._retry(application)

        self.assertIn("no failed invoice to retry", str(refused.exception), "the marker was cleared")
        self.assertEqual(len(self._invoices_of(member)), 1)

    def test_a_pending_application_cannot_be_retried(self):
        application = self._stage_and_confirm()
        with self.assertRaises(frappe.ValidationError) as refused:
            self._retry(application)
        self.assertIn("not been approved", str(refused.exception))

    def test_an_invoiced_approval_cannot_be_retried(self):
        application = self._stage_and_confirm()
        response, _mails, _outcomes, _errors = self._approve_capturing_mail(application, create_invoice=True)
        self.assertTrue(response["invoice"], response)
        with self.assertRaises(frappe.ValidationError) as refused:
            self._retry(application)
        self.assertIn("no failed invoice to retry", str(refused.exception))
        self.assertEqual(len(self._invoices_of(response["member"])), 1)

    def test_the_retry_takes_the_advisory_lock_before_creating_the_invoice(self):
        """Probe of the queries (PROBE LIMIT, stated: it shows the lock is requested before the invoice insert;
        contention between two connections is test_retry_invoice_concurrency's job). GET_LOCK, then a locking
        read of the application, both before the invoice is inserted."""
        from verenigingen.tests.utils.query_counter import count_queries

        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        with count_queries() as counter:
            self._retry(application)
        sql = [q.lower() for q in counter.queries]
        advisory = [i for i, q in enumerate(sql) if "get_lock(" in q]
        locking_read = [
            i for i, q in enumerate(sql) if "`tabmembership application submission`" in q and "for update" in q
        ]
        created = [i for i, q in enumerate(sql) if "insert into `tabsales invoice`" in q]
        self.assertTrue(advisory, "no GET_LOCK")
        self.assertTrue(locking_read, "no locking read of the application")
        self.assertTrue(created, "control: an invoice was inserted")
        self.assertLess(advisory[0], locking_read[0])
        self.assertLess(locking_read[0], created[0], "the state is re-read under lock, before the insert")

    def _board_probe(self, board_user, application):
        """(type, message, message_log delta, Error Log delta, query count) of the retry as a board member."""
        from verenigingen.api.membership_application_review import retry_application_invoice
        from verenigingen.tests.integration.test_application_record_approval import _message_log_without_exc_id
        from verenigingen.tests.utils.query_counter import count_queries

        errors = frappe.db.count("Error Log")
        frappe.clear_messages()
        before = len(frappe.local.message_log)
        kind = message = None
        with self.as_user(board_user):
            # Mock justified: Infrastructure - the RQ push of the refusal's security event
            with patch("frappe.enqueue"), count_queries() as counter:
                try:
                    retry_application_invoice(application)
                except Exception as error:
                    kind, message = type(error), str(error)
        log = _message_log_without_exc_id(list(frappe.local.message_log)[before:])
        queries = len([q for q in counter.queries if "Error Log" not in q])
        return kind, message, log, frappe.db.count("Error Log") - errors, queries

    def test_board_member_of_the_chapter_may_retry(self):
        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()

        response, mails = self._retry(application, user=board.user)

        self.assertTrue(response["success"], response)
        self.assertEqual(len(self._invoices_of(member)), 1)
        self.assertEqual(len(mails), 1)

    def test_board_member_retry_creates_the_membership_item_the_approval_never_got_to_make(self):
        """#1930/#2538: the retry creates the invoice as the CALLER, and the first invoice of a membership
        type creates its Item, which a board member cannot. After the retry's own authorisation the invoice
        step runs with permission checks bypassed, as the approver. The Item is removed after the failed
        approval (the approval's own attempt got as far as making it before the invoice insert failed)."""
        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        application, member = self._approved_with_failed_invoice()
        item_code = f"MEM-{self.membership_type.membership_type_name}".upper().replace(" ", "-")
        frappe.delete_doc("Item", item_code, force=True, ignore_permissions=True)
        self.assertFalse(frappe.db.exists("Item", item_code), "precondition: the membership Item is absent")
        self._fix_invoicing()

        response, mails = self._retry(application, user=board.user)

        self.assertTrue(response["success"], response)
        self.assertFalse(response["invoice_failed"], response)
        self.assertTrue(frappe.db.exists("Item", item_code))
        self.assertEqual(len(self._invoices_of(member)), 1)
        self.assertEqual(len(mails), 1)

    def test_a_board_member_of_another_chapter_is_refused_like_an_unknown_application(self):
        other = self.factory.ensure_test_chapter(
            f"Test Other {frappe.generate_hash(length=6)}", {"short_name": "OTH", "country": "Netherlands"}
        )
        stranger = self.create_test_board_member(other.name, permissions_level="Admin")
        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        unknown = f"nonexistent-{frappe.generate_hash(length=8)}"

        self._board_probe(stranger.user, unknown)  # warm the role/permission caches
        foreign_result = self._board_probe(stranger.user, application)
        unknown_result = self._board_probe(stranger.user, unknown)

        self.assertEqual(foreign_result[0], frappe.PermissionError, foreign_result)
        self.assertEqual(foreign_result, unknown_result, "every channel must match")
        self.assertEqual(self._invoices_of(member), [])
        self.assertEqual(frappe.db.get_value(SUBMISSION, application, "status"), "Approved")

    def test_a_basic_seat_cannot_retry(self):
        """Approval needs an Admin-level seat; a Basic seat on the same chapter may not retry either."""
        basic = self.create_test_board_member(self.chapter.name, permissions_level="Basic")
        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        kind, _message, _log, _errors, _queries = self._board_probe(basic.user, application)
        self.assertEqual(kind, frappe.PermissionError)
        self.assertEqual(self._invoices_of(member), [])

    def test_the_retry_list_shows_only_marked_applications_the_caller_may_retry(self):
        from verenigingen.api.membership_application_review import get_approved_applications_without_invoice

        other = self.factory.ensure_test_chapter(
            f"Test Other {frappe.generate_hash(length=6)}", {"short_name": "OTH", "country": "Netherlands"}
        )
        mine = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        stranger = self.create_test_board_member(other.name, permissions_level="Admin")
        application, member = self._approved_with_failed_invoice()

        def listed(user):
            with self.as_user(user):
                return [row.name for row in get_approved_applications_without_invoice()]

        self.assertIn(application, listed(mine.user))
        self.assertIn(application, listed(self.admin_user.email))
        self.assertNotIn(application, listed(stranger.user), "a caller who cannot retry sees nothing")
        self._fix_invoicing()
        self._retry(application)
        self.assertNotIn(application, listed(mine.user), "an invoiced application leaves the list")

    # -- the marker (#1900 round 4) -------------------------------------------------------------

    def _marker(self, application):
        return frappe.db.get_value(SUBMISSION, application, "invoice_failed_on")

    def test_a_failed_approval_is_marked_and_a_successful_retry_clears_the_marker(self):
        application, _member = self._approved_with_failed_invoice()
        self.assertTrue(self._marker(application), "the failed approval is marked")
        self._fix_invoicing()
        self._retry(application)
        self.assertFalse(self._marker(application), "a successful retry clears the marker")

    def _give_the_applicant_a_user(self):
        """An existing User makes the core's account step link it and COMMIT (the commit under test)."""
        user_doc = frappe.get_doc(
            {"doctype": "User", "email": self.email, "first_name": "Marker", "send_welcome_email": 0}
        ).insert()  # as the suite's Administrator
        self.track_doc("User", user_doc.name)

    def _approve_failing_after_the_core_commit(self, application, user=None, with_user=True):
        """Approve (invoice broken) and fail AFTER the core's own commit, then drop everything uncommitted.

        The core's account step really commits (member_user_account_service links an EXISTING User and
        commits, Pattern 1), so the applicant gets a User first. The later failure stands in for a crash or a
        worker kill: `_build_approval_response` runs after that commit. Then `frappe.db.rollback()` discards
        what a dying request would lose, so the reads that follow see only what was COMMITTED."""
        from verenigingen.api import membership_application_review as review

        if with_user:
            self._give_the_applicant_a_user()
        self._make_invoicing_fail()
        # Mock justified: execution-context fault injection standing in for a crash after the core's commit
        with patch.object(review, "_build_approval_response", side_effect=RuntimeError("crash after commit")):
            with self.assertRaises(RuntimeError):
                self._approve_as(
                    application,
                    user=user,
                    create_invoice=True,
                    membership_type=self.membership_type.name,
                    chapter=self.chapter.name,
                )
        frappe.db.rollback()

    def _assert_committed_approved_and_marked(self, application):
        self.assertEqual(
            frappe.db.get_value(SUBMISSION, application, "status"),
            "Approved",
            "control: the core's commit really persisted the approval, so the crash fell AFTER it",
        )
        self.assertEqual(
            frappe.db.get_value("Member", frappe.db.get_value(SUBMISSION, application, "member"), "user"),
            self.email,
            "control: the account step's own commit is the one that ran",
        )
        self.assertTrue(
            self._marker(application),
            "an Approved application with a failed invoice must carry its retry marker in the DATABASE",
        )

    def test_the_marker_is_committed_with_the_approval_even_if_the_request_dies_after_the_core_commit(self):
        """#2055: the marker used to be written after the core returned, i.e. after the core's mid-operation
        commit, so a failure in between left Approved + failed invoice + NO marker (never in the retry list)."""
        application = self._stage_and_confirm()
        self._approve_failing_after_the_core_commit(application)
        self._assert_committed_approved_and_marked(application)

    def test_the_marker_survives_the_same_crash_for_the_least_privileged_approver(self):
        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        application = self._stage_and_confirm()
        self._approve_failing_after_the_core_commit(application, user=board.user)
        self._assert_committed_approved_and_marked(application)

    def test_without_a_user_the_core_never_commits_so_a_crash_rolls_approval_and_marker_back_together(self):
        """No existing User: the account step QUEUES a job and does not commit, so nothing is persisted
        before the crash. The rollback also discards the test's own uncommitted staging, so the row may be
        gone entirely; what must NOT survive is an Approved application (with or without a marker): approval
        and marker go together or not at all. (A marker written WITH a commit would leave Approved behind.)"""
        application = self._stage_and_confirm()
        self._approve_failing_after_the_core_commit(application, with_user=False)
        self.assertNotEqual(frappe.db.get_value(SUBMISSION, application, "status"), "Approved")
        self.assertFalse(self._marker(application))

    def test_without_a_user_a_failed_invoice_approval_is_marked(self):
        """The no-User branch of the real flow: the marker is set by the same write."""
        application, _member = self._approved_with_failed_invoice()
        self.assertFalse(frappe.db.get_value("User", self.email), "control: the applicant had no User")
        self.assertEqual(frappe.db.get_value(SUBMISSION, application, "status"), "Approved")
        self.assertTrue(self._marker(application))

    def test_a_crash_after_the_core_commit_does_not_mark_an_approval_without_a_requested_invoice(self):
        """Control: the early marker is only for a REQUESTED invoice that failed (create_invoice=False is
        never marked), so the fix cannot be 'always mark'."""
        from verenigingen.api import membership_application_review as review

        application = self._stage_and_confirm()
        self._give_the_applicant_a_user()
        # Mock justified: execution-context fault injection standing in for a crash after the core's commit
        with patch.object(review, "_build_approval_response", side_effect=RuntimeError("crash after commit")):
            with self.assertRaises(RuntimeError):
                self._approve_as(
                    application,
                    create_invoice=False,
                    membership_type=self.membership_type.name,
                    chapter=self.chapter.name,
                )
        frappe.db.rollback()
        self.assertEqual(frappe.db.get_value(SUBMISSION, application, "status"), "Approved")
        self.assertFalse(self._marker(application))

    def test_a_failed_retry_keeps_the_marker(self):
        application, _member = self._approved_with_failed_invoice()  # invoicing stays broken
        self._retry(application)
        self.assertTrue(self._marker(application))

    def test_approvals_that_are_not_failures_are_not_marked(self):
        """create_invoice=False (billed elsewhere) and an invoiced approval: neither is marked."""
        for create_invoice in (False, True):
            self.email = self._fresh_applicant_email()
            application = self._stage_and_confirm()
            self._approve_capturing_mail(application, create_invoice=create_invoice)
            self.assertFalse(self._marker(application), f"create_invoice={create_invoice}")

    def test_an_approval_without_an_invoice_requested_cannot_be_retried(self):
        application = self._stage_and_confirm()
        response, _mails, _outcomes, _errors = self._approve_capturing_mail(application, create_invoice=False)
        before = len(self._invoices_of(response["member"]))
        with self.assertRaises(frappe.ValidationError) as refused:
            self._retry(application)
        self.assertIn("no failed invoice to retry", str(refused.exception))
        self.assertEqual(len(self._invoices_of(response["member"])), before)

    def test_the_list_holds_a_marked_application_only(self):
        from verenigingen.api.membership_application_review import get_approved_applications_without_invoice

        failed, _member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        self.email = self._fresh_applicant_email()
        not_invoiced = self._stage_and_confirm()
        self._approve_capturing_mail(not_invoiced, create_invoice=False)
        with self.as_user(self.admin_user.email):
            names = [row.name for row in get_approved_applications_without_invoice()]
        self.assertIn(failed, names)
        self.assertNotIn(not_invoiced, names, "control: an approved, invoice-less, unmarked application")

    def test_a_member_who_is_no_longer_active_is_refused_and_keeps_the_marker(self):
        """PROBE SHORTCUT, stated: the Member's status is written directly to stand in for a termination
        (Quit); the refusal is what is proven, not that the state is reachable that way."""
        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        frappe.db.set_value("Member", member, "status", "Quit")
        with self.assertRaises(frappe.ValidationError) as refused:
            self._retry(application)
        self.assertIn("Reinstate the member first", str(refused.exception))
        self.assertEqual(self._invoices_of(member), [])
        self.assertTrue(self._marker(application), "the marker is kept: the invoice was never created")
        from verenigingen.api.membership_application_review import get_approved_applications_without_invoice

        with self.as_user(self.admin_user.email):
            self.assertNotIn(application, [r.name for r in get_approved_applications_without_invoice()])

    def test_a_submitted_non_membership_invoice_does_not_count_as_the_membership_invoice(self):
        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        other = self.create_test_sales_invoice(member)  # submitted by the helper; not a membership invoice
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", other.name, ["docstatus", "is_membership_invoice"], as_dict=True),
            {"docstatus": 1, "is_membership_invoice": 0},
            "control: a submitted invoice that is not a membership invoice",
        )
        response, _mails = self._retry(application)
        self.assertNotIn(response["invoice"], (None, other.name), "a membership invoice was created")

    def _approve_with_failing_submit(self, application):
        """Approve with the invoice INSERT succeeding and the SUBMIT failing: a draft membership invoice
        remains. The boundary is the secure-operation wrapper the invoice goes through; the insert still runs."""
        from types import SimpleNamespace

        from verenigingen.services.member.approval import application_payments

        real = application_payments.secure_document_operation

        def fail_submit(*args, **kwargs):
            if kwargs.get("operation") == "submit":
                return SimpleNamespace(success=False, errors=["forced submit failure"], doc_name=None)
            return real(*args, **kwargs)

        self.expectErrorLog("Membership Invoice Creation Failed", "Membership Invoice Security")
        # Mock justified: External Service boundary - the submit step is made to fail, nothing else
        with patch.object(application_payments, "secure_document_operation", fail_submit):
            return self._approve_capturing_mail(application, create_invoice=True)

    def test_a_draft_left_by_a_failed_submit_is_refused_and_no_second_invoice_is_created(self):
        application = self._stage_and_confirm()
        response, mails, _outcomes, _errors = self._approve_with_failing_submit(application)
        member = response["member"]
        self.assertTrue(response["invoice_failed"], response)
        self.assertEqual(mails, [])
        self.assertTrue(self._marker(application))
        drafts = frappe.get_all(
            "Sales Invoice",
            {"customer": frappe.db.get_value("Member", member, "customer"), "is_membership_invoice": 1, "docstatus": 0},
            pluck="name",
        )
        self.assertEqual(len(drafts), 1, "control: the failed submit left a draft membership invoice")

        with self.assertRaises(frappe.ValidationError) as refused:
            self._retry(application)

        self.assertIn("draft membership invoice exists", str(refused.exception))
        self.assertEqual(self._invoices_of(member), drafts, "no second invoice")
        self.assertTrue(self._marker(application), "the marker is kept")

    def test_a_submitted_invoice_created_another_way_is_mailed_not_duplicated(self):
        """PROBE SHORTCUT, stated: the 'other route' (scheduler or manual) is stood in for by calling the
        approval's own invoice helper directly. The held mail must carry THAT invoice's link, and nothing new
        is created."""
        from verenigingen.services.member.approval.membership_creation_service import MembershipCreationService

        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        doc = frappe.get_doc("Member", member)
        membership = frappe.get_doc("Membership", doc.current_membership_plan)
        existing = MembershipCreationService()._create_membership_invoice(
            doc, membership, frappe.get_doc("Membership Type", membership.membership_type)
        )
        self.assertEqual(existing.docstatus, 1, "control: a submitted membership invoice")

        response, mails = self._retry(application)

        self.assertEqual(response["invoice"], existing.name)
        self.assertEqual(self._invoices_of(member), [existing.name], "nothing new was created")
        self.assertEqual(len(mails), 1)
        self.assertIn(f"/payment/membership/{member}/{existing.name}", mails[0]["content"])
        self.assertFalse(self._marker(application))

    def test_a_failed_mail_keeps_the_marker_and_the_next_retry_resends_without_a_new_invoice(self):
        from verenigingen.utils.operation_result import OperationResult

        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        self.expectErrorLog("Approval Email Failed")
        # Mock justified: External Service - SMTP delivery fails
        with patch.object(EmailService, "_send_email_internal", return_value=OperationResult.fail("smtp down")):
            response, _mails = self._retry(application)
        self.assertTrue(response["invoice"])
        self.assertFalse(response["mail_sent"])
        self.assertTrue(self._marker(application), "no mail went out, so the marker stays")

        second, mails = self._retry(application)

        self.assertEqual(second["invoice"], response["invoice"])
        self.assertEqual(self._invoices_of(member), [response["invoice"]], "no second invoice")
        self.assertEqual(len(mails), 1)
        self.assertTrue(second["mail_sent"])
        self.assertFalse(self._marker(application))

    def _rejoin_with_failed_invoice(self):
        """(earlier membership, application, member): a member approved once without an invoice, terminated
        through the real termination service, then re-applying and approved again with invoicing broken.
        PROBE SHORTCUT, stated: only the first Membership's commitment_end_date is backdated so a past-dated
        termination can run (as test_approval_invoice_period does)."""
        from verenigingen.tests.support.termination_request import execute_real_termination

        self.expectErrorLog("Chapter Membership Error")
        first = self._stage_and_confirm()
        first_response, _m, _o, _e = self._approve_capturing_mail(first, create_invoice=False)
        member = first_response["member"]
        earlier_plan = frappe.db.get_value("Member", member, "current_membership_plan")
        frappe.db.set_value("Membership", earlier_plan, "commitment_end_date", add_days(today(), -60))
        execute_real_termination(self, member, add_days(today(), -30))
        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Quit")

        second = self._stage_and_confirm()
        self._make_invoicing_fail()
        response, _mails, _outcomes, _errors = self._approve_capturing_mail(second, create_invoice=True)
        self.assertTrue(response["invoice_failed"], response)
        self.assertEqual(response["member"], member, "the rejoiner is the same Member")
        self.assertNotEqual(frappe.db.get_value("Member", member, "current_membership_plan"), earlier_plan)
        self._fix_invoicing()
        return earlier_plan, second, member

    def _earlier_membership_invoice(self, member, earlier_plan, submitted):
        """An invoice of the EARLIER membership that survives on the shared Customer, as a paid one would
        (the termination cancels or deletes unpaid ones). PROBE SHORTCUT, stated: it is made with the
        approval's own invoice helper against the old Membership and a coverage start a year back; with
        submitted=False the submit step is made to fail, which leaves a draft."""
        from types import SimpleNamespace

        from verenigingen.services.member.approval import application_payments
        from verenigingen.services.member.approval.membership_creation_service import MembershipCreationService

        doc = frappe.get_doc("Member", member)
        membership = frappe.get_doc("Membership", earlier_plan)
        membership_type = frappe.get_doc("Membership Type", membership.membership_type)
        real = application_payments.secure_document_operation

        def fail_submit(*args, **kwargs):
            if kwargs.get("operation") == "submit":
                return SimpleNamespace(success=False, errors=["forced submit failure"], doc_name=None)
            return real(*args, **kwargs)

        service = MembershipCreationService()
        start = add_days(today(), -400)
        if submitted:
            invoice = service._create_membership_invoice(doc, membership, membership_type, period_start=start)
            self.assertTrue(invoice and invoice.docstatus == 1, "control: a submitted earlier invoice")
            return invoice.name
        self.expectErrorLog("Membership Invoice Creation Failed", "Membership Invoice Security")
        # Mock justified: External Service boundary - only the submit step is made to fail
        with patch.object(application_payments, "secure_document_operation", fail_submit):
            service._create_membership_invoice(doc, membership, membership_type, period_start=start)
        drafts = frappe.get_all(
            "Sales Invoice",
            {"customer": doc.customer, "membership": earlier_plan, "docstatus": 0},
            pluck="name",
        )
        self.assertEqual(len(drafts), 1, "control: a draft earlier invoice")
        return drafts[0]

    def test_a_submitted_invoice_of_an_earlier_membership_does_not_stand_in_for_this_one(self):
        """A rejoiner keeps the Customer and its old (often paid) membership invoices. The retry must bill the
        NEW membership and mail the NEW invoice's link, not mail the old one and leave the member unbilled."""
        earlier_plan, application, member = self._rejoin_with_failed_invoice()
        old_invoice = self._earlier_membership_invoice(member, earlier_plan, submitted=True)

        response, mails = self._retry(application)

        new_invoice = response["invoice"]
        self.assertTrue(new_invoice)
        self.assertNotEqual(new_invoice, old_invoice)
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", new_invoice, "membership"),
            frappe.db.get_value("Member", member, "current_membership_plan"),
        )
        self.assertEqual(len(mails), 1)
        self.assertIn(f"/payment/membership/{member}/{new_invoice}", mails[0]["content"])
        self.assertNotIn(old_invoice, mails[0]["content"])
        # The rejoiner was mailed at the first approval, so this mail may be in the recipient's cooldown and
        # skipped: the marker must then stay. Either way it matches whether the mail went out.
        self.assertEqual(bool(self._marker(application)), not response["mail_sent"])

    def test_a_draft_invoice_of_an_earlier_membership_does_not_block_this_retry(self):
        earlier_plan, application, member = self._rejoin_with_failed_invoice()
        old_draft = self._earlier_membership_invoice(member, earlier_plan, submitted=False)

        response, mails = self._retry(application)

        self.assertTrue(response["invoice"])
        self.assertNotEqual(response["invoice"], old_draft)
        self.assertEqual(frappe.db.get_value("Sales Invoice", old_draft, "docstatus"), 0, "the old draft is untouched")
        self.assertEqual(len(mails), 1)

    def _unlinked_membership_invoice(self, member, coverage_start):
        """A submitted membership invoice on the member's Customer with NO membership link, as some other
        writer might leave one. PROBE SHORTCUT, stated: it is made with the approval's own helper and then the
        `membership` link is blanked and the coverage start set directly, to ask the lookup's fallback."""
        from verenigingen.services.member.approval.membership_creation_service import MembershipCreationService

        doc = frappe.get_doc("Member", member)
        membership = frappe.get_doc("Membership", doc.current_membership_plan)
        invoice = MembershipCreationService()._create_membership_invoice(
            doc, membership, frappe.get_doc("Membership Type", membership.membership_type)
        )
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            {"membership": None, "custom_coverage_start_date": coverage_start},
            update_modified=False,
        )
        return invoice.name, membership

    def test_an_unlinked_invoice_covering_this_membership_is_mailed_not_duplicated(self):
        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        plan = frappe.db.get_value("Member", member, "current_membership_plan")
        start = frappe.db.get_value("Membership", plan, "start_date")
        unlinked, _membership = self._unlinked_membership_invoice(member, start)
        self.assertFalse(frappe.db.get_value("Sales Invoice", unlinked, "membership"), "control: no link")

        response, mails = self._retry(application)

        self.assertEqual(response["invoice"], unlinked)
        self.assertEqual(self._invoices_of(member), [unlinked], "nothing new was created")
        self.assertEqual(len(mails), 1)
        self.assertIn(f"/payment/membership/{member}/{unlinked}", mails[0]["content"])

    def test_an_invoice_linked_to_this_membership_is_found_whatever_its_coverage_start(self):
        """The link is the key; coverage is only the fallback for an unlinked invoice. A linked invoice whose
        coverage begins before the membership start is still this membership's, and is mailed, not duplicated."""
        from verenigingen.services.member.approval.membership_creation_service import MembershipCreationService

        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        doc = frappe.get_doc("Member", member)
        membership = frappe.get_doc("Membership", doc.current_membership_plan)
        linked = MembershipCreationService()._create_membership_invoice(
            doc,
            membership,
            frappe.get_doc("Membership Type", membership.membership_type),
            period_start=add_days(membership.start_date, -5),
        )
        self.assertEqual(frappe.db.get_value("Sales Invoice", linked.name, "membership"), membership.name)

        response, mails = self._retry(application)

        self.assertEqual(response["invoice"], linked.name)
        self.assertEqual(self._invoices_of(member), [linked.name])
        self.assertEqual(len(mails), 1)

    def test_an_unlinked_invoice_from_before_this_membership_is_ignored(self):
        """Control for the fallback: an unlinked invoice whose coverage starts BEFORE the membership start
        belongs to something earlier. It must not be mailed, and a new invoice is created."""
        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        plan = frappe.db.get_value("Member", member, "current_membership_plan")
        start = frappe.db.get_value("Membership", plan, "start_date")
        unlinked, _membership = self._unlinked_membership_invoice(member, add_days(start, -400))

        response, mails = self._retry(application)

        self.assertTrue(response["invoice"])
        self.assertNotEqual(response["invoice"], unlinked)
        self.assertEqual(len(mails), 1)
        self.assertIn(f"/payment/membership/{member}/{response['invoice']}", mails[0]["content"])
        self.assertNotIn(unlinked, mails[0]["content"])

    def test_a_skipped_mail_is_not_a_sent_mail_and_keeps_the_marker(self):
        """The mail service answers success with skipped=True when emails are off (or the notification is
        disabled, in cooldown, opted out). The held mail was NOT sent, so the marker stays and the response says why."""
        from verenigingen.tests.fixtures.singleton_backup import singleton_backup

        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        # The master switch is a scalar field, which singleton_backup restores (so do the
        # notification_types rows, since #2091).
        with singleton_backup("Verenigingen Email Configuration"):
            frappe.db.set_single_value("Verenigingen Email Configuration", "master_email_enabled", 0)
            response, mails = self._retry(application)
            self.assertEqual(mails, [], "control: nothing was sent while emails are off")

        self.assertFalse(response["mail_sent"])
        self.assertIn("skipped", response["message"].lower())
        self.assertTrue(response["invoice"], "the invoice itself was created")
        self.assertTrue(self._marker(application), "nothing was sent, so the marker stays")
        second, mails = self._retry(application)  # notification enabled again
        self.assertTrue(second["mail_sent"])
        self.assertEqual(second["invoice"], response["invoice"], "the resend creates no new invoice")
        self.assertEqual(len(mails), 1)
        self.assertFalse(self._marker(application))

    def test_a_late_retry_covers_the_period_approval_would_have(self):
        """The first invoice discharges the running period from the membership's start, not from the day of
        the retry; otherwise the schedule's next invoice would overlap it. The schedule's next_invoice_date is
        the one the REAL approval wrote (approval + period). PROBE SHORTCUT, stated: the membership start and
        that date are both moved back by the same ONE MONTH (the fixture's frequency is Monthly), standing in for a
        retry made a period after approval."""
        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        plan = frappe.db.get_value("Member", member, "current_membership_plan")
        schedule = frappe.db.get_value("Membership Dues Schedule", {"member": member, "is_template": 0}, "name")
        written = frappe.db.get_value("Membership Dues Schedule", schedule, "next_invoice_date")
        start = add_months(frappe.db.get_value("Membership", plan, "start_date"), -1)
        frappe.db.set_value("Membership", plan, "start_date", start)
        frappe.db.set_value("Membership Dues Schedule", schedule, "next_invoice_date", add_months(written, -1))

        response, _mails = self._retry(application)

        invoice = frappe.get_doc("Sales Invoice", response["invoice"])
        self.assertEqual(getdate(invoice.custom_coverage_start_date), getdate(start))
        self.assertEqual(
            add_days(getdate(invoice.custom_coverage_end_date), 1),
            getdate(add_months(written, -1)),
            "the next period starts the day after this one ends: no overlap, no gap",
        )
