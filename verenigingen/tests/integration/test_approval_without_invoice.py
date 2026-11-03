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

import frappe

from verenigingen.services.communication.email_service import EmailService
from verenigingen.tests.integration.test_application_record_approval import ApprovalCase

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
