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

    def _break_invoicing(self):
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
        self._break_invoicing()
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

        self.assertIn("already has an invoice", str(refused.exception))
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
        self.assertIn("already has an invoice", str(refused.exception))
        self.assertEqual(len(self._invoices_of(response["member"])), 1)

    def test_the_retry_takes_the_member_row_lock_before_creating_the_invoice(self):
        """Two staff at once: the Member row is read FOR UPDATE before the invoice is created, so the second
        waits for the first's commit and then finds the invoice. Probe: the queries of the retry
        (PROBE LIMIT, stated: this shows the lock is requested, not contention between two connections)."""
        from verenigingen.tests.utils.query_counter import count_queries

        application, member = self._approved_with_failed_invoice()
        self._fix_invoicing()
        with count_queries() as counter:
            self._retry(application)
        sql = [q.lower() for q in counter.queries]
        locked = [i for i, q in enumerate(sql) if "tabmember`" in q and "for update" in q and "tabmember " not in q]
        created = [i for i, q in enumerate(sql) if "insert into `tabsales invoice`" in q]
        self.assertTrue(locked, "no SELECT ... FOR UPDATE on Member")
        self.assertTrue(created, "control: an invoice was inserted")
        self.assertLess(locked[0], created[0], "the lock must come before the invoice insert")

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

    def test_the_retry_list_shows_only_what_the_caller_may_retry_and_drops_it_once_invoiced(self):
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
