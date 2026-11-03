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

APPROVAL_ERRORS = ["Approval Email Exception", "Approval Email Failed", "Approval Notification Failed"]


class TestApprovalWithoutInvoice(ApprovalCase):
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

    def test_failed_invoice_still_sends_mail_without_link_and_is_not_a_clean_approval(self):
        """invoice_failed (#1774) stays distinct from 'no invoice requested': it is reported as a failure."""
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
        self._assert_mail_without_payment_link(mails, outcomes)
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
